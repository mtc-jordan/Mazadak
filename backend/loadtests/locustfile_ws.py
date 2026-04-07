"""
Locust load test — 500 concurrent WebSocket connections.

Simulates auction watchers connecting via Socket.IO, receiving
real-time bid broadcasts, and a fraction submitting bids.

Usage:
    # Start the backend first:
    #   uvicorn app.main:app --host 0.0.0.0 --port 8000

    # Run Locust (headless, 500 users, 60s duration):
    locust -f loadtests/locustfile_ws.py \
        --headless -u 500 -r 50 --run-time 60s \
        --host http://localhost:8000

    # Or with the Locust web UI:
    locust -f loadtests/locustfile_ws.py --host http://localhost:8000

Prerequisites:
    - pip install locust python-socketio[client] websocket-client
    - A running MZADAK backend with at least one ACTIVE auction in Redis
    - Valid JWT tokens (or set AUCTION_ID / JWT_TOKEN env vars)

Environment variables:
    AUCTION_ID   — UUID of an active auction (required)
    JWT_TOKEN    — Valid JWT access token (required)
    WS_URL       — WebSocket base URL (default: http://localhost:8000)
    BID_FRACTION — Fraction of users that submit bids (default: 0.1)
"""

from __future__ import annotations

import json
import os
import random
import time
from uuid import uuid4

import socketio
from locust import User, between, events, task
from locust.exception import StopUser


# ── Configuration ────────────────────────────────────────────────

AUCTION_ID = os.environ.get("AUCTION_ID", "test-auction-id")
JWT_TOKEN = os.environ.get("JWT_TOKEN", "test-jwt-token")
WS_URL = os.environ.get("WS_URL", "http://localhost:8000")
BID_FRACTION = float(os.environ.get("BID_FRACTION", "0.1"))


# ── Metrics helpers ──────────────────────────────────────────────

def fire_success(name: str, elapsed_ms: float, response_length: int = 0):
    """Report a successful event to Locust."""
    events.request.fire(
        request_type="WSS",
        name=name,
        response_time=elapsed_ms,
        response_length=response_length,
        exception=None,
        context={},
    )


def fire_failure(name: str, elapsed_ms: float, exc: Exception):
    """Report a failed event to Locust."""
    events.request.fire(
        request_type="WSS",
        name=name,
        response_time=elapsed_ms,
        response_length=0,
        exception=exc,
        context={},
    )


# ── Socket.IO Locust User ───────────────────────────────────────

class AuctionWatcher(User):
    """Simulates a single WebSocket auction watcher.

    Lifecycle:
      1. Connect to /ws with JWT + auction_id
      2. Receive current_state event
      3. Periodically receive bid_update / watcher_update events
      4. With probability BID_FRACTION, submit bids at random intervals
      5. Stay connected for the test duration
    """

    wait_time = between(1, 5)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sio: socketio.Client | None = None
        self.connected = False
        self.auction_id = AUCTION_ID
        self.current_price = 0.0
        self.bid_count = 0
        self.events_received = 0
        self.is_bidder = random.random() < BID_FRACTION
        self.user_id = str(uuid4())

    def on_start(self):
        """Called when a simulated user starts. Connects to WebSocket."""
        self.sio = socketio.Client(
            reconnection=False,
            logger=False,
            engineio_logger=False,
        )

        self._register_handlers()

        start = time.time()
        try:
            self.sio.connect(
                f"{WS_URL}/ws",
                auth={
                    "token": JWT_TOKEN,
                    "auction_id": self.auction_id,
                },
                transports=["websocket"],
                wait_timeout=10,
            )
            elapsed = (time.time() - start) * 1000
            fire_success("ws_connect", elapsed)
            self.connected = True
        except Exception as exc:
            elapsed = (time.time() - start) * 1000
            fire_failure("ws_connect", elapsed, exc)
            raise StopUser()

    def _register_handlers(self):
        """Register Socket.IO event handlers."""

        @self.sio.on("current_state")
        def on_current_state(data):
            self.current_price = data.get("current_price", 0)
            self.bid_count = data.get("bid_count", 0)
            self.events_received += 1
            fire_success("recv_current_state", 0, len(json.dumps(data)))

        @self.sio.on("bid_update")
        def on_bid_update(data):
            self.current_price = data.get("amount", self.current_price)
            self.bid_count = data.get("bid_count", self.bid_count)
            self.events_received += 1
            fire_success("recv_bid_update", 0, len(json.dumps(data)))

        @self.sio.on("watcher_update")
        def on_watcher_update(data):
            self.events_received += 1
            fire_success("recv_watcher_update", 0, len(json.dumps(data)))

        @self.sio.on("bid_rejected")
        def on_bid_rejected(data):
            self.events_received += 1
            fire_success("recv_bid_rejected", 0, len(json.dumps(data)))

        @self.sio.on("timer_extended")
        def on_timer_extended(data):
            self.events_received += 1
            fire_success("recv_timer_extended", 0, len(json.dumps(data)))

        @self.sio.on("error")
        def on_error(data):
            fire_failure(
                "recv_error", 0,
                Exception(f"Server error: {data.get('message', 'unknown')}"),
            )

    @task(10)
    def watch(self):
        """Most users just watch — this is a no-op task that lets
        Locust maintain the user count while events flow passively."""
        if not self.connected:
            raise StopUser()
        # Passive watching — events are received via callbacks

    @task(1)
    def place_bid(self):
        """Submit a bid. Only runs for 'bidder' users."""
        if not self.connected or not self.is_bidder:
            return

        # Bid slightly above current price + typical increment
        amount = self.current_price + random.uniform(26.0, 100.0)
        amount = round(amount, 3)

        start = time.time()
        try:
            self.sio.emit("bid", {"amount": amount})
            elapsed = (time.time() - start) * 1000
            fire_success("emit_bid", elapsed)
        except Exception as exc:
            elapsed = (time.time() - start) * 1000
            fire_failure("emit_bid", elapsed, exc)

    def on_stop(self):
        """Disconnect when the simulated user stops."""
        if self.sio and self.connected:
            start = time.time()
            try:
                self.sio.disconnect()
                elapsed = (time.time() - start) * 1000
                fire_success("ws_disconnect", elapsed)
            except Exception as exc:
                elapsed = (time.time() - start) * 1000
                fire_failure("ws_disconnect", elapsed, exc)
            self.connected = False
