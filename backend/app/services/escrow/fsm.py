"""
Escrow FSM engine — SDD §3.3, PM-08.

12-state escrow state machine with pessimistic row locking.

Every state transition is:
1. Locked with pessimistic row lock (SELECT FOR UPDATE NOWAIT)
2. Validated against VALID_TRANSITIONS
3. Written to append-only escrow_events BEFORE state update
4. Deadlines set based on new state
5. Followed by async notification dispatch

Exceptions:
    InvalidTransitionError — FSM rejects the transition
    EscrowLockError        — another process holds the escrow lock
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.escrow.models import (
    Escrow,
    EscrowEvent,
    VALID_TRANSITIONS,
    TERMINAL_STATES,
)

logger = logging.getLogger(__name__)


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed by the FSM."""


class EscrowLockError(Exception):
    """Raised when another process holds the escrow lock."""


async def transition_escrow(
    escrow_id: UUID,
    new_state: str,
    actor_id: Optional[UUID],
    actor_type: str,
    trigger: str,
    metadata: dict,
    db: AsyncSession,
) -> Escrow:
    """Atomic state transition with pessimistic locking.

    1. SELECT FOR UPDATE NOWAIT — acquire row lock or raise EscrowLockError
    2. Validate transition against VALID_TRANSITIONS
    3. INSERT escrow_event BEFORE state update (audit trail is append-only)
    4. UPDATE escrow state + transition_count + last_transition_at
    5. Set deadlines based on new state
    6. Commit deferred to caller's db.commit()
    7. After commit: dispatch_escrow_notifications.delay()
    """
    eid = str(escrow_id) if isinstance(escrow_id, UUID) else escrow_id

    # ── 1. Acquire row lock (NOWAIT — fail fast if locked) ───────
    try:
        result = await db.execute(
            select(Escrow)
            .where(Escrow.id == eid)
            .with_for_update(nowait=True)
        )
        escrow = result.scalar_one_or_none()
    except OperationalError as e:
        if "could not obtain lock" in str(e).lower():
            raise EscrowLockError(
                f"Escrow {escrow_id} locked by concurrent process"
            ) from e
        raise
    except Exception as exc:
        err = str(exc).lower()
        if "could not obtain lock" in err or "55p03" in err:
            raise EscrowLockError(
                f"Escrow {escrow_id} locked by concurrent process"
            ) from exc
        raise

    if not escrow:
        raise ValueError(f"Escrow {escrow_id} not found")

    # ── 2. Validate transition ───────────────────────────────────
    current = escrow.state
    if hasattr(current, "value"):
        current = current.value

    allowed = VALID_TRANSITIONS.get(current, [])
    if new_state not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition escrow from '{current}' to '{new_state}'. "
            f"Allowed: {allowed}"
        )

    old_state = current

    # ── 3. INSERT event FIRST (before state update) ──────────────
    actor_id_str = str(actor_id) if actor_id is not None else None
    event = EscrowEvent(
        escrow_id=eid,
        from_state=old_state,
        to_state=new_state,
        actor_id=actor_id_str,
        actor_type=actor_type,
        trigger=trigger,
        meta=metadata or {},
    )
    db.add(event)
    await db.flush()  # ensure event row exists before state change

    # ── 4. UPDATE escrow state ───────────────────────────────────
    now = datetime.utcnow()
    escrow.state = new_state
    escrow.last_transition_at = now
    escrow.transition_count = (escrow.transition_count or 0) + 1

    # ── 5. Set deadlines based on new state ──────────────────────
    if new_state == "payment_pending":
        escrow.payment_deadline = now + timedelta(hours=24)
    elif new_state == "shipping_requested":
        escrow.shipping_deadline = now + timedelta(hours=48)
    elif new_state == "inspection_period":
        escrow.inspection_deadline = now + timedelta(hours=72)
    elif new_state == "under_review":
        escrow.release_deadline = now + timedelta(hours=144)

    # ── 6. Commit ────────────────────────────────────────────────
    await db.commit()
    await db.refresh(escrow)

    # ── 7. After commit: queue notifications (in background) ─────
    try:
        from app.tasks.escrow import dispatch_escrow_notifications
        dispatch_escrow_notifications.delay(
            escrow_id=eid,
            from_state=old_state,
            to_state=new_state,
            trigger=trigger,
            metadata=metadata,
        )
    except Exception:
        logger.warning(
            "Failed to dispatch escrow notification for %s: %s → %s",
            eid, old_state, new_state,
        )

    return escrow
