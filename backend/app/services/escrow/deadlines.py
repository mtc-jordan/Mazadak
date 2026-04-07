"""
Escrow deadline monitoring — FR-ESC-019, PM-08.

Scanned every 5 minutes by Celery Beat.  Each expired deadline
triggers a transition_escrow() call which acquires the row lock,
writes the audit event, and updates state atomically.

Deadline types
--------------
1. PAYMENT_PENDING   → payment_deadline expired       → CANCELLED
2. SHIPPING_REQUESTED → shipping_deadline + 15 min     → DISPUTED  (+ seller strike)
3. INSPECTION_PERIOD  → inspection_deadline + 15 min   → RELEASED  (auto-release)
4. UNDER_REVIEW       → 72 h since entry              → escalate to admin
5. UNDER_REVIEW       → 120 h since entry             → propose 50/50 split
6. UNDER_REVIEW       → 144 h since entry             → auto-execute 50/50
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.escrow.fsm import (
    InvalidTransitionError,
    NoWaitLockError,
    transition_escrow,
)
from app.services.escrow.models import (
    ActorType,
    Escrow,
    EscrowEvent,
    EscrowState,
)

logger = logging.getLogger(__name__)

GRACE_PERIOD = timedelta(minutes=15)
MEDIATOR_SLA_ESCALATE = timedelta(hours=72)
MEDIATOR_SLA_PROPOSE = timedelta(hours=120)
MEDIATOR_SLA_AUTO_EXECUTE = timedelta(hours=144)


# ── Public entry point ────────────────────────────────────────────

async def check_escrow_deadlines(db: AsyncSession) -> dict:
    """Scan all active escrows for expired deadlines.

    Returns a summary dict with counts of each action taken.
    """
    now = datetime.now(timezone.utc)
    results = {
        "payment_expired": 0,
        "shipping_expired": 0,
        "inspection_expired": 0,
        "mediator_escalated": 0,
        "mediator_proposed": 0,
        "mediator_auto_executed": 0,
    }

    await _check_payment_deadlines(db, now, results)
    await _check_shipping_deadlines(db, now, results)
    await _check_inspection_deadlines(db, now, results)
    await _check_mediator_sla(db, now, results)

    return results


# ── 1. PAYMENT_PENDING past payment_deadline → CANCELLED ─────────

async def _check_payment_deadlines(
    db: AsyncSession, now: datetime, results: dict,
) -> None:
    rows = await _query_state(db, EscrowState.PAYMENT_PENDING)
    for escrow in rows:
        deadline = _parse_deadline(escrow.payment_deadline)
        if deadline is None or now <= deadline:
            continue

        try:
            await transition_escrow(
                escrow.id, "cancelled", None, ActorType.SYSTEM,
                "system.payment_deadline_expired",
                meta={"deadline": escrow.payment_deadline},
                db=db,
            )
            _void_payment_intent(escrow)
            results["payment_expired"] += 1
            logger.info("Payment deadline expired → CANCELLED: %s", escrow.id)
        except (InvalidTransitionError, NoWaitLockError) as exc:
            logger.debug("Skipping escrow %s: %s", escrow.id, exc)


# ── 2. SHIPPING_REQUESTED past shipping_deadline + 15 min → DISPUTED

async def _check_shipping_deadlines(
    db: AsyncSession, now: datetime, results: dict,
) -> None:
    rows = await _query_state(db, EscrowState.SHIPPING_REQUESTED)
    for escrow in rows:
        deadline = _parse_deadline(escrow.shipping_deadline)
        if deadline is None or now <= (deadline + GRACE_PERIOD):
            continue

        try:
            await transition_escrow(
                escrow.id, "disputed", None, ActorType.SYSTEM,
                "system.seller_no_show_48h",
                meta={
                    "deadline": escrow.shipping_deadline,
                    "seller_id": escrow.seller_id,
                },
                db=db,
            )
            await _increment_seller_strike(db, escrow.seller_id)
            results["shipping_expired"] += 1
            logger.info(
                "Shipping deadline expired → DISPUTED: %s (seller %s striked)",
                escrow.id, escrow.seller_id,
            )
        except (InvalidTransitionError, NoWaitLockError) as exc:
            logger.debug("Skipping escrow %s: %s", escrow.id, exc)


# ── 3. INSPECTION_PERIOD past inspection_deadline + 15 min → RELEASED

async def _check_inspection_deadlines(
    db: AsyncSession, now: datetime, results: dict,
) -> None:
    rows = await _query_state(db, EscrowState.INSPECTION_PERIOD)
    for escrow in rows:
        deadline = _parse_deadline(escrow.inspection_deadline)
        if deadline is None or now <= (deadline + GRACE_PERIOD):
            continue

        try:
            await transition_escrow(
                escrow.id, "released", None, ActorType.SYSTEM,
                "system.inspection_auto_release",
                meta={"deadline": escrow.inspection_deadline},
                db=db,
            )
            results["inspection_expired"] += 1
            logger.info("Inspection deadline expired → RELEASED: %s", escrow.id)
        except (InvalidTransitionError, NoWaitLockError) as exc:
            logger.debug("Skipping escrow %s: %s", escrow.id, exc)


# ── 4–6. UNDER_REVIEW mediator SLA (72 h / 120 h / 144 h) ───────

async def _check_mediator_sla(
    db: AsyncSession, now: datetime, results: dict,
) -> None:
    rows = await _query_state(db, EscrowState.UNDER_REVIEW)
    for escrow in rows:
        entered_at = await _get_state_entry_time(db, escrow.id, "under_review")
        if entered_at is None:
            continue

        elapsed = now - entered_at

        # ── 144 h → auto-execute 50/50 ───────────────────────────
        if elapsed >= MEDIATOR_SLA_AUTO_EXECUTE:
            if await _has_trigger(db, escrow.id, "system.mediator_sla_144h_auto_execute"):
                continue
            try:
                escrow_obj = await transition_escrow(
                    escrow.id, "partially_released", None, ActorType.SYSTEM,
                    "system.mediator_sla_144h_auto_execute",
                    meta={
                        "elapsed_hours": elapsed.total_seconds() / 3600,
                        "split": {"seller_pct": 50, "buyer_pct": 50},
                    },
                    db=db,
                )
                escrow_obj.seller_amount = float(escrow.amount) * 0.5
                await db.commit()
                results["mediator_auto_executed"] += 1
                logger.info("Mediator SLA 144h → PARTIALLY_RELEASED: %s", escrow.id)
            except (InvalidTransitionError, NoWaitLockError) as exc:
                logger.debug("Skipping escrow %s: %s", escrow.id, exc)
            continue

        # ── 120 h → propose 50/50 split ──────────────────────────
        if elapsed >= MEDIATOR_SLA_PROPOSE:
            if await _has_trigger(db, escrow.id, "system.mediator_sla_120h_propose"):
                continue
            event = EscrowEvent(
                escrow_id=escrow.id,
                from_state="under_review",
                to_state="under_review",
                actor_id=None,
                actor_type=ActorType.SYSTEM,
                trigger="system.mediator_sla_120h_propose",
                meta={"proposed_split": {"seller_pct": 50, "buyer_pct": 50}},
            )
            db.add(event)
            await db.commit()
            _dispatch_notification(escrow.id, "mediator_sla_120h_propose")
            results["mediator_proposed"] += 1
            logger.info("Mediator SLA 120h → proposed 50/50: %s", escrow.id)
            continue

        # ── 72 h → escalate to admin ─────────────────────────────
        if elapsed >= MEDIATOR_SLA_ESCALATE:
            if await _has_trigger(db, escrow.id, "system.mediator_sla_72h_escalation"):
                continue
            event = EscrowEvent(
                escrow_id=escrow.id,
                from_state="under_review",
                to_state="under_review",
                actor_id=None,
                actor_type=ActorType.SYSTEM,
                trigger="system.mediator_sla_72h_escalation",
                meta={"elapsed_hours": elapsed.total_seconds() / 3600},
            )
            db.add(event)
            await db.commit()
            _dispatch_notification(escrow.id, "mediator_sla_72h_escalation")
            results["mediator_escalated"] += 1
            logger.info("Mediator SLA 72h → escalated: %s", escrow.id)


# ── Helpers ───────────────────────────────────────────────────────

async def _query_state(db: AsyncSession, state: EscrowState) -> list[Escrow]:
    result = await db.execute(
        select(Escrow).where(Escrow.state == state.value)
    )
    return list(result.scalars().all())


def _parse_deadline(value: str | None) -> datetime | None:
    """Parse an ISO-8601 deadline string to an aware UTC datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


