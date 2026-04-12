"""
Escrow service — SDD §3.3.

FSM transition logic lives in fsm.py; this module re-exports it
and provides CRUD helpers (create, get, get_by_auction).

Commission tiers (BRD §4.2):
  Pro sellers:  5% platform fee
  Free sellers: 8% platform fee

Zakat (BRD §4.5):
  Charity auctions with zakat-eligible NGO: 2.5% of sale price
  deducted separately from commission, receipt issued to buyer.
"""

import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.escrow.fsm import (  # noqa: F401 — re-export
    InvalidTransitionError,
    EscrowLockError,
    transition_escrow,
)
from app.services.escrow.models import Escrow, EscrowState, NgoPartner, ZakatReceipt

logger = logging.getLogger(__name__)

# Commission rates by seller tier
COMMISSION_RATE_PRO = 0.05    # 5% for Pro sellers
COMMISSION_RATE_FREE = 0.08   # 8% for free-tier sellers

# Zakat rate for charity auctions
ZAKAT_RATE = 0.025  # 2.5%


def calculate_seller_amount(
    amount: float,
    is_pro_seller: bool,
    zakat_amount: float = 0.0,
) -> float:
    """Calculate the seller's payout after platform commission and zakat.

    Returns amount in the same currency unit as input.
    """
    rate = COMMISSION_RATE_PRO if is_pro_seller else COMMISSION_RATE_FREE
    return round(amount * (1 - rate) - zakat_amount, 3)


def calculate_zakat(amount: float) -> float:
    """Calculate 2.5% zakat on charity auction proceeds."""
    return round(amount * ZAKAT_RATE, 3)


async def get_escrow(escrow_id: str, db: AsyncSession) -> Escrow | None:
    return await db.get(Escrow, escrow_id)


async def get_escrow_by_auction(auction_id: str, db: AsyncSession) -> Escrow | None:
    result = await db.execute(
        select(Escrow).where(Escrow.auction_id == auction_id)
    )
    return result.scalar_one_or_none()


async def create_escrow(
    auction_id: str,
    winner_id: str,
    seller_id: str,
    amount: float,
    currency: str,
    db: AsyncSession,
) -> Escrow:
    """Create an escrow after auction ends with a winner.

    Automatically calculates:
    - seller_amount based on seller's Pro status (5% or 8% commission)
    - zakat (2.5%) for charity auctions with zakat-eligible NGOs
    """
    from app.services.auth.models import User
    from app.services.auction.models import Auction
    from app.services.listing.models import Listing

    # Look up seller to determine commission tier
    seller = await db.get(User, seller_id)
    is_pro = seller.is_pro_seller if seller else False

    # Check if this is a charity auction with zakat
    zakat_amount = 0.0
    ngo_id = None
    is_charity = False

    auction = await db.get(Auction, auction_id)
    if auction:
        listing = await db.get(Listing, auction.listing_id)
        if listing and listing.is_charity and listing.ngo_id:
            is_charity = True
            ngo_id = listing.ngo_id
            # Check if NGO is zakat-eligible
            ngo = await db.get(NgoPartner, ngo_id)
            if ngo and ngo.is_zakat_eligible:
                zakat_amount = calculate_zakat(amount)

    seller_amount = calculate_seller_amount(amount, is_pro, zakat_amount)

    rate_pct = COMMISSION_RATE_PRO * 100 if is_pro else COMMISSION_RATE_FREE * 100
    logger.info(
        "Escrow commission: auction=%s amount=%.3f rate=%.0f%% zakat=%.3f seller_amount=%.3f pro=%s charity=%s",
        auction_id, amount, rate_pct, zakat_amount, seller_amount, is_pro, is_charity,
    )

    escrow = Escrow(
        auction_id=auction_id,
        winner_id=winner_id,
        seller_id=seller_id,
        amount=amount,
        seller_amount=seller_amount,
        currency=currency,
        state=EscrowState.PAYMENT_PENDING,
    )
    db.add(escrow)
    await db.commit()
    await db.refresh(escrow)

    # Issue zakat receipt if applicable
    if zakat_amount > 0 and ngo_id:
        zakat_cents = int(round(zakat_amount * 100))
        receipt_number = f"ZKT-{str(escrow.id)[:8].upper()}-{uuid4().hex[:6].upper()}"
        receipt = ZakatReceipt(
            escrow_id=escrow.id,
            ngo_id=ngo_id,
            buyer_id=winner_id,
            amount=zakat_cents,
            receipt_number=receipt_number,
        )
        db.add(receipt)
        await db.commit()
        logger.info(
            "Zakat receipt issued: %s escrow=%s amount=%d ngo=%d",
            receipt_number, escrow.id, zakat_cents, ngo_id,
        )

    return escrow
