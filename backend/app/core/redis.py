"""
Async Redis connection pool.

Provides a shared pool for:
- Auction state (individual keys + Pub/Sub)
- OTP storage
- JWT blacklist
- Rate limiting
- Notification deduplication

Also provides a keyspace expiry listener that watches for auction
root key expirations (notify-keyspace-events Ex) and dispatches
handle_auction_expiry Celery tasks.
"""

from __future__ import annotations

import asyncio
import logging
import re

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

pool = ConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=settings.REDIS_MAX_CONNECTIONS,
    decode_responses=True,
)

# Background task handle for keyspace listener
_keyspace_task: asyncio.Task | None = None


def get_redis() -> Redis:
    """FastAPI dependency — returns a Redis client bound to the shared pool."""
    return Redis(connection_pool=pool)


async def get_redis_client() -> Redis:
    """Standalone Redis client for Celery tasks (not a FastAPI dependency)."""
    return Redis(connection_pool=pool)


# ── Keyspace expiry listener ───────────────────────────────────

# Pattern: matches "auction:<uuid>" but NOT "auction:<uuid>:suffix"
_AUCTION_ROOT_RE = re.compile(
    r"^auction:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


async def _keyspace_listener() -> None:
    """Subscribe to __keyevent@0__:expired and dispatch auction
    expiry tasks when an auction root key expires.

    Requires Redis config: notify-keyspace-events Ex
    """
    redis = Redis(connection_pool=pool)
    pubsub = redis.pubsub()

    try:
        # Subscribe to expiry events on DB 0
        await pubsub.subscribe("__keyevent@0__:expired")
        logger.info("Keyspace expiry listener started")

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            expired_key = message.get("data", "")
            if not _AUCTION_ROOT_RE.match(expired_key):
                continue

            # Extract auction_id from "auction:<uuid>"
            auction_id = expired_key.split(":", 1)[1]
            logger.info("Keyspace expiry detected for auction=%s", auction_id)

            try:
                from app.tasks.auction import handle_auction_expiry
                handle_auction_expiry.delay(auction_id)
            except Exception:
                logger.exception(
                    "Failed to dispatch handle_auction_expiry for %s", auction_id,
                )

    except asyncio.CancelledError:
        logger.info("Keyspace expiry listener cancelled")
    except Exception:
        logger.exception("Keyspace expiry listener error")
    finally:
        try:
            await pubsub.unsubscribe("__keyevent@0__:expired")
            await pubsub.aclose()
        except Exception:
            pass


async def start_keyspace_listener() -> None:
    """Start the keyspace expiry listener as a background task.
    Call once at application startup."""
    global _keyspace_task
    if _keyspace_task is None or _keyspace_task.done():
        _keyspace_task = asyncio.create_task(_keyspace_listener())
        logger.info("Keyspace listener background task created")


async def stop_keyspace_listener() -> None:
    """Cancel the listener task. Call at application shutdown."""
    global _keyspace_task
    if _keyspace_task and not _keyspace_task.done():
        _keyspace_task.cancel()
        try:
            await _keyspace_task
        except asyncio.CancelledError:
            pass
    _keyspace_task = None


# ── Shutdown ───────────────────────────────────────────────────

async def close_redis() -> None:
    """Call on application shutdown."""
    await stop_keyspace_listener()
    await pool.aclose()
