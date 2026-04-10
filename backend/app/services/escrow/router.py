"""Escrow endpoints — SDD §5.5."""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.types import UUIDPath
from app.services.auth.dependencies import get_current_user
from app.services.auth.models import User
from app.services.escrow import schemas, service
from app.services.escrow.dependencies import get_escrow_as_participant, get_escrow_or_404
from app.services.escrow.models import ActorType, Escrow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/escrow", tags=["escrow"])


@router.get("/{escrow_id}", response_model=schemas.EscrowOut)
async def get_escrow(escrow: Escrow = Depends(get_escrow_as_participant)):
    return escrow


@router.post("/{escrow_id}/pay", response_model=schemas.InitiatePaymentResponse)
async def initiate_payment(
    escrow: Escrow = Depends(get_escrow_as_participant),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Buyer initiates payment — creates Checkout.com Payment Link.

    Only the winner (buyer) can call this, and only when state is payment_pending.
    Returns a hosted payment page URL the client opens in a browser/webview.
    """
    if user.id != escrow.winner_id:
        raise HTTPException(status_code=403, detail="Only buyer can initiate payment")

    current = escrow.state
    if hasattr(current, "value"):
        current = current.value

    if current != "payment_pending":
        raise HTTPException(
            status_code=400,
            detail=f"Payment already initiated (state: {current})",
        )

    # Return existing payment link if already created (idempotent)
    if escrow.payment_link:
        return schemas.InitiatePaymentResponse(
            escrow_id=escrow.id,
            payment_link=escrow.payment_link,
        )

    if not settings.CHECKOUT_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail="Payment service not configured",
        )

    # JOD uses 3 decimal places: 1 JOD = 1000 fils
    amount_minor = int(round(float(escrow.amount) * 1000))

    # Create Checkout.com Payment Link via API
    payload = {
        "amount": amount_minor,
        "currency": escrow.currency or "JOD",
        "reference": str(escrow.id),
        "description": f"MZADAK Auction Payment — {escrow.auction_id}",
        "return_url": settings.CHECKOUT_SUCCESS_URL,
        "processing_channel_id": "pc_mzadak",
        "billing": {
            "address": {"country": "JO"},
        },
        "3ds": {"enabled": True},
        "metadata": {
            "escrow_id": str(escrow.id),
            "auction_id": str(escrow.auction_id),
            "buyer_id": str(escrow.winner_id),
        },
    }

    headers = {
        "Authorization": f"Bearer {settings.CHECKOUT_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.checkout.com/payment-links",
                json=payload,
                headers=headers,
            )

        if resp.status_code not in (200, 201):
            logger.error(
                "Checkout.com payment link creation failed %d: %s",
                resp.status_code, resp.text[:300],
            )
            raise HTTPException(
                status_code=502,
                detail="Payment provider error — please try again",
            )

        result = resp.json()
        payment_link = result.get("_links", {}).get("redirect", {}).get("href", "")
        payment_id = result.get("id", "")
        expires_at = result.get("expires_on")

        # Store on escrow record
        escrow.payment_link = payment_link
        escrow.payment_intent_id = payment_id
        await db.commit()

        logger.info(
            "Payment link created: escrow=%s payment_id=%s",
            escrow.id, payment_id,
        )

        return schemas.InitiatePaymentResponse(
            escrow_id=escrow.id,
            payment_link=payment_link,
            expires_at=expires_at,
        )

    except httpx.HTTPError as exc:
        logger.error("Checkout.com request failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Payment provider unavailable — please try again",
        )


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
