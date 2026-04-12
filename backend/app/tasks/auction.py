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
    name="app.tasks.auction.schedule_auction",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def schedule_auction(self, listing_id: str):
    """Create an Auction row for a published listing and initialize if starts_at has arrived.

    Called from listing.service.publish_listing when a listing is auto-approved.
    """
    asyncio.run(_run_schedule_auction(listing_id))


async def _run_schedule_auction(listing_id: str):
    from datetime import datetime, timezone
    from uuid import uuid4

    from app.core.database import async_session_factory
    from app.core.redis import get_redis_client
    from app.services.auction.models import Auction, AuctionStatus
    from app.services.auction.service import initialize_auction
    from app.services.listing.models import Listing

    async with async_session_factory() as db:
        listing = await db.get(Listing, listing_id)
        if not listing:
            logger.error("schedule_auction: listing %s not found", listing_id)
            return

        # Idempotency: check if auction already exists for this listing
        from sqlalchemy import select
        existing = await db.execute(
            select(Auction).where(Auction.listing_id == listing_id)
        )
        if existing.scalar_one_or_none():
            logger.info("schedule_auction: auction already exists for listing %s", listing_id)
            return

        now = datetime.now(timezone.utc)
        starts_at = listing.starts_at
        ends_at = listing.ends_at

        # If starts_at is not set or in the past, start now
        if not starts_at or starts_at <= now:
            starts_at = now

        auction = Auction(
            id=str(uuid4()),
            listing_id=listing_id,
            status=AuctionStatus.SCHEDULED.value,
            starts_at=starts_at,
            ends_at=ends_at,
            current_price=float(listing.starting_price),
            min_increment=float(listing.min_increment),
            bid_count=0,
            extension_count=0,
        )
        db.add(auction)
        await db.commit()
        await db.refresh(auction)

        logger.info(
            "schedule_auction: created auction %s for listing %s (starts_at=%s)",
            auction.id, listing_id, starts_at,
        )

        # If start time is now or past, immediately initialize in Redis
        if starts_at <= now:
            redis = await get_redis_client()
            try:
                from uuid import UUID
                result = await initialize_auction(
                    auction_id=UUID(auction.id),
                    listing_id=UUID(listing_id),
                    db=db,
                    redis=redis,
                )
                logger.info("schedule_auction: immediate init result=%s", result.get("status"))
            finally:
                await redis.aclose()


@celery_app.task(
    name="app.tasks.auction.finalize_buy_now",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def finalize_buy_now(self, auction_id: str, buyer_id: str, final_price: int):
    """Finalize a Buy It Now purchase: update DB, create escrow, notify, cleanup Redis."""
    asyncio.run(_run_finalize_buy_now(auction_id, buyer_id, final_price))


async def _run_finalize_buy_now(auction_id: str, buyer_id: str, final_price: int):
    from datetime import datetime, timezone
    from app.core.database import async_session_factory
    from app.core.redis import get_redis_client
    from app.services.auction.models import Auction, AuctionStatus
    from app.services.auction.service import _cleanup_redis_keys
    from app.services.listing.models import Listing

    redis = await get_redis_client()
    try:
        async with async_session_factory() as db:
            auction = await db.get(Auction, auction_id)
            if not auction:
                logger.error("finalize_buy_now: auction %s not found", auction_id)
                return

            # Idempotency: skip if already ended
            if auction.status == AuctionStatus.ENDED.value:
                logger.info("finalize_buy_now: auction %s already ended", auction_id)
                return

            now = datetime.now(timezone.utc)
            seller_id = await redis.get(f"auction:{auction_id}:seller")
            bid_count_str = await redis.get(f"auction:{auction_id}:bid_count")
            bid_count = int(bid_count_str) if bid_count_str else 0

            # Update auction
            auction.status = AuctionStatus.ENDED.value
            auction.current_price = final_price
            auction.final_price = final_price
            auction.bid_count = bid_count
            auction.winner_id = buyer_id

            # Update listing
            listing = await db.get(Listing, auction.listing_id)
            if listing:
                listing.status = "ended"
                listing.ended_at = now
                listing.current_price = final_price

            # Create escrow
            if seller_id:
                try:
                    from app.services.escrow.service import create_escrow
                    amount_jod = round(final_price / 100, 2)
                    await create_escrow(
                        auction_id=auction_id,
                        winner_id=buyer_id,
                        seller_id=seller_id,
                        amount=amount_jod,
                        currency="JOD",
                        db=db,
                    )
                    logger.info(
                        "BIN escrow created: auction=%s buyer=%s amount=%d",
                        auction_id, buyer_id, final_price,
                    )
                except Exception:
                    logger.exception("Failed to create BIN escrow for auction=%s", auction_id)

            await db.commit()

            # Notifications
            try:
                from app.tasks.notification import send_notification
                price_jod = round(final_price / 100, 2)
                send_notification.delay(
                    event="buy_now_winner",
                    auction_id=auction_id,
                    user_id=buyer_id,
                    data={"final_price": price_jod},
                )
                if seller_id:
                    send_notification.delay(
                        event="buy_now_sold",
                        auction_id=auction_id,
                        user_id=seller_id,
                        data={"final_price": price_jod, "buyer_id": buyer_id},
                    )
            except Exception:
                logger.warning("Failed to queue BIN notifications for auction=%s", auction_id)

            # Sync listing to Meilisearch
            if listing:
                try:
                    from app.tasks.listing import sync_listing_to_meilisearch
                    sync_listing_to_meilisearch.delay(str(listing.id), action="index")
                except Exception:
                    pass

            # Cleanup Redis keys
            await _cleanup_redis_keys(auction_id, redis)
    finally:
        await redis.aclose()


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
