"""
Auction lifecycle async logic — SDD §3.2.1.

Separated from Celery task wrappers so the async functions can be
tested without importing the Celery app (which requires the celery
package).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def activate_scheduled_auctions_async(redis, db) -> int:
    """Find SCHEDULED auctions whose starts_at has arrived, initialize
    their Redis state, and mark them ACTIVE in PostgreSQL.

    Returns the number of auctions activated.
    """
    from sqlalchemy import select

    from app.services.auction.models import Auction, AuctionStatus
    from app.services.auction.service import initialize_auction_in_redis
    from app.services.listing.models import Listing

    now = datetime.now(timezone.utc).isoformat()

    result = await db.execute(
        select(Auction).where(
            Auction.status == AuctionStatus.SCHEDULED.value,
            Auction.starts_at <= now,
        )
    )
    auctions = result.scalars().all()

    if not auctions:
        return 0

    logger.info("Activating %d scheduled auctions", len(auctions))
    activated = 0

    for auction in auctions:
        try:
            ends_at = datetime.fromisoformat(auction.ends_at)
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=timezone.utc)
            ttl = int((ends_at - datetime.now(timezone.utc)).total_seconds())

            if ttl <= 0:
                auction.status = AuctionStatus.ENDED.value
                logger.warning(
                    "Auction %s already past ends_at, marking ENDED",
                    auction.id,
                )
                continue

            listing = await db.get(Listing, auction.listing_id)
            seller_id = listing.seller_id if listing else ""

            await initialize_auction_in_redis(auction, seller_id, redis, ttl)

            auction.status = AuctionStatus.ACTIVE.value
            auction.redis_synced_at = datetime.now(timezone.utc).isoformat()
            activated += 1

            logger.info(
                "Activated auction=%s TTL=%ds seller=%s",
                auction.id, ttl, seller_id,
            )
        except Exception:
            logger.exception("Failed to activate auction=%s", auction.id)

    await db.commit()
    return activated


async def handle_auction_expiry_async(
    auction_id: str,
    redis,
    db,
) -> None:
    """Handle auction end: read Redis state, sync to PostgreSQL,
    create escrow if there was a winner.

    Can be called from Celery task (keyspace notification) or directly.
    """
    from app.services.auction.models import Auction, AuctionStatus
    from app.services.listing.models import Listing

    key = f"auction:{auction_id}"
    state = await redis.hgetall(key)

    auction = await db.get(Auction, auction_id)
    if not auction:
        logger.error("Auction %s not found in PostgreSQL", auction_id)
        return

    if auction.status == AuctionStatus.ENDED.value:
        logger.info("Auction %s already ended, skipping", auction_id)
        return

    if state:
        auction.status = AuctionStatus.ENDED.value
        auction.current_price = float(state.get("current_price", "0"))
        auction.bid_count = int(state.get("bid_count", "0"))
        auction.extension_count = int(state.get("extension_count", "0"))
        auction.final_price = float(state.get("current_price", "0"))
        winner_id = state.get("last_bidder")
        auction.winner_id = winner_id if winner_id else None
        await redis.delete(key)
    else:
        auction.status = AuctionStatus.ENDED.value

    await db.commit()
    await db.refresh(auction)

    if auction.winner_id:
        try:
            listing = await db.get(Listing, auction.listing_id)
            seller_id = listing.seller_id if listing else ""

            from app.services.escrow.service import create_escrow
            escrow = await create_escrow(
                auction_id=auction_id,
                winner_id=auction.winner_id,
                seller_id=seller_id,
                amount=float(auction.final_price or auction.current_price),
                currency="JOD",
                db=db,
            )
            logger.info(
                "Escrow %s created for auction=%s winner=%s amount=%.3f",
                escrow.id, auction_id, auction.winner_id, escrow.amount,
            )
        except Exception:
            logger.exception(
                "Failed to create escrow for auction=%s", auction_id,
            )
    else:
        logger.info("Auction %s ended with no bids", auction_id)