async def _get_state_entry_time(
    db: AsyncSession, escrow_id: str, state: str,
) -> datetime | None:
    """Return the created_at of the earliest event transitioning INTO state."""
    result = await db.execute(
        select(EscrowEvent.created_at)
        .where(EscrowEvent.escrow_id == escrow_id)
        .where(EscrowEvent.to_state == state)
        .order_by(EscrowEvent.created_at.asc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if isinstance(row, str):
        return _parse_deadline(row)
    return row if row.tzinfo else row.replace(tzinfo=timezone.utc)


async def _has_trigger(db: AsyncSession, escrow_id: str, trigger: str) -> bool:
    """Check if an event with the given trigger already exists."""
    result = await db.execute(
        select(EscrowEvent.id)
        .where(EscrowEvent.escrow_id == escrow_id)
        .where(EscrowEvent.trigger == trigger)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _increment_seller_strike(db: AsyncSession, seller_id: str) -> None:
    """Increment seller's strike_count by 1."""
    from app.services.auth.models import User

    result = await db.execute(select(User).where(User.id == seller_id))
    user = result.scalar_one_or_none()
    if user:
        user.strike_count = (user.strike_count or 0) + 1
        await db.commit()
        logger.info("Seller %s strike_count → %d", seller_id, user.strike_count)


def _void_payment_intent(escrow: Escrow) -> None:
    """Queue Checkout.com payment intent void (best-effort)."""
    if not escrow.payment_intent_id:
        return
    try:
        from app.tasks.escrow import void_payment_intent
        void_payment_intent.delay(escrow.payment_intent_id)
    except Exception:
        logger.warning(
            "Failed to dispatch void for payment intent %s",
            escrow.payment_intent_id,
        )


def _dispatch_notification(escrow_id: str, event_type: str) -> None:
    """Fire a Celery notification task (best-effort)."""
    try:
        from app.tasks.escrow import dispatch_escrow_notifications
        dispatch_escrow_notifications.delay(escrow_id, event_type)
    except Exception:
        logger.warning("Failed to dispatch notification %s for %s", event_type, escrow_id)
