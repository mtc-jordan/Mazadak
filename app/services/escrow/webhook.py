"""
Checkout.com webhook processing — FR-ESC-003, PM-08.

Handles payment.captured, payment.declined, payment.refunded events
with HMAC-SHA256 signature verification and idempotent processing.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.escrow.fsm import InvalidTransitionError, transition_escrow
from app.services.escrow.models import ActorType, Escrow, VALID_TRANSITIONS
from app.services.escrow.service import get_escrow

logger = logging.getLogger(__name__)

# States that mean payment.captured was already processed
_CAPTURED_OR_BEYOND = frozenset(
    VALID_TRANSITIONS.keys() - {"initiated", "payment_pending", "payment_failed"}
)

MAX_PAYMENT_RETRIES = 3


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify Checkout.com HMAC-SHA256 webhook signature.

    Args:
        payload: Raw request body bytes.
        signature: Value of the ``cko-signature`` header.
        secret: ``CHECKOUT_WEBHOOK_SECRET`` from settings.

    Returns:
        True if the signature is valid.
    """
    expected = hmac.new(
        secret.encode(), payload, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def handle_webhook(
    event_type: str,
    data: dict,
    db: AsyncSession,
) -> dict:
    """Dispatch a verified webhook event to the appropriate handler.

    Returns a JSON-serialisable dict for the HTTP response body.
    """
    handlers = {
        "payment_captured": _handle_payment_captured,
        "payment_declined": _handle_payment_declined,
        "payment_refunded": _handle_payment_refunded,
    }

    handler = handlers.get(event_type)
    if handler is None:
        logger.info("Ignoring unhandled webhook event type: %s", event_type)
        return {"status": "ignored", "reason": "unhandled_event_type"}

    return await handler(data, db)


# ── payment.captured ──────────────────────────────────────────────

async def _handle_payment_captured(data: dict, db: AsyncSession) -> dict:
    """Process a successful payment capture.

    1. Look up escrow by reference (= escrow UUID).
    2. Idempotency: if already FUNDS_HELD or beyond, return 200.
    3. Verify captured amount matches escrow.amount within tolerance.
    4. Transition PAYMENT_PENDING → FUNDS_HELD.
    5. Immediately transition FUNDS_HELD → SHIPPING_REQUESTED.
    6. Set shipping_deadline = now + 48h.
    """
    escrow_id = data.get("reference")
    if not escrow_id:
        return {"status": "error", "reason": "missing_reference"}

    escrow = await get_escrow(escrow_id, db)
    if not escrow:
        logger.warning("Webhook payment.captured for unknown escrow %s", escrow_id)
        return {"status": "error", "reason": "escrow_not_found"}

    # ── Idempotency check ─────────────────────────────────────────
    current = escrow.state
    if hasattr(current, "value"):
        current = current.value

    if current in _CAPTURED_OR_BEYOND:
        logger.info("Duplicate payment.captured for escrow %s (state=%s)", escrow_id, current)
        return {"status": "already_processed", "state": current}

    # ── Amount verification ───────────────────────────────────────
    captured_amount = _minor_to_major(
        data.get("amount", 0), data.get("currency", "JOD"),
    )
    if abs(captured_amount - float(escrow.amount)) > 0.001:
        logger.error(
            "Amount mismatch for escrow %s: captured=%.3f, expected=%.3f",
            escrow_id, captured_amount, float(escrow.amount),
        )
        return {"status": "error", "reason": "amount_mismatch"}

    # ── PAYMENT_PENDING → FUNDS_HELD ──────────────────────────────
    payment_id = data.get("id", "")
    escrow = await transition_escrow(
        escrow_id, "funds_held", None, ActorType.SYSTEM,
        "checkout.payment_captured",
        meta={"payment_id": payment_id, "amount": captured_amount},
        db=db,
    )

    # ── FUNDS_HELD → SHIPPING_REQUESTED ───────────────────────────
    from app.core.config import settings
    deadline = datetime.now(timezone.utc) + timedelta(hours=settings.SHIPPING_DEADLINE_HOURS)

    escrow = await transition_escrow(
        escrow_id, "shipping_requested", None, ActorType.SYSTEM,
        "checkout.funds_confirmed",
        meta={"shipping_deadline": deadline.isoformat()},
        db=db,
    )

    # Set shipping deadline on the escrow row
    escrow.shipping_deadline = deadline.isoformat()
    await db.commit()
    await db.refresh(escrow)

    return {"status": "processed", "state": "shipping_requested"}


# ── payment.declined ──────────────────────────────────────────────

async def _handle_payment_declined(data: dict, db: AsyncSession) -> dict:
    """Process a declined payment.

    1. Look up escrow by reference.
    2. Transition PAYMENT_PENDING → PAYMENT_FAILED.
    3. Increment retry_count.
    4. After MAX_PAYMENT_RETRIES failures: transition to CANCELLED
       and notify second-highest bidder.
    """
    escrow_id = data.get("reference")
    if not escrow_id:
        return {"status": "error", "reason": "missing_reference"}

    escrow = await get_escrow(escrow_id, db)
    if not escrow:
        return {"status": "error", "reason": "escrow_not_found"}

    current = escrow.state
    if hasattr(current, "value"):
        current = current.value

    # Only process if in payment_pending
    if current != "payment_pending":
        logger.info(
            "Ignoring payment.declined for escrow %s (state=%s)", escrow_id, current,
        )
        return {"status": "ignored", "reason": "not_payment_pending", "state": current}

    decline_reason = data.get("response_summary", "unknown")
    payment_id = data.get("id", "")

    # ── PAYMENT_PENDING → PAYMENT_FAILED ──────────────────────────
    escrow = await transition_escrow(
        escrow_id, "payment_failed", None, ActorType.SYSTEM,
        "checkout.payment_declined",
        meta={"payment_id": payment_id, "reason": decline_reason},
        db=db,
    )

    # ── Increment retry count ─────────────────────────────────────
    escrow.retry_count = (escrow.retry_count or 0) + 1
    await db.commit()
    await db.refresh(escrow)

    # ── After max retries → CANCELLED + notify second bidder ──────
    if escrow.retry_count >= MAX_PAYMENT_RETRIES:
        escrow = await transition_escrow(
            escrow_id, "cancelled", None, ActorType.SYSTEM,
            "checkout.max_retries_exceeded",
            meta={"retry_count": escrow.retry_count, "last_decline": decline_reason},
            db=db,
        )
        _dispatch_second_bidder_notification(escrow)
        return {
            "status": "processed",
            "state": "cancelled",
            "retry_count": escrow.retry_count,
        }

    return {
        "status": "processed",
        "state": "payment_failed",
        "retry_count": escrow.retry_count,
    }


# ── payment.refunded ─────────────────────────────────────────────

async def _handle_payment_refunded(data: dict, db: AsyncSession) -> dict:
    """Process a Checkout.com refund confirmation.

    This webhook arrives after a mediator-initiated refund is processed
    by Checkout.com. If the escrow is in ``under_review`` we transition
    to ``refunded``; otherwise we log and return 200.
    """
    escrow_id = data.get("reference")
    if not escrow_id:
        return {"status": "error", "reason": "missing_reference"}

    escrow = await get_escrow(escrow_id, db)
    if not escrow:
        return {"status": "error", "reason": "escrow_not_found"}

    current = escrow.state
    if hasattr(current, "value"):
        current = current.value

    if current == "refunded":
        return {"status": "already_processed", "state": "refunded"}

    if "refunded" not in VALID_TRANSITIONS.get(current, []):
        logger.info(
            "Cannot apply payment.refunded to escrow %s (state=%s)", escrow_id, current,
        )
        return {"status": "ignored", "reason": "invalid_state", "state": current}

    payment_id = data.get("id", "")
    escrow = await transition_escrow(
        escrow_id, "refunded", None, ActorType.SYSTEM,
        "checkout.payment_refunded",
        meta={"payment_id": payment_id},
        db=db,
    )
    return {"status": "processed", "state": "refunded"}


# ── Helpers ───────────────────────────────────────────────────────

def _minor_to_major(amount_minor: int, currency: str) -> float:
    """Convert Checkout.com minor-unit amount to major units.

    JOD uses 3 decimal places (1 JOD = 1000 fils).
    Most other currencies use 2 (1 USD = 100 cents).
    """
    three_decimal = {"jod", "kwd", "bhd", "omr"}
    divisor = 1000 if currency.lower() in three_decimal else 100
    return round(amount_minor / divisor, 3)


def _dispatch_second_bidder_notification(escrow: Escrow) -> None:
    """Queue a Celery task to notify the second-highest bidder."""
    try:
        from app.tasks.escrow import notify_second_bidder
        notify_second_bidder.delay(escrow.auction_id)
    except Exception:
        logger.warning(
            "Failed to dispatch second-bidder notification for auction %s",
            escrow.auction_id,
        )
