"""Escrow endpoints — SDD §5.5."""

import logging
from datetime import datetime, timedelta, timezone
from hashlib import sha256 as sha256_hash
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.types import UUIDPath
from app.services.auth.dependencies import get_current_user
from app.services.auth.models import User
from app.services.escrow import schemas, service
from app.services.escrow.dependencies import get_escrow_as_participant, get_escrow_or_404
from app.services.escrow.models import ActorType, Dispute, DisputeEvidence, DisputeMessage, Escrow, Rating
from app.services.listing.models import Listing

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
    """Seller uploads tracking info → escrow goes to in_transit.

    Valid from `shipping_requested` (seller skipped Aramex label and is
    using their own carrier) or `label_generated` (Aramex label exists).
    """
    if user.id != escrow.seller_id:
        raise HTTPException(status_code=403, detail="Only seller can upload tracking")
    escrow.tracking_number = body.tracking_number
    escrow.carrier = body.carrier
    try:
        return await service.transition_escrow(
            escrow.id, "in_transit", user.id, ActorType.SELLER.value,
            "seller.upload_tracking",
            {"tracking_number": body.tracking_number, "carrier": body.carrier},
            db,
        )
    except service.InvalidTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_ESCROW_STATE",
                "message_en": str(exc),
                "message_ar": "حالة الضمان لا تسمح برفع رقم التتبع",
            },
        ) from exc


@router.post("/{escrow_id}/mark-delivered", response_model=schemas.EscrowOut)
async def mark_delivered(
    escrow: Escrow = Depends(get_escrow_as_participant),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Buyer marks the package as delivered → escrow enters inspection_period.

    Starts the 72h inspection window.  After 72h, deadlines.py auto-releases
    the funds; the buyer can also call confirm_receipt earlier to release
    immediately, or file a dispute.

    Valid from `label_generated`, `shipped`, `in_transit`, or `delivered`.
    """
    if user.id != escrow.winner_id:
        raise HTTPException(
            status_code=403, detail="Only buyer can mark the package delivered",
        )
    try:
        return await service.transition_escrow(
            escrow.id, "inspection_period", user.id, ActorType.BUYER.value,
            "buyer.mark_delivered", {}, db,
        )
    except service.InvalidTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_ESCROW_STATE",
                "message_en": str(exc),
                "message_ar": "حالة الضمان لا تسمح بتأكيد الاستلام",
            },
        ) from exc


# ── GET /:id/invoice — Generate invoice (FR-ESC-024) ──────────

@router.get("/{escrow_id}/invoice", response_model=schemas.InvoiceOut)
async def get_invoice(
    escrow: Escrow = Depends(get_escrow_as_participant),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an invoice for a completed escrow transaction.

    FR-ESC-024: Available to buyer/seller once escrow reaches a terminal state.
    """
    from app.services.auction.models import Auction

    state = escrow.state if isinstance(escrow.state, str) else escrow.state.value
    terminal = {"released", "resolved_released", "resolved_refunded", "resolved_split"}
    if state not in terminal:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "ESCROW_NOT_COMPLETE",
                "message_en": "Invoice is only available for completed transactions",
                "message_ar": "الفاتورة متاحة فقط للمعاملات المكتملة",
            },
        )

    # Fetch related auction and listing for item details
    result = await db.execute(
        select(Auction).where(Auction.id == escrow.auction_id)
    )
    auction = result.scalar_one_or_none()

    item_title = ""
    item_description = None
    if auction:
        listing_result = await db.execute(
            select(Listing).where(Listing.id == auction.listing_id)
        )
        listing = listing_result.scalar_one_or_none()
        if listing:
            item_title = listing.title_ar
            item_description = listing.description_ar

    amount = float(escrow.amount)
    fee_percent = settings.PLATFORM_FEE_PERCENT
    platform_fee = round(amount * fee_percent / 100, 3)

    # Check for zakat on this escrow
    from app.services.escrow.models import ZakatReceipt
    zakat_result = await db.execute(
        select(ZakatReceipt).where(ZakatReceipt.escrow_id == str(escrow.id))
    )
    zakat_receipt = zakat_result.scalar_one_or_none()
    zakat_amount = round(zakat_receipt.amount / 100, 3) if zakat_receipt else 0.0

    seller_payout = round(amount - platform_fee - zakat_amount, 3)

    # Invoice number: INV-{escrow_id_short}-{timestamp}
    esc_short = str(escrow.id)[:8].upper()
    issued_at = datetime.now(timezone.utc)
    invoice_number = f"INV-{esc_short}-{issued_at.strftime('%Y%m%d')}"

    line_items = [
        schemas.InvoiceLineItem(
            description_ar="قيمة المزاد",
            description_en="Auction sale amount",
            amount=amount,
        ),
        schemas.InvoiceLineItem(
            description_ar=f"عمولة المنصة ({fee_percent}%)",
            description_en=f"Platform fee ({fee_percent}%)",
            amount=-platform_fee,
        ),
    ]

    if zakat_amount > 0:
        line_items.append(schemas.InvoiceLineItem(
            description_ar="زكاة (2.5%)",
            description_en="Zakat (2.5%)",
            amount=-zakat_amount,
        ))

    return schemas.InvoiceOut(
        invoice_number=invoice_number,
        escrow_id=str(escrow.id),
        auction_id=str(escrow.auction_id),
        issued_at=issued_at.isoformat(),
        buyer_id=str(escrow.winner_id),
        seller_id=str(escrow.seller_id),
        item_title=item_title,
        item_description=item_description,
        subtotal=amount,
        platform_fee=platform_fee,
        platform_fee_percent=fee_percent,
        seller_payout=seller_payout,
        total=amount,
        currency=escrow.currency or "JOD",
        status=state,
        line_items=line_items,
    )


