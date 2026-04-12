"""
WebSocket auction server — SDD §5.6.

Real-time bidding via python-socketio (async mode).
Namespace: /auction — all events live here.

Events emitted to clients:
  current_state    — full auction snapshot (on connect / reconnect)
  bid_confirmed    — accepted bid acknowledgement (to submitting socket only)
  bid_update       — new accepted bid (broadcast to room, masked user_id)
  bid_rejected     — rejection (to submitting socket only)
  watcher_update   — watcher count changed
  timer_extended   — anti-snipe triggered
  pong             — heartbeat reply

Events received from clients:
  place_bid        — { amount: int }
  ping             — heartbeat (client sends every 30s)

Session keys (sio.save_session / sio.get_session):
  user_id, auction_id, connected_at, pubsub_task
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import socketio

from app.core.config import settings
from app.core.security import decode_access_token
from app.services.auction.service import _k, _root

logger = logging.getLogger(__name__)

# ── Socket.IO server ─────────────────────────────────────────────

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.ALLOWED_ORIGINS or "*",
    ping_interval=30,
    ping_timeout=10,
    logger=False,
    engineio_logger=False,
)

# ── Redis accessor (injected at startup, overridden in tests) ────

_redis_factory = None


def set_redis_factory(factory):
    """Called once at app startup to inject the Redis factory."""
    global _redis_factory
    _redis_factory = factory


async def _get_redis():
    """Get a Redis client. Uses the injected factory."""
    if _redis_factory is None:
        from app.core.redis import get_redis
        return get_redis()
    return _redis_factory()


# ── Helpers ──────────────────────────────────────────────────────

def _channel(auction_id: str) -> str:
    return f"channel:auction:{auction_id}"


def _room(auction_id: str) -> str:
    return f"auction_{auction_id}"


def _cents_to_jod(cents: int) -> float:
    """Convert integer cents to JOD float for client payloads."""
    return round(cents / 100, 2)


def mask_user_id(user_id: str) -> str:
    """Privacy mask: first char + '***' + last 3 chars.

    For short IDs (< 5 chars), just return '***'.
    """
    if not user_id or len(user_id) < 5:
        return "***"
    return f"{user_id[0]}***{user_id[-3:]}"


async def _build_current_state(auction_id: str, redis) -> dict | None:
    """Build the current_state payload from individual Redis keys."""
    status = await redis.get(_k(auction_id, "status"))
    if not status:
        return None

    price = await redis.get(_k(auction_id, "price"))
    bid_count = await redis.get(_k(auction_id, "bid_count"))
    watcher_ct = await redis.get(_k(auction_id, "watcher_ct"))
    ext_ct = await redis.get(_k(auction_id, "extension_ct"))
    last_bidder = await redis.get(_k(auction_id, "last_bidder"))
    min_inc = await redis.get(_k(auction_id, "min_increment"))
    buy_now = await redis.get(_k(auction_id, "buy_now"))
    root_ttl = await redis.ttl(_root(auction_id))

    buy_now_val = int(buy_now) if buy_now else 0

    return {
        "auction_id": auction_id,
        "current_price": _cents_to_jod(int(price)) if price else 0,
        "status": status,
        "bid_count": int(bid_count) if bid_count else 0,
        "watcher_count": int(watcher_ct) if watcher_ct else 0,
        "extension_count": int(ext_ct) if ext_ct else 0,
        "last_bidder": mask_user_id(last_bidder) if last_bidder else None,
        "min_increment": _cents_to_jod(int(min_inc)) if min_inc else 0,
        "buy_now_price": _cents_to_jod(buy_now_val) if buy_now_val > 0 else None,
        "remaining_seconds": root_ttl if root_ttl > 0 else 0,
    }


async def _get_recent_bids(auction_id: str, limit: int = 20) -> list[dict]:
    """Fetch last N bids from PostgreSQL for state reconciliation."""
    try:
        from sqlalchemy import select
        from app.core.database import async_session_factory
        from app.services.auction.models import Bid

        async with async_session_factory() as db:
            result = await db.execute(
                select(Bid)
                .where(Bid.auction_id == auction_id)
                .order_by(Bid.created_at.desc())
                .limit(limit)
            )
            bids = result.scalars().all()
            return [
                {
                    "id": b.id,
                    "user_id": mask_user_id(str(b.user_id)),
                    "amount": _cents_to_jod(int(b.amount)),
                    "currency": b.currency,
                    "created_at": str(b.created_at),
                }
                for b in reversed(bids)  # oldest-first for replay
            ]
    except Exception:
        logger.warning("Failed to fetch recent bids for %s", auction_id)
        return []


# ── Pub/Sub listener ─────────────────────────────────────────────

async def _start_pubsub_listener(auction_id: str, redis):
    """Subscribe to Redis Pub/Sub channel and relay messages to the
    Socket.IO room. Stored in sio session for cleanup on disconnect."""
    channel_name = _channel(auction_id)
    room = _room(auction_id)

    try:
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel_name)

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                data = json.loads(message["data"])
                event = data.get("event", "bid_update")
                payload = data.get("payload", data)
                await sio.emit(event, payload, room=room, namespace="/auction")
            except (json.JSONDecodeError, Exception):
                logger.warning("Bad Pub/Sub message on %s", channel_name)
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Pub/Sub listener error for %s", auction_id)
    finally:
        try:
            await pubsub.unsubscribe(channel_name)
            await pubsub.aclose()
        except Exception:
            pass


# Track Pub/Sub tasks per room to avoid duplicates
_pubsub_tasks: dict[str, asyncio.Task] = {}


def _ensure_pubsub(auction_id: str, redis) -> asyncio.Task | None:
    """Start a Pub/Sub listener for this auction if not already running.
    Returns the task for storage in sio session."""
    room = _room(auction_id)
    if room not in _pubsub_tasks or _pubsub_tasks[room].done():
        task = asyncio.create_task(_start_pubsub_listener(auction_id, redis))
        _pubsub_tasks[room] = task
        return task
    return _pubsub_tasks[room]


# ── /auction namespace ───────────────────────────────────────────

class AuctionNamespace(socketio.AsyncNamespace):
    """Socket.IO namespace for real-time auction bidding."""

    async def on_connect(self, sid, environ, auth):
        """Handle new WebSocket connection.

        Auth dict must contain { "token": "<JWT>", "auction_id": "<uuid>" }.

        Validates:
          1. JWT signature + expiry (ConnectionRefusedError('4401') if bad)
          2. Auction exists in Redis and status is ACTIVE or SCHEDULED
          3. Save session, join room, start Pub/Sub
          4. Emit current_state + recent bids for reconciliation
          5. INCR watcher_ct, broadcast watcher_update
        """
        # ── 1. Extract and validate JWT ──────────────────────────
        if not auth or "token" not in auth:
            logger.warning("WS connect without auth from sid=%s", sid)
            raise ConnectionRefusedError("4401")

        token = auth["token"]
        auction_id = auth.get("auction_id", "")

        payload = decode_access_token(token)
        if payload is None:
            logger.info("WS connect with invalid/expired JWT, sid=%s", sid)
            raise ConnectionRefusedError("4401")

        user_id = payload.sub

        # ── 1b. Check per-user WebSocket connection limit (max 5) ──
        redis = await _get_redis()

        from app.core.middleware import check_ws_connection_limit
        if not await check_ws_connection_limit(user_id, redis):
            logger.warning("WS connect rejected: user=%s exceeded 5 connection limit", user_id)
            raise ConnectionRefusedError("4429")

        # ── 2. Verify auction exists and is ACTIVE or SCHEDULED ──

        status = await redis.get(_k(auction_id, "status"))
        if status not in ("ACTIVE", "SCHEDULED"):
            logger.info("WS connect to non-active auction=%s status=%s", auction_id, status)
            raise ConnectionRefusedError("4404")

        # ── 3. Save session, join room, start Pub/Sub ────────────
        room = _room(auction_id)
        self.enter_room(sid, room)

        pubsub_task = _ensure_pubsub(auction_id, redis)

        await self.save_session(sid, {
            "user_id": user_id,
            "auction_id": auction_id,
            "connected_at": time.time(),
            "pubsub_task": pubsub_task,
        })

        # ── 4. Emit current_state + recent bids ─────────────────
        current = await _build_current_state(auction_id, redis)
        recent_bids = await _get_recent_bids(auction_id)
        await self.emit("current_state", {
            **(current or {}),
            "recent_bids": recent_bids,
        }, to=sid)

        # ── 5. INCR watcher_ct, broadcast ───────────────────────
        new_count = await redis.incr(_k(auction_id, "watcher_ct"))
        await self.emit("watcher_update", {
            "auction_id": auction_id,
            "watcher_count": new_count,
        }, room=room)

        logger.info(
            "WS connected: sid=%s user=%s auction=%s watchers=%d",
            sid, user_id, auction_id, new_count,
        )

    async def on_place_bid(self, sid, data):
        """Handle place_bid event from client.

        data: { "amount": int }

        On ACCEPTED:
          1. Emit bid_confirmed to submitting socket
          2. PUBLISH bid_update to Redis channel (fans out to all instances)
          3. Queue Celery task for PostgreSQL persistence
          4. Anti-snipe handled atomically inside Lua script
        On REJECTED:
          5. Emit bid_rejected to submitting socket only
        """
        session = await self.get_session(sid)
        if not session:
            await self.emit("bid_rejected", {
                "reason": "NOT_CONNECTED",
                "message": "Not connected to an auction room",
            }, to=sid)
            return

        auction_id = session["auction_id"]
        user_id = session["user_id"]

        amount = data.get("amount") if isinstance(data, dict) else None
        if not amount or not isinstance(amount, (int, float)) or amount <= 0:
            await self.emit("bid_rejected", {
                "reason": "INVALID_AMOUNT",
                "message": "Amount must be a positive number",
            }, to=sid)
            return

        amount = int(amount)
        redis = await _get_redis()

        # ── Atomic Lua validation (includes anti-snipe) ──────────
        from app.services.auction.service import place_bid

        result = await place_bid(auction_id, user_id, amount, redis)

        if not result.accepted:
            rejection = {
                "reason": result.rejection_reason,
                "message": f"Bid rejected: {result.rejection_reason}",
                "auction_id": auction_id,
                "amount": _cents_to_jod(amount),
            }
            if result.min_required is not None:
                rejection["min_required"] = _cents_to_jod(result.min_required)
            await self.emit("bid_rejected", rejection, to=sid)
            return

        # ── ACCEPTED ─────────────────────────────────────────────
        bid_count_str = await redis.get(_k(auction_id, "bid_count"))
        bid_count = int(bid_count_str) if bid_count_str else 0
        price_jod = _cents_to_jod(result.new_price)

        # 1. bid_confirmed to submitting socket only
        confirmed_payload = {
            "auction_id": auction_id,
            "amount": price_jod,
            "bid_count": bid_count,
            "currency": "JOD",
            "timestamp": time.time(),
        }
        if result.buy_now:
            confirmed_payload["buy_now"] = True
        await self.emit("bid_confirmed", confirmed_payload, to=sid)

        # 2. PUBLISH bid_update to Redis channel (cross-instance fan-out)
        bid_payload = {
            "auction_id": auction_id,
            "user_id": mask_user_id(user_id),
            "amount": price_jod,
            "bid_count": bid_count,
            "currency": "JOD",
            "timestamp": time.time(),
        }
        if result.buy_now:
            bid_payload["buy_now"] = True
        await redis.publish(_channel(auction_id), json.dumps({
            "event": "bid_update",
            "payload": bid_payload,
        }))

        # 3. Queue Celery task for PostgreSQL persistence
        try:
            from app.tasks.auction import insert_bid_to_db
            insert_bid_to_db.delay(auction_id, user_id, amount, "JOD")
        except Exception:
            logger.warning("Failed to queue bid persistence for auction=%s", auction_id)

        # 4. Buy It Now — auction ended atomically in Lua, finalize in DB
        if result.buy_now:
            logger.info(
                "BUY_NOW triggered: auction=%s buyer=%s price=%d",
                auction_id, user_id, result.new_price,
            )
            # Publish auction_ended event
            await redis.publish(_channel(auction_id), json.dumps({
                "event": "auction_ended",
                "payload": {
                    "auction_id": auction_id,
                    "winner_id": mask_user_id(user_id),
                    "final_price": price_jod,
                    "bid_count": bid_count,
                    "outcome": "buy_now",
                },
            }))
            # Queue Celery task to finalize in DB (escrow, notifications, cleanup)
            try:
                from app.tasks.auction import finalize_buy_now
                finalize_buy_now.delay(auction_id, user_id, result.new_price)
            except Exception:
                logger.exception("Failed to queue finalize_buy_now for auction=%s", auction_id)
            return

        # 5. Anti-snipe handled atomically inside Lua script
        if result.extended:
            ext_ct_str = await redis.get(_k(auction_id, "extension_ct"))
            ext_count = int(ext_ct_str) if ext_ct_str else 0

            timer_payload = {
                "auction_id": auction_id,
                "remaining_seconds": result.new_ttl,
                "extension_count": ext_count,
                "extension_seconds": 180,
            }
            await redis.publish(_channel(auction_id), json.dumps({
                "event": "timer_extended",
                "payload": timer_payload,
            }))

    async def on_ping(self, sid, data=None):
        """Application-level heartbeat. Client sends ping every 30s,
        server replies with pong. If no ping within 45s, server
        can disconnect (handled by engine.io ping_interval/timeout)."""
        await self.emit("pong", {
            "timestamp": time.time(),
        }, to=sid)

    async def on_disconnect(self, sid):
        """Handle WebSocket disconnection.

        DECR watcher_ct, broadcast watcher_update, clean up session.
        """
        session = await self.get_session(sid)
        if not session:
            return

        auction_id = session.get("auction_id")
        if not auction_id:
            return

        redis = await _get_redis()

        # DECR watcher_ct (floor at 0)
        watcher_key = _k(auction_id, "watcher_ct")
        new_count = await redis.decr(watcher_key)
        if new_count < 0:
            await redis.set(watcher_key, "0")
            new_count = 0

        room = _room(auction_id)
        await self.emit("watcher_update", {
            "auction_id": auction_id,
            "watcher_count": new_count,
        }, room=room)

        self.leave_room(sid, room)

        # Release per-user WS connection slot
        user_id = session.get("user_id")
        if user_id:
            from app.core.middleware import release_ws_connection
            await release_ws_connection(user_id, redis)

        # Clean up Pub/Sub task if room is empty
        try:
            room_sids = self.server.manager.get_participants("/auction", room)
            has_members = bool(next(iter(room_sids), None))
        except (StopIteration, TypeError):
            has_members = False

        if not has_members and room in _pubsub_tasks:
            task = _pubsub_tasks.pop(room)
            task.cancel()

        logger.info(
            "WS disconnected: sid=%s user=%s auction=%s watchers=%d",
            sid, session.get("user_id"), auction_id, new_count,
        )


# Register namespace
sio.register_namespace(AuctionNamespace("/auction"))

# Wrap as ASGI app — main.py uses socketio.ASGIApp(sio, other_asgi_app=app)
sio_app = socketio.ASGIApp(sio, socketio_path="")
