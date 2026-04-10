"""Escrow endpoints — SDD §5.5."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.types import UUIDPath
from app.services.auth.dependencies import get_current_user
from app.services.auth.models import User
from app.services.escrow import schemas, service
from app.services.escrow.dependencies import get_escrow_as_participant, get_escrow_or_404
from app.services.escrow.models import ActorType, Escrow

router = APIRouter(prefix="/escrow", tags=["escrow"])


@router.get("/{escrow_id}", response_model=schemas.EscrowOut)
async def get_escrow(escrow: Escrow = Depends(get_escrow_as_participant)):
    return escrow


@router.post("/{escrow_id}/confirm-receipt", response_model=schemas.EscrowOut)
async def confirm_receipt(
    escrow: Escrow = Depends(get_escrow_as_participant),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Buyer confirms item received — transitions to RELEASED."""
    if user.id != escrow.winner_id:
        raise HTTPException(status_code=403, detail="Only buyer can confirm receipt")
    return await service.transition_escrow(
        escrow.id, "released", user.id, ActorType.BUYER.value,
        "buyer.confirm_receipt", {}, db,
    )


@router.post("/{escrow_id}/tracking", response_model=schemas.EscrowOut)
async def upload_tracking(
    body: schemas.UploadTrackingRequest,
    escrow: Escrow = Depends(get_escrow_as_participant),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Seller uploads tracking info."""
    if user.id != escrow.seller_id:
        raise HTTPException(status_code=403, detail="Only seller can upload tracking")
    escrow.tracking_number = body.tracking_number
    escrow.carrier = body.carrier
    return await service.transition_escrow(
        escrow.id, "in_transit", user.id, ActorType.SELLER.value,
        "seller.upload_tracking",
        {"tracking_number": body.tracking_number, "carrier": body.carrier},
        db,
    )


@router.post("/disputes", response_model=schemas.EscrowOut, status_code=201)
async def file_dispute(
    body: schemas.FileDisputeRequest,
    escrow_id: UUIDPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Buyer files a dispute."""
    escrow = await service.get_escrow(escrow_id, db)
    if not escrow:
        raise HTTPException(status_code=404)
    return await service.transition_escrow(
        escrow.id, "disputed", user.id, ActorType.BUYER.value,
        "buyer.file_dispute",
        {"reason": body.reason, "evidence": body.evidence_s3_keys},
        db,
    )