@router.post("/disputes", response_model=schemas.EscrowOut, status_code=201)
async def file_dispute(
    body: schemas.FileDisputeRequest,
    escrow_id: UUIDPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Buyer files a dispute. Sets 48h seller response deadline (FR-DISP-004)."""
    escrow = await service.get_escrow(escrow_id, db)
    if not escrow:
        raise HTTPException(status_code=404)

    if user.id != escrow.winner_id:
        raise HTTPException(status_code=403, detail="Only buyer can file a dispute")

    now = datetime.now(timezone.utc)

    # Create Dispute record with 48h seller response deadline
    dispute = Dispute(
        id=str(uuid4()),
        escrow_id=str(escrow.id),
        buyer_id=str(user.id),
        seller_id=str(escrow.seller_id),
        reason=body.reason[:30],
        reason_detail=body.reason,
        status="open",
        seller_response_deadline=now + timedelta(hours=48),
        buyer_evidence_count=len(body.evidence_s3_keys),
    )
    db.add(dispute)

    # Store buyer evidence
    for s3_key in body.evidence_s3_keys:
        evidence = DisputeEvidence(
            id=str(uuid4()),
            dispute_id=dispute.id,
            uploader_id=str(user.id),
            uploader_role="buyer",
            s3_key=s3_key,
            sha256_hash=sha256_hash(s3_key.encode()).hexdigest(),
        )
        db.add(evidence)

    return await service.transition_escrow(
        escrow.id, "disputed", user.id, ActorType.BUYER.value,
        "buyer.file_dispute",
        {"reason": body.reason, "dispute_id": dispute.id, "evidence_count": len(body.evidence_s3_keys)},
        db,
    )


# ── POST /disputes/:id/seller-respond — FR-DISP-004 ──────────

@router.post(
    "/disputes/{dispute_id}/seller-respond",
    response_model=schemas.DisputeOut,
)
async def seller_respond_to_dispute(
    dispute_id: str,
    body: schemas.SellerDisputeResponseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Seller responds to a dispute with evidence and proposed resolution.

    FR-DISP-004: Seller has 48h from dispute creation to respond.
    After response, dispute transitions to under_review for admin mediation.
    """
    result = await db.execute(
        select(Dispute).where(Dispute.id == dispute_id)
    )
    dispute = result.scalar_one_or_none()
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")

    if user.id != dispute.seller_id:
        raise HTTPException(status_code=403, detail="Only the seller can respond to this dispute")

    if dispute.seller_responded_at is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ALREADY_RESPONDED",
                "message_en": "Seller has already responded to this dispute",
                "message_ar": "تم الرد على النزاع مسبقاً",
            },
        )

    d_status = dispute.status if isinstance(dispute.status, str) else dispute.status.value
    if d_status not in ("open", "under_review"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DISPUTE_CLOSED",
                "message_en": "This dispute is no longer open for responses",
                "message_ar": "هذا النزاع لم يعد مفتوحاً للردود",
            },
        )

    # Check 48h deadline if set
    if dispute.seller_response_deadline:
        now = datetime.now(timezone.utc)
        if now > dispute.seller_response_deadline:
            raise HTTPException(
                status_code=410,
                detail={
                    "code": "RESPONSE_DEADLINE_PASSED",
                    "message_en": "The 48-hour response window has expired",
                    "message_ar": "انتهت فترة الـ 48 ساعة المتاحة للرد",
                },
            )

    now = datetime.now(timezone.utc)
    dispute.seller_response = body.response_text
    dispute.seller_responded_at = now
    dispute.seller_proposed_resolution = body.proposed_resolution
    dispute.status = "under_review"

    # Store seller evidence
    for s3_key in body.evidence_s3_keys:
        evidence = DisputeEvidence(
            id=str(uuid4()),
            dispute_id=dispute.id,
            uploader_id=user.id,
            uploader_role="seller",
            s3_key=s3_key,
            sha256_hash=sha256_hash(s3_key.encode()).hexdigest(),
        )
        db.add(evidence)
        dispute.seller_evidence_count += 1

    # Transition escrow to under_review
    escrow = await service.get_escrow(dispute.escrow_id, db)
    if escrow:
        current = escrow.state if isinstance(escrow.state, str) else escrow.state.value
        if current == "disputed":
            await service.transition_escrow(
                escrow.id, "under_review", user.id, ActorType.SELLER.value,
                "seller.dispute_response",
                {"response_length": len(body.response_text), "evidence_count": len(body.evidence_s3_keys)},
                db,
            )

    await db.commit()
    await db.refresh(dispute)
    return dispute


