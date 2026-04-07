"""
Escrow service — SDD §3.3.

FSM transition logic lives in fsm.py; this module re-exports it
and provides CRUD helpers (create, get, get_by_auction).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.escrow.fsm import (  # noqa: F401 — re-export
    InvalidTransitionError,
    NoWaitLockError,
    transition_escrow,
)
from app.services.escrow.models import Escrow, EscrowState


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
    """Create an escrow after auction ends with a winner."""
    escrow = Escrow(
        auction_id=auction_id,
        winner_id=winner_id,
        seller_id=seller_id,
        amount=amount,
        currency=currency,
        state=EscrowState.INITIATED,
    )
    db.add(escrow)
    await db.commit()
    await db.refresh(escrow)
    return escrow
