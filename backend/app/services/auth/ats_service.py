"""
ATS (Auction Trust Score) calculation and updates — SDD §3.5.

Score formula (0–1000):
  identity_score    × 0.15  → max 150  (binary: KYC verified or not)
  completion_rate   × 0.25  → max 250  (completed_sales / total_sales × 250)
  speed_score       × 0.20  → max 200  (avg days_to_ship vs target 2 days)
  rating_score      × 0.20  → max 200  (avg_buyer_rating / 5 × 200)
  quality_score     × 0.10  → max 100  (listing approval rate × 100)
  dispute_score     × 0.10  → max 100  (100 - dispute_rate × 100, min 0)

Commission tiers:
  >= 750 (Elite):  4%   (-1% discount)
  600–749 (Gold):  5%   (standard)
  400–599 (Silver): 5.5% (+0.5%)
  < 400 (Bronze):  6%   (+1%)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth.models import User
from app.services.escrow.models import Dispute, Escrow, EscrowEvent, Rating
from app.services.listing.models import Listing

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Main recalculation
# ═══════════════════════════════════════════════════════════════

async def recalculate_ats(
    user_id: str,
    trigger: str,
    db: AsyncSession,
) -> int:
    """Recalculate all ATS sub-scores for a user and persist.

    Args:
        user_id: UUID of the user to recalculate.
        trigger: Reason for recalculation (e.g. 'escrow_released', 'kyc_approved').
        db: Async database session.

    Returns:
        New total ATS score (0–1000).
    """
    user = await db.get(User, user_id)
    if not user:
        logger.warning("ATS recalc: user %s not found (trigger=%s)", user_id, trigger)
        return 0

    now = datetime.now(timezone.utc)
    d180 = now - timedelta(days=180)
    d90 = now - timedelta(days=90)

    # ── 1. Identity score (binary: KYC verified → 150, else 0) ──
    kyc = user.kyc_status.value if hasattr(user.kyc_status, "value") else user.kyc_status
    identity = 150 if kyc == "verified" else 0

    # ── 2. Completion rate (seller, last 180 days) ──────────────
    completion = await _calc_completion(user_id, d180, db)

    # ── 3. Speed score (avg days to ship, last 90 days) ─────────
    speed = await _calc_speed(user_id, d90, db)

    # ── 4. Rating score (avg rating / 5 × 200, last 180 days) ──
    rating = await _calc_rating(user_id, d180, db)

    # ── 5. Quality score (listing approval rate) ────────────────
    quality = await _calc_quality(user_id, db)

    # ── 6. Dispute score (100 - dispute_rate × 500, min 0) ──────
    dispute = await _calc_dispute(user_id, d180, db)

    # ── Total (clamped 0–1000) ──────────────────────────────────
    total = int(identity + completion + speed + rating + quality + dispute)
    total = max(0, min(1000, total))

    # ── Commission tier ─────────────────────────────────────────
    commission = _commission_for_score(total)

    # ── Persist ─────────────────────────────────────────────────
    await db.execute(
        update(User).where(User.id == user_id).values(
            ats_score=total,
            ats_identity_score=identity,
            ats_completion_score=int(completion),
            ats_speed_score=speed,
            ats_rating_score=rating,
            ats_quality_score=quality,
            ats_dispute_score=dispute,
            commission_rate=commission,
        )
    )
    await db.commit()

    logger.info(
        "ats_recalculated user=%s total=%d trigger=%s "
        "identity=%d completion=%d speed=%d rating=%d quality=%d dispute=%d commission=%s",
        user_id, total, trigger,
        identity, int(completion), speed, rating, quality, dispute, commission,
    )
    return total


# ═══════════════════════════════════════════════════════════════
# Sub-score calculators
# ═══════════════════════════════════════════════════════════════

async def _calc_completion(user_id: str, since: datetime, db: AsyncSession) -> float:
    """Completion rate: completed_sales / total_sales × 250.

    Default 200 for sellers with no sales history (benefit of the doubt).
    """
    result = await db.execute(
        select(
            func.count(Escrow.id).label("total"),
            func.count(
                case((Escrow.state == "released", Escrow.id))
            ).label("completed"),
        ).where(
            Escrow.seller_id == user_id,
            Escrow.created_at > since,
        )
    )
    stats = result.one()
    if stats.total == 0:
        return 200  # default for new sellers
    return stats.completed / stats.total * 250


async def _calc_speed(user_id: str, since: datetime, db: AsyncSession) -> int:
    """Speed score based on avg days to ship (target <= 2 days).

    Scoring brackets:
      <= 1 day  → 200
      <= 2 days → 180
      <= 3 days → 140
      <= 5 days → 80
      > 5 days  → max(0, 200 - avg_days * 30)
    Default 180 for new sellers.
    """
    avg_days = await db.scalar(
        select(
            func.avg(
                func.extract("epoch", EscrowEvent.created_at - Escrow.created_at) / 86400
            )
        )
        .select_from(Escrow)
        .join(EscrowEvent, EscrowEvent.escrow_id == Escrow.id)
        .where(
            Escrow.seller_id == user_id,
            EscrowEvent.to_state == "shipped",
            Escrow.created_at > since,
        )
    )

    if avg_days is None:
        return 180  # default for new sellers
    if avg_days <= 1:
        return 200
    if avg_days <= 2:
        return 180
    if avg_days <= 3:
        return 140
    if avg_days <= 5:
        return 80
    return max(0, int(200 - avg_days * 30))


async def _calc_rating(user_id: str, since: datetime, db: AsyncSession) -> int:
    """Rating score: avg(score) / 5 × 200. Default 4.0 for new users."""
    avg_rating = await db.scalar(
        select(func.avg(Rating.score)).where(
            Rating.ratee_id == user_id,
            Rating.created_at > since,
        )
    )
    return int((avg_rating or 4.0) / 5.0 * 200)


async def _calc_quality(user_id: str, db: AsyncSession) -> int:
    """Quality score: approval rate of last 30 listings × 100.

    Default 100 for sellers with no listings.
    """
    # Subquery: last 30 listings by this seller
    subq = (
        select(Listing.moderation_status)
        .where(Listing.seller_id == user_id)
        .order_by(Listing.created_at.desc())
        .limit(30)
        .subquery()
    )

    result = await db.execute(
        select(
            func.count().label("total"),
            func.count(
                case((subq.c.moderation_status == "approved", 1))
            ).label("approved"),
        ).select_from(subq)
    )
    stats = result.one()
    if stats.total == 0:
        return 100  # default for new sellers
    return int(stats.approved / stats.total * 100)


async def _calc_dispute(user_id: str, since: datetime, db: AsyncSession) -> int:
    """Dispute score: 100 - dispute_rate × 500 (2% dispute rate → 0 score).

    Default 100 for sellers with no escrows.
    """
    result = await db.execute(
        select(
            func.count(Escrow.id).label("total"),
            func.count(Dispute.id).label("disputes"),
        )
        .select_from(Escrow)
        .outerjoin(Dispute, Dispute.escrow_id == Escrow.id)
        .where(
            Escrow.seller_id == user_id,
            Escrow.created_at > since,
        )
    )
    stats = result.one()
    if stats.total == 0:
        return 100  # default
    dispute_rate = stats.disputes / stats.total
    return max(0, int(100 - dispute_rate * 500))


# ═══════════════════════════════════════════════════════════════
# Commission tier
# ═══════════════════════════════════════════════════════════════

def _commission_for_score(score: int) -> Decimal:
    """Map ATS total to commission rate."""
    if score >= 750:
        return Decimal("0.0400")  # Elite: 4%
    if score >= 600:
        return Decimal("0.0500")  # Gold: 5%
    if score >= 400:
        return Decimal("0.0550")  # Silver: 5.5%
    return Decimal("0.0600")      # Bronze: 6%


# ═══════════════════════════════════════════════════════════════
# Batch recalculation (for weekly beat task)
# ═══════════════════════════════════════════════════════════════

async def recalculate_all_sellers(db: AsyncSession, batch_size: int = 100) -> int:
    """Recalculate ATS for all active sellers in batches.

    Returns total number of sellers recalculated.
    """
    # Get all active sellers
    result = await db.execute(
        select(User.id).where(
            User.role.in_(["seller", "admin", "superadmin"]),
            User.status == "active",
        )
    )
    seller_ids = [row[0] for row in result.all()]

    count = 0
    for i in range(0, len(seller_ids), batch_size):
        batch = seller_ids[i : i + batch_size]
        for uid in batch:
            try:
                await recalculate_ats(uid, "weekly_recalc", db)
                count += 1
            except Exception as exc:
                logger.error("ATS batch recalc failed for %s: %s", uid, exc)

    logger.info("ATS weekly recalc completed: %d sellers processed", count)
    return count
