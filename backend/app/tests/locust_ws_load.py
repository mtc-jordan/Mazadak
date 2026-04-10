"""
Locust load test for WebSocket auction server — SDD §5.6 performance.

Target: 500 concurrent WebSocket connections, 1 bid per 30s per user,
<100ms P95 broadcast latency for bid_update events.

Usage:
    locust -f app/tests/locust_ws_load.py --headless \
        -u 500 -r 50 --run-time 5m \
        --host http://localhost:8000

Requires a running backend with:
  - Redis populated with an ACTIVE auction
  - Valid JWT tokens (or set LOCUST_AUTH_TOKEN env var)
"""

from __future__ import annotations

import json
import os
import time
from uuid import uuid4

import socketio
from locust import User, between, events, task


# ── Configuration ────────────────────────────────────────────────

AUCTION_ID = os.getenv("LOCUST_AUCTION_ID", "test-auction-load")
AUTH_TOKEN = os.getenv("LOCUST_AUTH_TOKEN", "")
WS_NAMESPACE = "/auction"


class AuctionWSUser(User):
    """Simulates a WebSocket client connected to the /auction namespace.

    Each user:
      1. Connects with JWT + auction_id
      2. Sends a place_bid every 25-35s
      3. Tracks bid_confirmed + bid_update latency
    """
    wait_time = between(25, 35)
    abstract = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sio = None
        self._bid_send_times: dict[str, float] = {}
        self._connected = False

    def on_start(self):
        """Connect to the WebSocket server."""
        self.sio = socketio.Client(
            reconnection=False,
            logger=False,
            engineio_logger=False,
        )

        # Track events for Locust reporting
        @self.sio.on("current_state", namespace=WS_NAMESPACE)
        def on_current_state(data):
            events.request.fire(
                request_type="WS",
                name="current_state",
                response_time=0,
                response_length=len(json.dumps(data)),
                exception=None,
                context={},
            )

        @self.sio.on("bid_confirmed", namespace=WS_NAMESPACE)
        def on_bid_confirmed(data):
            # Measure round-trip time from bid send to confirmation
            send_time = self._bid_send_times.pop("last_bid", None)
            rt = (time.time() - send_time) * 1000 if send_time else 0
            events.request.fire(
                request_type="WS",
                name="bid_confirmed",
                response_time=rt,
                response_length=len(json.dumps(data)),
                exception=None,
                context={},
            )

        @self.sio.on("bid_update", namespace=WS_NAMESPACE)
        def on_bid_update(data):
            # Measure broadcast latency from bid timestamp
            bid_ts = data.get("timestamp", 0)
            rt = (time.time() - bid_ts) * 1000 if bid_ts else 0
            events.request.fire(
                request_type="WS",
                name="bid_update (broadcast)",
                response_time=rt,
                response_length=len(json.dumps(data)),
                exception=None,
                context={},
            )

        @self.sio.on("bid_rejected", namespace=WS_NAMESPACE)
        def on_bid_rejected(data):
            events.request.fire(
                request_type="WS",
                name="bid_rejected",
                response_time=0,
                response_length=len(json.dumps(data)),
                exception=None,
                context={},
            )

        @self.sio.on("timer_extended", namespace=WS_NAMESPACE)
        def on_timer_extended(data):
            events.request.fire(
                request_type="WS",
                name="timer_extended",
                response_time=0,
                response_length=len(json.dumps(data)),
                exception=None,
                context={},
            )

        @self.sio.on("watcher_update", namespace=WS_NAMESPACE)
        def on_watcher_update(data):
            pass  # Ignore for metrics

        # Connect
        start = time.time()
        try:
            self.sio.connect(
                self.host,
                namespaces=[WS_NAMESPACE],
                auth={
                    "token": AUTH_TOKEN,
                    "auction_id": AUCTION_ID,
                },
                transports=["websocket"],
            )
            rt = (time.time() - start) * 1000
            self._connected = True
            events.request.fire(
                request_type="WS",
                name="connect",
                response_time=rt,
                response_length=0,
                exception=None,
                context={},
            )
        except Exception as e:
            rt = (time.time() - start) * 1000
            self._connected = False
            events.request.fire(
                request_type="WS",
                name="connect",
                response_time=rt,
                response_length=0,
                exception=e,
                context={},
            )

    def on_stop(self):
        """Disconnect from the WebSocket server."""
        if self.sio and self._connected:
            try:
                self.sio.disconnect()
            except Exception:
                pass

    @task
    def place_bid(self):
        """Send a place_bid event with a random amount."""
        if not self._connected or not self.sio:
            return

        # Generate a bid amount (increments of 1000 fils = 1 JOD)
        amount = 10000 + (hash(uuid4()) % 100) * 1000

        start = time.time()
        self._bid_send_times["last_bid"] = start
        try:
            self.sio.emit(
                "place_bid",
                {"amount": amount},
                namespace=WS_NAMESPACE,
            )
            rt = (time.time() - start) * 1000
            events.request.fire(
                request_type="WS",
                name="place_bid (send)",
                response_time=rt,
                response_length=0,
                exception=None,
                context={},
            )
        except Exception as e:
            rt = (time.time() - start) * 1000
            events.request.fire(
                request_type="WS",
                name="place_bid (send)",
                response_time=rt,
                response_length=0,
                exception=e,
                context={},
            )
