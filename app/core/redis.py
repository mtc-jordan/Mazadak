"""
Async Redis connection pool.

Provides a shared pool for:
- Auction state (Hash + Pub/Sub)
- OTP storage
- JWT blacklist
- Rate limiting
- Notification deduplication
"""

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

pool = ConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=settings.REDIS_MAX_CONNECTIONS,
    decode_responses=True,
)


def get_redis() -> Redis:
    """FastAPI dependency — returns a Redis client bound to the shared pool."""
    return Redis(connection_pool=pool)


async def get_redis_client() -> Redis:
    """Standalone Redis client for Celery tasks (not a FastAPI dependency)."""
    return Redis(connection_pool=pool)


async def close_redis() -> None:
    """Call on application shutdown."""
    await pool.aclose()
