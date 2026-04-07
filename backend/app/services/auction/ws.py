"""
WebSocket auction server — SDD §5.6.

Real-time bidding via python-socketio (async mode).
Each auction room is a Socket.IO "room" named auction:{id}.
Bid updates are fanned out via Redis Pub/Sub so that multiple
server instances stay in sync (horizontal scaling).

Events emitted to clients:
  current_state    — full auction snapshot (on connect / reconnect)
  bid_update       — new accepted bid
  bid_rejected     — rejection (to submitting socket only)
  watcher_update   — watcher count changed
  timer_extended   — anti-snipe triggered

Events received from clients:
  bid              — { amount: float }

Heartbeat: PING every 30s, close on no PONG within 10s.
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

# Wrap as ASGI app for mounting on FastAPI
sio_app = socketio.ASGIApp(sio, socketio_path="")

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


# ── Per-connection state ─────────────────────────────────────────
# sid → { user_id, auction_id, connected_at }
_sessions: dict[str, dict[str, Any]] = {}

# Active Pub/Sub listener tasks per room — only one per auction
_pubsub_tasks: dict[str, asyncio.Task] = {}


# ── Helpers ──────────────────────────────────────────────────────

def _auction_key(auction_id: str) -> str:
    return f"auction:{auction_id}"


def _channel(auction_id: str) -> str:
    return f"channel:auction:{auction_id}"


def _room(auction_id: str) -> str:
    return f"auction:{auction_id}"


async def _build_current_state(auction_id: str, redis) -> dict | None:
    """Build the current_state payload from Redis Hash."""
    state = await redis.hgetall(_auction_key(auction_id))
    if not state:
        return None
    return {
        "auction_id": auction_id,
        "current_price": float(state.get("current_price", "0")),
        "status": state.get("status", ""),
        "bid_count": int(state.get("bid_count", "0")),
        "watcher_count": int(state.get("watcher_count", "0")),
        "extension_count": int(state.get("extension_count", "0")),
        "last_bidder": state.get("last_bidder") or None,
        "min_increment": float(state.get("min_increment", "25")),
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
                    "user_id": b.user_id,
                    "amount": float(b.amount),
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
    Socket.IO room. One listener per auction, shared across all
    connections in that room."""
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
                await sio.emit(event, payload, room=room)
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


def _ensure_pubsub(auction_id: str, redis):
    """Start a Pub/Sub listener for this auction if not already running."""
    room = _room(auction_id)
    if room not in _pubsub_tasks or _pubsub_tasks[room].done():
        task = asyncio.create_task(_start_pubsub_listener(auction_id, redis))
        _pubsub_tasks[room] = task


# ── Socket.IO events ─────────────────────────────────────────────

@sio.event
async def connect(sid, environ, auth):
    """Handle new WebSocket connection.

    Auth dict must contain { "token": "<JWT>", "auction_id": "<uuid>" }.

    Validates:
      1. JWT signature + expiry (disconnect code 4401 if bad)
      2. Auction exists in Redis and status == ACTIVE
      3. Subscribe to Redis Pub/Sub channel
      4. Emit current_state + recent bids for state reconciliation
      5. INCR watcher_count, broadcast watcher_update
    """
    # ── 1. Extract and validate JWT ──────────────────────────
    if not auth or "token" not in auth:
        logger.warning("WS connect without auth from sid=%s", sid)
        await sio.disconnect(sid)
        return False

    token = auth["token"]
    auction_id = auth.get("auction_id", "")

    payload = decode_access_token(token)
    if payload is None:
        logger.info("WS connect with invalid/expired JWT, sid=%s", sid)
        # Emit error before disconnect so client knows the reason
        await sio.emit("error", {
            "code": 4401,
            "message": "Invalid or expired token",
        }, to=sid)
        await sio.disconnect(sid)
        return False

    user_id = payload.sub

    # ── 2. Verify auction exists and is ACTIVE ───────────────
    redis = await _get_redis()

    state = await redis.hgetall(_auction_key(auction_id))
    if not state or state.get("status") != "ACTIVE":
        await sio.emit("error", {
            "code": 4404,
            "message": "Auction not found or not active",
        }, to=sid)
        await sio.disconnect(sid)
        return False

    # ── 3. Join room and start Pub/Sub ───────────────────────
    room = _room(auction_id)
    sio.enter_room(sid, room)

    _sessions[sid] = {
        "user_id": user_id,
        "auction_id": auction_id,
        "connected_at": time.time(),
    }

    _ensure_pubsub(auction_id, redis)

    # ── 4. Emit current_state + recent bids ──────────────────
    current = await _build_current_state(auction_id, redis)
    recent_bids = await _get_recent_bids(auction_id)
    await sio.emit("current_state", {
        **current,
        "recent_bids": recent_bids,
    }, to=sid)

    # ── 5. INCR watcher_count, broadcast ─────────────────────
    new_count = await redis.hincrby(_auction_key(auction_id), "watcher_count", 1)
    await sio.emit("watcher_update", {
        "auction_id": auction_id,
        "watcher_count": new_count,
    }, room=room)

    logger.info(
        "WS connected: sid=%s user=%s auction=%s watchers=%d",
        sid, user_id, auction_id, new_count,
    )
    return True


