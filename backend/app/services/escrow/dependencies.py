"""Escrow dependencies — lookup, participant guards."""

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.auth.dependencies import get_current_user
from app.services.auth.models import User
from app.services.escrow.models import Escrow
from app.services.escrow.service import get_escrow


async def get_escrow_or_404(
    escrow_id: str,
    db: AsyncSession = Depends(get_db),
) -> Escrow:
    escrow = await get_escrow(escrow_id, db)
    if not escrow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ESCROW_NOT_FOUND", "message_en": "Escrow not found"},
        )
    return escrow


async def get_escrow_as_participant(
    escrow: Escrow = Depends(get_escrow_or_404),
    user: User = Depends(get_current_user),
) -> Escrow:
    """Ensure current user is buyer, seller, or mediator of this escrow."""
    if user.id not in (escrow.winner_id, escrow.seller_id, escrow.mediator_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "NOT_PARTICIPANT", "message_en": "Not a participant in this escrow"},
        )
    return escrow
