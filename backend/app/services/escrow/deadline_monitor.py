"""
Escrow deadline monitor — Celery Beat task (every 5 min, queue='high').

Scans active escrows for expired deadlines and enforces state transitions:
  1. PAYMENT_PENDING   → payment_deadline expired       → CANCELLED
  2. SHIPPING_REQUESTED → shipping_deadline + 15 min     → DISPUTED  (+ seller strike + ATS)
  3. INSPECTION_PERIOD  → inspection_deadline + 15 min   → RELEASED  (+ seller payout)
  4. UNDER_REVIEW       → 72 h  → escalate
  5. UNDER_REVIEW       → 120 h → propose 50/50
  6. UNDER_REVIEW       → 144 h → auto-execute 50/50
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.escrow.fsm import (
    InvalidTransitionError,
    EscrowLockError,
    transition_escrow,
)
from app.services.escrow.models import Escrow

logger = logging.getLogger(__name__)

GRACE = timedelta(minutes=15)


async def check_escrow_deadlines(db: AsyncSession) -> None:
    """Scan all active escrows for expired deadlines.

    Called by Celery Beat ``check_deadlines`` task every 5 minutes.
    """
    now = datetime.utcnow()
    grace = GRACE
    cutoff = (now - grace).isoformat()

    payment_cancelled = 0
    shipping_disputed = 0
    inspection_released = 0

    # ── 1. PAYMENT_PENDING expired ───────────────────────────────
    overdue_payment = (
        await db.scalars(
            select(Escrow).where(
                Escrow.state == "payment_pending",
                Escrow.payment_deadline < cutoff,
                Escrow.payment_deadline.isnot(None),
            )
        )
    ).all()

    for escrow in overdue_payment:
        try:
            await transition_escrow(
                escrow.id, "cancelled", None, "system",
                "deadline.payment_expired",
                {"deadline": escrow.payment_deadline},
                db,
            )
            # Void Checkout.com payment intent if exists
            if escrow.payment_intent_id:
                _dispatch_void_checkout_payment(escrow.payment_intent_id)
            payment_cancelled += 1
        except (InvalidTransitionError, EscrowLockError) as exc:
            logger.debug("Skipping escrow %s: %s", escrow.id, exc)

    # ── 2. SHIPPING_REQUESTED expired — seller no-show ───────────
    overdue_shipping = (
        await db.scalars(
            select(Escrow).where(
                Escrow.state == "shipping_requested",
                Escrow.shipping_deadline < cutoff,
                Escrow.shipping_deadline.isnot(None),
            )
        )
    ).all()

    for escrow in overdue_shipping:
        try:
            await transition_escrow(
                escrow.id, "disputed", None, "system",
                "deadline.shipping_expired",
                {"reason": "seller_no_show_48h"},
                db,
            )
            # Increment seller strike count
            from app.services.auth.models import User
            await db.execute(
                update(User)
                .where(User.id == escrow.seller_id)
                .values(strike_count=User.strike_count + 1)
            )
            # Update seller ATS speed score
            _dispatch_update_ats_score(str(escrow.seller_id), "shipping_deadline_missed")
            shipping_disputed += 1
        except (InvalidTransitionError, EscrowLockError) as exc:
            logger.debug("Skipping escrow %s: %s", escrow.id, exc)

    # ── 3. INSPECTION_PERIOD expired — auto release to seller ────
    overdue_inspection = (
        await db.scalars(
            select(Escrow).where(
                Escrow.state == "inspection_period",
                Escrow.inspection_deadline < cutoff,
                Escrow.inspection_deadline.isnot(None),
            )
        )
    ).all()

    for escrow in overdue_inspection:
        try:
            await transition_escrow(
                escrow.id, "released", None, "system",
                "deadline.inspection_expired",
                {"reason": "auto_release_72h"},
                db,
            )
            # Trigger Checkout.com payout to seller
            _dispatch_trigger_seller_payout(str(escrow.id))
            inspection_released += 1
        except (InvalidTransitionError, EscrowLockError) as exc:
            logger.debug("Skipping escrow %s: %s", escrow.id, exc)

    # ── 4. UNDER_REVIEW mediator SLA checks ──────────────────────
    under_review = (
        await db.scalars(
            select(Escrow).where(Escrow.state == "under_review")
        )
    ).all()

    for escrow in under_review:
        entered_at = _parse_datetime(escrow.last_transition_at)
        if entered_at is None:
            continue

        hours_in_review = (now - entered_at).total_seconds() / 3600

        if hours_in_review >= 144:  # 6 days — auto 50/50 split
            try:
                await transition_escrow(
                    escrow.id, "resolved_split", None, "system",
                    "deadline.auto_split",
                    {"split_reason": "mediator_sla_144h_exceeded"},
                    db,
                )
                _dispatch_trigger_split_payout(str(escrow.id))
            except (InvalidTransitionError, EscrowLockError) as exc:
                logger.debug("Skipping escrow %s: %s", escrow.id, exc)

        elif hours_in_review >= 120:  # 5 days — propose 50/50
            _dispatch_notify_mediator_propose_split(
                str(escrow.mediator_id), str(escrow.id),
            )

        elif hours_in_review >= 72:  # 3 days — escalate
            _dispatch_notify_mediator_sla_breach(str(escrow.id))

    await db.commit()

    logger.info(
        "deadline_check_complete payment_cancelled=%d "
        "shipping_disputed=%d inspection_released=%d",
        payment_cancelled, shipping_disputed, inspection_released,
    )


# ── Datetime parsing ─────────────────────────────────────────────

def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO-8601 string to naive UTC datetime for comparison."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        # Strip tzinfo for utcnow() comparison
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return None


# ── Celery task dispatchers (best-effort, non-blocking) ──────────

def _dispatch_void_checkout_payment(payment_intent_id: str) -> None:
    try:
        from app.tasks.escrow import void_checkout_payment
        void_checkout_payment.delay(payment_intent_id)
    except Exception:
        logger.warning(
            "Failed to dispatch void for payment intent %s", payment_intent_id,
        )


def _dispatch_update_ats_score(seller_id: str, reason: str) -> None:
    try:
        from app.tasks.escrow import update_ats_score
        update_ats_score.delay(seller_id, reason)
    except Exception:
        logger.warning(
            "Failed to dispatch ATS update for seller %s", seller_id,
        )


def _dispatch_trigger_seller_payout(escrow_id: str) -> None:
    try:
        from app.tasks.escrow import trigger_seller_payout
        trigger_seller_payout.delay(escrow_id)
    except Exception:
        logger.warning(
            "Failed to dispatch seller payout for escrow %s", escrow_id,
        )


def _dispatch_trigger_split_payout(escrow_id: str) -> None:
    try:
        from app.tasks.escrow import trigger_split_payout
        trigger_split_payout.delay(escrow_id)
    except Exception:
        logger.warning(
            "Failed to dispatch split payout for escrow %s", escrow_id,
        )


def _dispatch_notify_mediator_propose_split(
    mediator_id: str, escrow_id: str,
) -> None:
    try:
        from app.tasks.escrow import notify_mediator_propose_split
        notify_mediator_propose_split.delay(mediator_id, escrow_id)
    except Exception:
        logger.warning(
            "Failed to dispatch mediator propose-split for escrow %s", escrow_id,
        )


def _dispatch_notify_mediator_sla_breach(escrow_id: str) -> None:
    try:
        from app.tasks.escrow import notify_mediator_sla_breach
        notify_mediator_sla_breach.delay(escrow_id)
    except Exception:
        logger.warning(
            "Failed to dispatch mediator SLA breach for escrow %s", escrow_id,
        )
