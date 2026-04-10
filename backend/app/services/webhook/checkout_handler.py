"""
Checkout.com webhook handler — FR-ESC-003, PM-08.

Handles payment.captured, payment.declined, payment.refunded,
payment.refund_declined events with HMAC-SHA256 signature verification
and idempotent processing.

Route: POST /api/v1/webhooks/checkout  (no JWT — HMAC-verified)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.escrow.fsm import transition_escrow
from app.services.escrow.models import Escrow, EscrowEvent

logger = logging.getLogger(__name__)

MAX_PAYMENT_RETRIES = 3


# ── Signature verification (FastAPI dependency) ─────────────────────

async def verify_checkout_signature(request: Request) -> bytes:
    """FastAPI dependency — verify Checkout.com HMAC-SHA256 signature.

    Reads the raw body, validates against the ``cko-signature`` header,
    and returns the raw bytes for further processing.

    Raises 403 if the signature is missing or invalid.
    """
    raw_body = await request.body()
    signature = request.headers.get("cko-signature")

    if not signature:
        raise HTTPException(403, "Missing webhook signature")

    expected = hmac.new(
        settings.CHECKOUT_WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(403, "Invalid webhook signature")

    return raw_body


# ── Main dispatcher ──────────────────────────────────────────────────

async def handle_checkout_webhook(
    raw_body: bytes,
    db: AsyncSession,
) -> dict:
    """Parse verified payload and dispatch to the appropriate handler.

    Always returns ``{'success': True}`` — Checkout.com retries on non-2xx.
    """
    payload = json.loads(raw_body)
    event_type = payload.get("type")

    logger.info(
        "checkout_webhook_received event_type=%s payment_id=%s",
        event_type,
        payload.get("data", {}).get("id"),
    )

    if event_type == "payment.captured":
        await handle_payment_captured(payload["data"], db)
    elif event_type == "payment.declined":
        await handle_payment_declined(payload["data"], db)
    elif event_type == "payment.refunded":
        await handle_payment_refunded(payload["data"], db)
    elif event_type == "payment.refund_declined":
        await handle_refund_declined(payload["data"], db)

    return {"success": True}


# ── payment.captured ─────────────────────────────────────────────────

async def handle_payment_captured(data: dict, db: AsyncSession) -> None:
    """Process a successful payment capture.

    1. Load escrow by reference (= escrow UUID).
    2. Idempotency: if not payment_pending, already processed.
    3. Verify captured amount within +-1 minor unit tolerance.
    4. Double transition: payment_pending -> funds_held -> shipping_requested.
    5. Store checkout_payment_id.
    """
    payment_id = data["id"]
    escrow_ref = data.get("reference")
    captured_amount = data["amount"]  # minor units (fils/pence)
    currency = data["currency"]

    # Load escrow by reference
    escrow = await db.scalar(select(Escrow).where(Escrow.id == escrow_ref))
    if not escrow:
        logger.error("checkout_webhook_escrow_not_found reference=%s", escrow_ref)
        return  # return 200 to Checkout (don't retry unresolvable)

    # ── Idempotency: already past payment_pending ────────────────
    current = escrow.state
    if hasattr(current, "value"):
        current = current.value

    if current not in ("payment_pending",):
        logger.info(
            "checkout_webhook_duplicate escrow_id=%s current_state=%s",
            escrow_ref, current,
        )
        return

    # ── Amount verification (+-1 minor unit for FX rounding) ─────
    expected_minor = _major_to_minor(float(escrow.amount), currency)
    if abs(captured_amount - expected_minor) > 1:
        logger.error(
            "checkout_amount_mismatch expected=%d actual=%d escrow_id=%s",
            expected_minor, captured_amount, escrow_ref,
        )
        # Flag for manual review, do NOT transition
        await flag_escrow_for_review(escrow.id, "amount_mismatch", db)
        return

    # ── Transition: payment_pending -> funds_held ────────────────
    escrow = await transition_escrow(
        escrow.id, "funds_held", None, "webhook",
        "webhook.payment_captured",
        {"checkout_payment_id": payment_id},
        db,
    )

    # ── Transition: funds_held -> shipping_requested ─────────────
    escrow = await transition_escrow(
        escrow.id, "shipping_requested", None, "system",
        "system.auto_shipping_request",
        {},
        db,
    )

    # ── Store checkout_payment_id ────────────────────────────────
    escrow.checkout_payment_id = payment_id
    await db.commit()


# ── payment.declined ─────────────────────────────────────────────────

async def handle_payment_declined(data: dict, db: AsyncSession) -> None:
    """Process a declined payment.

    1. Load escrow by reference.
    2. Only process if in payment_pending.
    3. Increment retry_count.
    4. After MAX_PAYMENT_RETRIES (3): cancel + notify second-place bidder.
    """
    escrow_ref = data.get("reference")
    escrow = await db.scalar(select(Escrow).where(Escrow.id == escrow_ref))
    if not escrow:
        return

    current = escrow.state
    if hasattr(current, "value"):
        current = current.value

    if current != "payment_pending":
        return

    # ── Increment retry count ────────────────────────────────────
    retry_count = (escrow.retry_count or 0) + 1
    escrow.retry_count = retry_count

    if retry_count >= MAX_PAYMENT_RETRIES:
        # Transition to cancelled, notify second-place bidder
        await transition_escrow(
            escrow.id, "cancelled", None, "system",
            "payment.declined.max_retries",
            {"retry_count": retry_count},
            db,
        )
        try:
            from app.tasks.escrow import notify_second_place_bidder
            notify_second_place_bidder.delay(str(escrow.auction_id))
        except Exception:
            logger.warning(
                "Failed to dispatch second-place-bidder notification for auction %s",
                escrow.auction_id,
            )
    else:
        # Notify buyer to retry payment
        try:
            from app.tasks.escrow import notify_payment_failed
            notify_payment_failed.delay(str(escrow.winner_id), retry_count)
        except Exception:
            logger.warning(
                "Failed to dispatch payment-failed notification for escrow %s",
                escrow.id,
            )

    await db.commit()


# ── payment.refunded ─────────────────────────────────────────────────

async def handle_payment_refunded(data: dict, db: AsyncSession) -> None:
    """Process a Checkout.com refund confirmation.

    Transitions from under_review -> resolved_refunded.
    """
    escrow_ref = data.get("reference")
    escrow = await db.scalar(select(Escrow).where(Escrow.id == escrow_ref))
    if not escrow:
        return

    current = escrow.state
    if hasattr(current, "value"):
        current = current.value

    if current == "resolved_refunded":
        return  # already processed

    from app.services.escrow.models import VALID_TRANSITIONS
    if "resolved_refunded" not in VALID_TRANSITIONS.get(current, []):
        logger.info(
            "Cannot apply payment.refunded to escrow %s (state=%s)",
            escrow_ref, current,
        )
        return

    payment_id = data.get("id", "")
    await transition_escrow(
        escrow.id, "resolved_refunded", None, "system",
        "checkout.payment_refunded",
        {"payment_id": payment_id},
        db,
    )


# ── payment.refund_declined ──────────────────────────────────────────

async def handle_refund_declined(data: dict, db: AsyncSession) -> None:
    """Process a refund that was declined by Checkout.com.

    Flags the escrow for manual review by an admin.
    """
    escrow_ref = data.get("reference")
    escrow = await db.scalar(select(Escrow).where(Escrow.id == escrow_ref))
    if not escrow:
        return

    decline_reason = data.get("response_summary", "unknown")
    logger.error(
        "Refund declined for escrow %s: reason=%s",
        escrow_ref, decline_reason,
    )

    await flag_escrow_for_review(
        escrow.id, f"refund_declined: {decline_reason}", db,
    )


# ── Helpers ──────────────────────────────────────────────────────────

def _major_to_minor(amount: float, currency: str) -> int:
    """Convert major-unit amount to Checkout.com minor units.

    JOD/KWD/BHD/OMR use 3 decimal places (1 JOD = 1000 fils).
    Most other currencies use 2 (1 USD = 100 cents).
    """
    three_decimal = {"jod", "kwd", "bhd", "omr"}
    multiplier = 1000 if currency.lower() in three_decimal else 100
    return round(amount * multiplier)


async def flag_escrow_for_review(
    escrow_id: str,
    reason: str,
    db: AsyncSession,
) -> None:
    """Flag an escrow for manual admin review.

    Inserts an audit event so the ops dashboard surfaces it.
    """
    escrow = await db.scalar(select(Escrow).where(Escrow.id == escrow_id))
    if not escrow:
        return

    current = escrow.state
    if hasattr(current, "value"):
        current = current.value

    event = EscrowEvent(
        escrow_id=str(escrow_id),
        from_state=current,
        to_state=current,
        actor_id=None,
        actor_type="system",
        trigger="system.flag_for_review",
        meta={"reason": reason},
    )
    db.add(event)
    await db.commit()

    logger.warning("Escrow %s flagged for review: %s", escrow_id, reason)
