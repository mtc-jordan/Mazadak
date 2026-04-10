"""
Auction lifecycle async logic — SDD §3.2.1.

Separated from Celery task wrappers so the async functions can be
tested without importing the Celery app (which requires the celery
package).

Delegates to service.py for actual Redis/DB operations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

logger = logging.getLogger(__name__)


async def activate_scheduled_auctions_async(redis, db) -> int:
    """Find SCHEDULED auctions whose starts_at has arrived, initialize
    their Redis state, and mark them ACTIVE in PostgreSQL.

    Returns the number of auctions activated.
    """
    from sqlalchemy import select

    from app.services.auction.models import Auction, AuctionStatus
    from app.services.auction.service import initialize_auction

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
            outcome = await initialize_auction(
                auction_id=UUID(auction.id),
                listing_id=UUID(auction.listing_id),
                db=db,
                redis=redis,
            )
            if outcome.get("status") == "initialized":
                activated += 1
        except Exception:
            logger.exception("Failed to activate auction=%s", auction.id)

    return activated


async def handle_auction_expiry_async(
    auction_id: str,
    redis,
    db,
) -> dict:
    """Handle auction end.  Delegates to service.handle_auction_expiry."""
    from app.services.auction.service import handle_auction_expiry

    return await handle_auction_expiry(auction_id, redis, db)


async def check_stale_auctions_async(redis, db) -> int:
    """Failsafe for missed expirations.  Delegates to service."""
    from app.services.auction.service import check_stale_auctions

    return await check_stale_auctions(redis, db)