@sio.event
async def bid(sid, data):
    """Handle bid event from client.

    data: { "amount": float }

    On ACCEPTED:
      1. PUBLISH bid_update to Redis channel (fans out to all instances)
      2. Queue Celery task to INSERT bid into PostgreSQL
      3. Check anti-snipe, if triggered: PUBLISH timer_extended
    On REJECTED:
      4. Emit bid_rejected to submitting socket only
    """
    session = _sessions.get(sid)
    if not session:
        await sio.emit("bid_rejected", {
            "reason": "NOT_CONNECTED",
            "message": "Not connected to an auction room",
        }, to=sid)
        return

    auction_id = session["auction_id"]
    user_id = session["user_id"]

    amount = data.get("amount") if isinstance(data, dict) else None
    if not amount or not isinstance(amount, (int, float)) or amount <= 0:
        await sio.emit("bid_rejected", {
            "reason": "INVALID_AMOUNT",
            "message": "Amount must be a positive number",
        }, to=sid)
        return

    amount = float(amount)
    redis = await _get_redis()

    # ── Atomic Lua validation ────────────────────────────────
    from app.services.auction.service import place_bid, check_anti_snipe

    bid_status, reason = await place_bid(auction_id, user_id, amount, redis)

    if bid_status == "REJECTED":
        await sio.emit("bid_rejected", {
            "reason": reason,
            "message": f"Bid rejected: {reason}",
            "auction_id": auction_id,
            "amount": amount,
        }, to=sid)
        return

    # ── ACCEPTED ─────────────────────────────────────────────
    bid_count = int(await redis.hget(_auction_key(auction_id), "bid_count") or "0")

    bid_payload = {
        "auction_id": auction_id,
        "user_id": user_id,
        "amount": amount,
        "bid_count": bid_count,
        "currency": "JOD",
        "timestamp": time.time(),
    }

    # 1. PUBLISH to Redis channel (cross-instance fan-out)
    await redis.publish(_channel(auction_id), json.dumps({
        "event": "bid_update",
        "payload": bid_payload,
    }))

    # 2. Queue Celery task for PostgreSQL persistence
    try:
        from app.tasks.auction import handle_bid_persistence
        handle_bid_persistence.delay(auction_id, user_id, amount, "JOD")
    except Exception:
        # Celery unavailable — log but don't fail the real-time path
        logger.warning("Failed to queue bid persistence for auction=%s", auction_id)

    # 3. Anti-snipe check
    extended = await check_anti_snipe(auction_id, redis)
    if extended:
        ttl = await redis.ttl(_auction_key(auction_id))
        ext_count = int(await redis.hget(
            _auction_key(auction_id), "extension_count",
        ) or "0")

        timer_payload = {
            "auction_id": auction_id,
            "new_ttl": ttl,
            "extension_count": ext_count,
            "extension_seconds": settings.ANTI_SNIPE_EXTENSION_SECONDS,
        }
        await redis.publish(_channel(auction_id), json.dumps({
            "event": "timer_extended",
            "payload": timer_payload,
        }))


@sio.event
async def disconnect(sid):
    """Handle WebSocket disconnection.

    DECR watcher_count, broadcast watcher_update, clean up session.
    """
    session = _sessions.pop(sid, None)
    if not session:
        return

    auction_id = session["auction_id"]
    redis = await _get_redis()

    # DECR watcher_count (floor at 0)
    new_count = await redis.hincrby(_auction_key(auction_id), "watcher_count", -1)
    if new_count < 0:
        await redis.hset(_auction_key(auction_id), mapping={"watcher_count": "0"})
        new_count = 0

    room = _room(auction_id)
    await sio.emit("watcher_update", {
        "auction_id": auction_id,
        "watcher_count": new_count,
    }, room=room)

    sio.leave_room(sid, room)

    # Clean up Pub/Sub task if room is empty
    room_sids = sio.manager.get_participants("/", room)
    # get_participants returns a set or iterator; check if empty
    try:
        has_members = bool(next(iter(room_sids), None))
    except (StopIteration, TypeError):
        has_members = False

    if not has_members and room in _pubsub_tasks:
        task = _pubsub_tasks.pop(room)
        task.cancel()

    logger.info(
        "WS disconnected: sid=%s user=%s auction=%s watchers=%d",
        sid, session["user_id"], auction_id, new_count,
    )
