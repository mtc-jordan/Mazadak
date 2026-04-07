"""
Escrow FSM engine — SDD §3.3, PM-08.

Every state transition is:
1. Locked with pessimistic row lock (SELECT FOR UPDATE NOWAIT)
2. Validated against VALID_TRANSITIONS
3. Written to append-only escrow_events BEFORE state update
4. Followed by async notification dispatch

Exceptions:
    InvalidTransitionError — FSM rejects the transition
    NoWaitLockError        — another transaction holds the row lock
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.escrow.models import (
    ActorType,
    Escrow,
    EscrowEvent,
    VALID_TRANSITIONS,
)

logger = logging.getLogger(__name__)


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed by the FSM."""


class NoWaitLockError(Exception):
    """Raised when SELECT FOR UPDATE NOWAIT cannot acquire the row lock."""


async def transition_escrow(
    escrow_id: str,
    new_state: str,
    actor_id: str | None,
    actor_type: ActorType,
    trigger: str,
    meta: dict | None = None,
    *,
    db: AsyncSession,
) -> Escrow:
    """Atomic state transition with pessimistic locking.

    1. SELECT FOR UPDATE NOWAIT — acquire row lock or raise NoWaitLockError
    2. Validate transition against VALID_TRANSITIONS
    3. INSERT escrow_event BEFORE state update (audit trail)
    4. UPDATE escrow state
    5. After commit: dispatch_escrow_notifications.delay()
    """
    # ── 1. Pessimistic lock ───────────────────────────────────────
    try:
        result = await db.execute(
            select(Escrow)
            .where(Escrow.id == escrow_id)
            .with_for_update(nowait=True)
        )
    except Exception as exc:
        err = str(exc).lower()
        if "could not obtain lock" in err or "55p03" in err:
            raise NoWaitLockError(
                f"Escrow {escrow_id} is locked by another transaction"
            ) from exc
        raise

    escrow = result.scalar_one_or_none()
    if not escrow:
        raise ValueError(f"Escrow {escrow_id} not found")

    # ── 2. Validate transition ────────────────────────────────────
    current = escrow.state
    if hasattr(current, "value"):
        current = current.value

    allowed = VALID_TRANSITIONS.get(current, [])
    if new_state not in allowed:
        raise InvalidTransitionError(
            f"{current} → {new_state} is not a valid transition"
        )

    # ── 3. Append-only event log (written BEFORE state update) ────
    event = EscrowEvent(
        escrow_id=escrow_id,
        from_state=current,
        to_state=new_state,
        actor_id=actor_id,
        actor_type=actor_type,
        trigger=trigger,
        meta=meta or {},
    )
    db.add(event)
    await db.flush()  # ensure event row exists before state change

    # ── 4. Update state ───────────────────────────────────────────
    escrow.state = new_state
    await db.commit()
    await db.refresh(escrow)

    # ── 5. Dispatch async notification ────────────────────────────
    try:
        from app.tasks.escrow import dispatch_escrow_notifications
        dispatch_escrow_notifications.delay(escrow_id, new_state)
    except Exception:
        logger.warning(
            "Failed to dispatch escrow notification for %s → %s",
            escrow_id, new_state,
        )

    return escrow
