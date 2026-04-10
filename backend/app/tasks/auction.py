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
def handle_bid_persistence(self, auction_id: str, user_id: str, amount: int, currency: str):
    """Persist an accepted bid to PostgreSQL (called from REST endpoint)."""
    asyncio.run(_run_bid_persistence(auction_id, user_id, amount, currency))


async def _run_bid_persistence(auction_id: str, user_id: str, amount: int, currency: str):
    from app.core.database import async_session_factory
    from app.services.auction.service import persist_bid

    async with async_session_factory() as db:
        await persist_bid(auction_id, user_id, amount, currency, db)


@celery_app.task(
    name="app.tasks.auction.insert_bid_to_db",
    bind=True,
    max_retries=5,
    default_retry_delay=2,
)
def insert_bid_to_db(self, auction_id: str, user_id: str, amount: int, currency: str):
    """Persist an accepted bid to PostgreSQL and update auction/listing tables.

    Called from WebSocket place_bid handler. Updates:
      - Inserts Bid row
      - Updates Auction.current_price + bid_count
      - Updates Listing.current_price
    """
    asyncio.run(_run_insert_bid(auction_id, user_id, amount, currency))


async def _run_insert_bid(auction_id: str, user_id: str, amount: int, currency: str):
    from app.core.database import async_session_factory
    from app.services.auction.service import persist_bid
    from app.services.auction.models import Auction
    from app.services.listing.models import Listing

    async with async_session_factory() as db:
        bid = await persist_bid(auction_id, user_id, amount, currency, db)

        # Update auction current_price + bid_count
        auction = await db.get(Auction, auction_id)
        if auction:
            auction.current_price = amount
            auction.bid_count = (auction.bid_count or 0) + 1

            # Update listing current_price + bid_count
            listing = await db.get(Listing, auction.listing_id)
            if listing:
                listing.current_price = amount
                listing.bid_count = auction.bid_count

            await db.commit()

            # Sync to Meilisearch (price + bid_count changed)
            if listing:
                try:
                    from app.tasks.listing import sync_listing_to_meilisearch
                    sync_listing_to_meilisearch.delay(str(listing.id), action="index")
                except Exception:
                    pass

        return bid


@celery_app.task(
    name="app.tasks.auction.check_stale_auctions",
    bind=True,
    max_retries=1,
)
def check_stale_auctions(self):
    """Beat task (every 5 min): recover auctions whose Redis key expired
    but handle_auction_expiry was missed."""
    asyncio.run(_run_stale_check())


async def _run_stale_check():
    from app.core.database import async_session_factory
    from app.core.redis import get_redis_client
    from app.services.auction.lifecycle import check_stale_auctions_async

    redis = await get_redis_client()
    try:
        async with async_session_factory() as db:
            recovered = await check_stale_auctions_async(redis, db)
            if recovered:
                logger.info("Stale auction failsafe recovered %d auctions", recovered)
    finally:
        await redis.aclose()