# ── GET /disputes/:id — Get dispute details ───────────────────

@router.get("/disputes/{dispute_id}", response_model=schemas.DisputeOut)
async def get_dispute(
    dispute_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get dispute details. Only buyer, seller, or admin can view."""
    result = await db.execute(
        select(Dispute).where(Dispute.id == dispute_id)
    )
    dispute = result.scalar_one_or_none()
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")

    role_val = user.role if isinstance(user.role, str) else user.role.value
    if user.id not in (dispute.buyer_id, dispute.seller_id) and role_val not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Not a participant in this dispute")

    return dispute


# ── Dispute Messages — FR-DISP-005 ──────────────────────────

@router.post(
    "/disputes/{dispute_id}/messages",
    response_model=schemas.DisputeMessageOut,
    status_code=201,
)
async def send_dispute_message(
    dispute_id: str,
    body: schemas.SendDisputeMessageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a message in the dispute thread.

    Only buyer, seller, or admin can send messages.
    """
    result = await db.execute(
        select(Dispute).where(Dispute.id == dispute_id)
    )
    dispute = result.scalar_one_or_none()
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")

    # Determine sender role
    role_val = user.role if isinstance(user.role, str) else user.role.value
    if user.id == dispute.buyer_id:
        sender_role = "buyer"
    elif user.id == dispute.seller_id:
        sender_role = "seller"
    elif role_val in ("admin", "superadmin"):
        sender_role = "admin"
    else:
        raise HTTPException(status_code=403, detail="Not a participant in this dispute")

    # Check dispute is still open
    d_status = dispute.status if isinstance(dispute.status, str) else dispute.status.value
    if d_status in ("resolved_buyer", "resolved_seller", "resolved_split", "closed"):
        raise HTTPException(status_code=409, detail="Dispute is closed")

    message = DisputeMessage(
        dispute_id=dispute_id,
        sender_id=user.id,
        sender_role=sender_role,
        body=body.body,
        attachment_s3_key=body.attachment_s3_key,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    # Notify other party
    try:
        from app.tasks.notification import send_notification
        recipient_id = dispute.seller_id if sender_role == "buyer" else dispute.buyer_id
        send_notification.delay(
            event="dispute_message",
            user_id=recipient_id,
            data={
                "dispute_id": dispute_id,
                "sender_role": sender_role,
                "preview": body.body[:100],
            },
        )
    except Exception:
        pass

    return message


@router.get(
    "/disputes/{dispute_id}/messages",
    response_model=list[schemas.DisputeMessageOut],
)
async def list_dispute_messages(
    dispute_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all messages in a dispute thread."""
    # Verify participant access
    result = await db.execute(
        select(Dispute).where(Dispute.id == dispute_id)
    )
    dispute = result.scalar_one_or_none()
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")

    role_val = user.role if isinstance(user.role, str) else user.role.value
    if user.id not in (dispute.buyer_id, dispute.seller_id) and role_val not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Not a participant in this dispute")

    messages = await db.execute(
        select(DisputeMessage)
        .where(DisputeMessage.dispute_id == dispute_id)
        .order_by(DisputeMessage.created_at.asc())
    )
    return [schemas.DisputeMessageOut.model_validate(m) for m in messages.scalars().all()]


# ── Post-transaction Ratings — FR-RATE-001 ───────────────────

@router.post(
    "/{escrow_id}/rating",
    response_model=schemas.RatingOut,
    status_code=201,
)
async def submit_rating(
    escrow_id: str,
    body: schemas.SubmitRatingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a post-transaction rating.

    Only buyer can rate seller (and vice versa) once escrow is released.
    One rating per user per escrow.
    """
    escrow = await service.get_escrow(escrow_id, db)
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")

    state = escrow.state if isinstance(escrow.state, str) else escrow.state.value
    terminal = {"released", "resolved_released", "resolved_refunded", "resolved_split"}
    if state not in terminal:
        raise HTTPException(
            status_code=400,
            detail={"code": "ESCROW_NOT_COMPLETE", "message_en": "Can only rate after transaction completes"},
        )

    # Determine rater/ratee
    if user.id == escrow.winner_id:
        role = "buyer"
        ratee_id = escrow.seller_id
    elif user.id == escrow.seller_id:
        role = "seller"
        ratee_id = escrow.winner_id
    else:
        raise HTTPException(status_code=403, detail="Not a participant")

    # Check for existing rating by this user
    existing = await db.execute(
        select(Rating).where(
            Rating.escrow_id == escrow_id,
            Rating.rater_id == user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail={"code": "ALREADY_RATED", "message_en": "You have already rated this transaction"},
        )

    rating = Rating(
        escrow_id=escrow_id,
        rater_id=user.id,
        ratee_id=ratee_id,
        role=role,
        score=body.score,
        comment=body.comment,
        is_anonymous=body.is_anonymous,
    )
    db.add(rating)
    await db.commit()
    await db.refresh(rating)

    # Queue ATS update for the ratee
    try:
        from app.tasks.ats import update_ats_scores
        update_ats_scores.delay(user_id=ratee_id)
    except Exception:
        pass

    return rating


@router.get(
    "/{escrow_id}/rating",
    response_model=list[schemas.RatingOut],
)
async def get_ratings(
    escrow_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get ratings for an escrow transaction."""
    escrow = await service.get_escrow(escrow_id, db)
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")

    result = await db.execute(
        select(Rating).where(Rating.escrow_id == escrow_id)
    )
    return [schemas.RatingOut.model_validate(r) for r in result.scalars().all()]


# ── Aramex Shipping (P1-8) ──────────────────────────────────

@router.post("/{escrow_id}/shipment", response_model=schemas.ShipmentResponse)
async def create_shipment(
    escrow_id: str,
    body: schemas.CreateShipmentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an Aramex shipment for this escrow. Seller only.

    Generates a shipping label and tracking number, transitions
    escrow to label_generated state.
    """
    escrow = await service.get_escrow(escrow_id, db)
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    if user.id != escrow.seller_id:
        raise HTTPException(status_code=403, detail="Only seller can create shipment")
    if escrow.state not in ("shipping_requested", "funds_held"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot create shipment in state: {escrow.state}",
        )

    from app.services.escrow.shipping import Address, create_shipment as aramex_create

    seller_addr = Address(
        line1=body.seller_address.line1,
        line2=body.seller_address.line2,
        city=body.seller_address.city,
        state=body.seller_address.state,
        postal_code=body.seller_address.postal_code,
        country_code=body.seller_address.country_code,
        contact_name=body.seller_address.contact_name,
        phone=body.seller_address.phone,
        email=body.seller_address.email,
    )
    buyer_addr = Address(
        line1=body.buyer_address.line1,
        line2=body.buyer_address.line2,
        city=body.buyer_address.city,
        state=body.buyer_address.state,
        postal_code=body.buyer_address.postal_code,
        country_code=body.buyer_address.country_code,
        contact_name=body.buyer_address.contact_name,
        phone=body.buyer_address.phone,
        email=body.buyer_address.email,
    )

    result = await aramex_create(
        seller_address=seller_addr,
        buyer_address=buyer_addr,
        weight_kg=body.weight_kg,
        description=body.description,
        reference=escrow_id,
        currency=escrow.currency,
        declared_value=float(escrow.amount),
    )

    if not result.success:
        raise HTTPException(
            status_code=502,
            detail=f"Shipping provider error: {result.error}",
        )

    # Update escrow with tracking info and transition state
    escrow.tracking_number = result.tracking_number
    escrow.carrier = "aramex"
    updated = await service.transition_escrow(
        escrow.id, "label_generated", user.id, ActorType.SELLER.value,
        "seller.create_shipment",
        {
            "tracking_number": result.tracking_number,
            "carrier": "aramex",
            "label_url": result.label_url,
        },
        db,
    )

    return schemas.ShipmentResponse(
        success=True,
        tracking_number=result.tracking_number,
        label_url=result.label_url,
    )


@router.get("/{escrow_id}/tracking", response_model=schemas.TrackingResponse)
async def get_tracking(
    escrow_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get real-time tracking info for an escrow's shipment."""
    escrow = await service.get_escrow(escrow_id, db)
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    if user.id not in (escrow.seller_id, escrow.winner_id):
        raise HTTPException(status_code=403, detail="Not a participant")
    if not escrow.tracking_number:
        raise HTTPException(status_code=404, detail="No tracking number set")

    from app.services.escrow.shipping import track_shipment

    result = await track_shipment(escrow.tracking_number)

    events = [
        schemas.TrackingEventOut(
            timestamp=e.timestamp,
            location=e.location,
            description=e.description,
            code=e.code,
        )
        for e in result.events
    ]

    return schemas.TrackingResponse(
        success=result.success,
        tracking_number=result.tracking_number,
        current_status=result.current_status,
        delivered=result.delivered,
        events=events,
        error=result.error,
    )
