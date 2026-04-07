"""
Auction lifecycle Celery tasks — SDD §3.2.1.

Thin wrappers around app.services.auction.lifecycle async functions.
"""

import asyncio
import logging

from app.core.celery import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.auction.activate_scheduled_auctions",
    bind=True,
    max_retries=1,
)
def activate_scheduled_auctions(self):
    """Beat task (every 30s): activate auctions whose starts_at has arrived."""
    asyncio.run(_run_activate())


async def _run_activate():
    from app.core.database import async_session_factory
    from app.core.redis import get_redis_client
    from app.services.auction.lifecycle import activate_scheduled_auctions_async

    redis = await get_redis_client()
    try:
        async with async_session_factory() as db:
            await activate_scheduled_auctions_async(redis, db)
    finally:
        await redis.aclose()


@celery_app.task(
    name="app.tasks.auction.handle_auction_expiry",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def handle_auction_expiry(self, auction_id: str):
    """Keyspace notification handler: sync final state to PG + create escrow."""
    asyncio.run(_run_expiry(auction_id))


async def _run_expiry(auction_id: str):
    from app.core.database import async_session_factory
    from app.core.redis import get_redis_client
    from app.services.auction.lifecycle import handle_auction_expiry_async

    redis = await get_redis_client()
    try:
        async with async_session_factory() as db:
            await handle_auction_expiry_async(auction_id, redis, db)
    finally:
        await redis.aclose()


@celery_app.task(
    name="app.tasks.auction.handle_bid_persistence",
    bind=True,
    max_retries=5,
    default_retry_delay=2,
)
def handle_bid_persistence(self, auction_id: str, user_id: str, amount: float, currency: str):
    """Persist an accepted bid to PostgreSQL (called from WebSocket handler)."""
    asyncio.run(_run_bid_persistence(auction_id, user_id, amount, currency))


async def _run_bid_persistence(auction_id: str, user_id: str, amount: float, currency: str):
    from app.core.database import async_session_factory
    from app.services.auction.service import persist_bid

    async with async_session_factory() as db:
        await persist_bid(auction_id, user_id, amount, currency, db)
