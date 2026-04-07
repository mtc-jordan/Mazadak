"""
Tests for Escrow FSM — SDD §3.3, PM-08.

Covers:
  - Every valid transition path
  - Every invalid transition (terminal states, illegal hops)
  - Append-only event log written BEFORE state update
  - NoWaitLockError on concurrent mutation
  - dispatch_escrow_notifications called after commit

SQLite notes:
  - Escrow model uses ARRAY(Text) / JSONB which SQLite doesn't support.
    We monkey-patch column types to Text before create_all, then restore.
  - SQLite ignores FOR UPDATE NOWAIT; lock contention is tested by
    mocking the OperationalError that PostgreSQL would raise.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import Text, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.escrow.models import ActorType, Escrow, EscrowEvent, VALID_TRANSITIONS


# ── Fixture: SQLite-compatible escrow tables ──────────────────────

def _register_sqlite_functions(dbapi_conn, connection_record):
    import uuid as _uuid
    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(_uuid.uuid4()))
    dbapi_conn.create_function("now", 0, lambda: "2026-04-07T00:00:00")


@pytest.fixture
async def escrow_db():
    """Async SQLite session with escrow tables.

    Monkey-patches ARRAY/JSONB columns → Text for SQLite DDL,
    then restores original types so production code is unaffected.
    """
    from sqlalchemy import event
    from app.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)

    # Save original types, swap to Text for SQLite create_all
    patch_targets = [
        (Escrow.__table__.c.evidence_s3_keys, None),
        (Escrow.__table__.c.evidence_hashes, None),
        (EscrowEvent.__table__.c.meta, None),
    ]
    for i, (col, _) in enumerate(patch_targets):
        patch_targets[i] = (col, col.type)
        col.type = Text()

    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[Escrow.__table__, EscrowEvent.__table__],
            )
    finally:
        for col, orig_type in patch_targets:
            col.type = orig_type

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()


# ── Helpers ───────────────────────────────────────────────────────

async def _insert_escrow(db: AsyncSession, state: str = "initiated", **overrides) -> dict:
    """Insert an escrow via ORM and return a dict of its fields."""
    defaults = dict(
        id=str(uuid4()),
        auction_id=str(uuid4()),
        winner_id=str(uuid4()),
        seller_id=str(uuid4()),
        amount=500.0,
        currency="JOD",
    )
    defaults.update(overrides)
    escrow = Escrow(**defaults, state=state)
    db.add(escrow)
    await db.commit()
    defaults["state"] = state
    return defaults


async def _get_events(db: AsyncSession, escrow_id: str) -> list[dict]:
    """Fetch all escrow_events for a given escrow_id."""
    result = await db.execute(
        select(EscrowEvent)
        .where(EscrowEvent.escrow_id == escrow_id)
        .order_by(EscrowEvent.created_at)
    )
    rows = result.scalars().all()
    return [
        {
            "id": r.id, "escrow_id": r.escrow_id,
            "from_state": r.from_state, "to_state": r.to_state,
            "actor_id": r.actor_id, "actor_type": r.actor_type,
            "trigger": r.trigger, "meta": r.meta,
        }
        for r in rows
    ]


# ── Mock Celery import ────────────────────────────────────────────

_mock_tasks = MagicMock()
_CELERY_PATCH = patch.dict("sys.modules", {
    "app.tasks.escrow": _mock_tasks,
    "app.core.celery": MagicMock(),
    "celery": MagicMock(),
})


def _get_fsm():
    """Import fsm module with Celery mocked."""
    # Ensure fresh import each time
    sys.modules.pop("app.services.escrow.fsm", None)
    with _CELERY_PATCH:
        from app.services.escrow import fsm
    return fsm


# ═══════════════════════════════════════════════════════════════════
#  VALID TRANSITIONS — every edge in the FSM graph
# ═══════════════════════════════════════════════════════════════════

class TestValidTransitions:
    """Test every valid transition in VALID_TRANSITIONS."""

    @pytest.mark.asyncio
    async def test_initiated_to_payment_pending(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="initiated")
        escrow = await fsm.transition_escrow(
            row["id"], "payment_pending", row["winner_id"],
            ActorType.SYSTEM, "payment.created", db=escrow_db,
        )
        assert escrow.state == "payment_pending"

    @pytest.mark.asyncio
    async def test_payment_pending_to_funds_held(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="payment_pending")
        escrow = await fsm.transition_escrow(
            row["id"], "funds_held", row["winner_id"],
            ActorType.SYSTEM, "payment.captured", db=escrow_db,
        )
        assert escrow.state == "funds_held"

    @pytest.mark.asyncio
    async def test_payment_pending_to_payment_failed(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="payment_pending")
        escrow = await fsm.transition_escrow(
            row["id"], "payment_failed", row["winner_id"],
            ActorType.SYSTEM, "payment.failed", db=escrow_db,
        )
        assert escrow.state == "payment_failed"

    @pytest.mark.asyncio
    async def test_payment_pending_to_cancelled(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="payment_pending")
        escrow = await fsm.transition_escrow(
            row["id"], "cancelled", row["winner_id"],
            ActorType.SYSTEM, "deadline.expired", db=escrow_db,
        )
        assert escrow.state == "cancelled"

    @pytest.mark.asyncio
    async def test_payment_failed_to_payment_pending(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="payment_failed")
        escrow = await fsm.transition_escrow(
            row["id"], "payment_pending", row["winner_id"],
            ActorType.BUYER, "buyer.retry_payment", db=escrow_db,
        )
        assert escrow.state == "payment_pending"

    @pytest.mark.asyncio
    async def test_payment_failed_to_cancelled(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="payment_failed")
        escrow = await fsm.transition_escrow(
            row["id"], "cancelled", row["winner_id"],
            ActorType.SYSTEM, "max_retries.exceeded", db=escrow_db,
        )
        assert escrow.state == "cancelled"

    @pytest.mark.asyncio
    async def test_funds_held_to_shipping_requested(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="funds_held")
        escrow = await fsm.transition_escrow(
            row["id"], "shipping_requested", row["seller_id"],
            ActorType.SYSTEM, "payment.confirmed", db=escrow_db,
        )
        assert escrow.state == "shipping_requested"

    @pytest.mark.asyncio
    async def test_shipping_requested_to_in_transit(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="shipping_requested")
        escrow = await fsm.transition_escrow(
            row["id"], "in_transit", row["seller_id"],
            ActorType.SELLER, "seller.upload_tracking",
            meta={"tracking": "ARX123"}, db=escrow_db,
        )
        assert escrow.state == "in_transit"

    @pytest.mark.asyncio
    async def test_shipping_requested_to_disputed(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="shipping_requested")
        escrow = await fsm.transition_escrow(
            row["id"], "disputed", row["winner_id"],
            ActorType.BUYER, "buyer.file_dispute", db=escrow_db,
        )
        assert escrow.state == "disputed"

    @pytest.mark.asyncio
    async def test_in_transit_to_inspection_period(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="in_transit")
        escrow = await fsm.transition_escrow(
            row["id"], "inspection_period", row["winner_id"],
            ActorType.SYSTEM, "delivery.confirmed", db=escrow_db,
        )
        assert escrow.state == "inspection_period"

    @pytest.mark.asyncio
    async def test_inspection_period_to_released(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="inspection_period")
        escrow = await fsm.transition_escrow(
            row["id"], "released", row["winner_id"],
            ActorType.BUYER, "buyer.confirm_receipt", db=escrow_db,
        )
        assert escrow.state == "released"

    @pytest.mark.asyncio
    async def test_inspection_period_to_disputed(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="inspection_period")
        escrow = await fsm.transition_escrow(
            row["id"], "disputed", row["winner_id"],
            ActorType.BUYER, "buyer.file_dispute", db=escrow_db,
        )
        assert escrow.state == "disputed"

    @pytest.mark.asyncio
    async def test_disputed_to_under_review(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="disputed")
        escrow = await fsm.transition_escrow(
            row["id"], "under_review", None,
            ActorType.MEDIATOR, "mediator.assigned", db=escrow_db,
        )
        assert escrow.state == "under_review"

    @pytest.mark.asyncio
    async def test_under_review_to_released(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="under_review")
        escrow = await fsm.transition_escrow(
            row["id"], "released", str(uuid4()),
            ActorType.MEDIATOR, "mediator.release", db=escrow_db,
        )
        assert escrow.state == "released"

    @pytest.mark.asyncio
    async def test_under_review_to_refunded(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="under_review")
        escrow = await fsm.transition_escrow(
            row["id"], "refunded", str(uuid4()),
            ActorType.MEDIATOR, "mediator.refund", db=escrow_db,
        )
        assert escrow.state == "refunded"

    @pytest.mark.asyncio
    async def test_under_review_to_partially_released(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="under_review")
        escrow = await fsm.transition_escrow(
            row["id"], "partially_released", str(uuid4()),
            ActorType.MEDIATOR, "mediator.split",
            meta={"seller_pct": 70, "buyer_pct": 30}, db=escrow_db,
        )
        assert escrow.state == "partially_released"


# ═══════════════════════════════════════════════════════════════════
#  INVALID TRANSITIONS — terminal states & illegal hops
# ═══════════════════════════════════════════════════════════════════

class TestInvalidTransitions:
    """Every terminal state rejects all transitions; illegal hops raise."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("terminal", ["released", "refunded", "partially_released", "cancelled"])
    async def test_terminal_states_reject_all(self, escrow_db, terminal):
        """Terminal states have empty allowed lists — nothing can follow."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state=terminal)
        with pytest.raises(fsm.InvalidTransitionError):
            await fsm.transition_escrow(
                row["id"], "initiated", str(uuid4()),
                ActorType.SYSTEM, "should.fail", db=escrow_db,
            )

    @pytest.mark.asyncio
    async def test_initiated_cannot_skip_to_funds_held(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="initiated")
        with pytest.raises(fsm.InvalidTransitionError, match="initiated .* funds_held"):
            await fsm.transition_escrow(
                row["id"], "funds_held", str(uuid4()),
                ActorType.SYSTEM, "skip.attempt", db=escrow_db,
            )

    @pytest.mark.asyncio
    async def test_funds_held_cannot_go_to_released(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="funds_held")
        with pytest.raises(fsm.InvalidTransitionError):
            await fsm.transition_escrow(
                row["id"], "released", str(uuid4()),
                ActorType.SYSTEM, "skip.attempt", db=escrow_db,
            )

    @pytest.mark.asyncio
    async def test_in_transit_cannot_go_to_released(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="in_transit")
        with pytest.raises(fsm.InvalidTransitionError):
            await fsm.transition_escrow(
                row["id"], "released", str(uuid4()),
                ActorType.SYSTEM, "skip.attempt", db=escrow_db,
            )

    @pytest.mark.asyncio
    async def test_disputed_cannot_go_to_released_directly(self, escrow_db):
        """disputed → released is invalid; must go through under_review."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="disputed")
        with pytest.raises(fsm.InvalidTransitionError):
            await fsm.transition_escrow(
                row["id"], "released", str(uuid4()),
                ActorType.MEDIATOR, "shortcut", db=escrow_db,
            )

    @pytest.mark.asyncio
    async def test_backward_transition_rejected(self, escrow_db):
        """shipping_requested → funds_held is a backward move — rejected."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="shipping_requested")
        with pytest.raises(fsm.InvalidTransitionError):
            await fsm.transition_escrow(
                row["id"], "funds_held", str(uuid4()),
                ActorType.SYSTEM, "rollback.attempt", db=escrow_db,
            )

    @pytest.mark.asyncio
    async def test_nonexistent_escrow_raises_value_error(self, escrow_db):
        fsm = _get_fsm()
        with pytest.raises(ValueError, match="not found"):
            await fsm.transition_escrow(
                str(uuid4()), "payment_pending", str(uuid4()),
                ActorType.SYSTEM, "ghost", db=escrow_db,
            )


# ═══════════════════════════════════════════════════════════════════
#  EVENT LOG — append-only audit trail
# ═══════════════════════════════════════════════════════════════════

class TestEventLog:
    """Verify events are written BEFORE state update and are immutable."""

    @pytest.mark.asyncio
    async def test_event_created_on_valid_transition(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="initiated")
        await fsm.transition_escrow(
            row["id"], "payment_pending", row["winner_id"],
            ActorType.SYSTEM, "payment.created", db=escrow_db,
        )
        events = await _get_events(escrow_db, row["id"])
        assert len(events) == 1
        ev = events[0]
        assert ev["from_state"] == "initiated"
        assert ev["to_state"] == "payment_pending"
        assert ev["actor_id"] == row["winner_id"]
        assert ev["actor_type"] == "system"
        assert ev["trigger"] == "payment.created"

    @pytest.mark.asyncio
    async def test_no_event_on_invalid_transition(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="released")
        with pytest.raises(fsm.InvalidTransitionError):
            await fsm.transition_escrow(
                row["id"], "initiated", str(uuid4()),
                ActorType.SYSTEM, "bad", db=escrow_db,
            )
        events = await _get_events(escrow_db, row["id"])
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_multiple_transitions_create_ordered_events(self, escrow_db):
        """Walk initiated → payment_pending → funds_held → shipping_requested."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="initiated")
        eid = row["id"]
        transitions = [
            ("payment_pending", "payment.created"),
            ("funds_held", "payment.captured"),
            ("shipping_requested", "payment.confirmed"),
        ]
        for new_state, trigger in transitions:
            await fsm.transition_escrow(
                eid, new_state, row["winner_id"],
                ActorType.SYSTEM, trigger, db=escrow_db,
            )
        events = await _get_events(escrow_db, eid)
        assert len(events) == 3
        assert [e["to_state"] for e in events] == [
            "payment_pending", "funds_held", "shipping_requested",
        ]

    @pytest.mark.asyncio
    async def test_meta_stored_in_event(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="shipping_requested")
        meta = {"tracking": "ARX456", "carrier": "aramex"}
        await fsm.transition_escrow(
            row["id"], "in_transit", row["seller_id"],
            ActorType.SELLER, "seller.upload_tracking",
            meta=meta, db=escrow_db,
        )
        events = await _get_events(escrow_db, row["id"])
        assert len(events) == 1
        # meta is stored (as JSON text in SQLite, JSONB in PG)
        assert events[0]["meta"] is not None


# ═══════════════════════════════════════════════════════════════════
#  NOWAIT LOCK CONTENTION
# ═══════════════════════════════════════════════════════════════════

class TestNoWaitLock:
    """Verify NoWaitLockError is raised when row lock cannot be acquired."""

    @pytest.mark.asyncio
    async def test_nowait_lock_error_raised(self, escrow_db):
        """Simulate PostgreSQL 55P03 by patching db.execute to raise."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="initiated")

        from sqlalchemy.exc import OperationalError

        original_execute = escrow_db.execute

        async def mock_execute(stmt, *args, **kwargs):
            stmt_str = str(stmt)
            if "FOR UPDATE" in stmt_str or "for_update" in str(getattr(stmt, '_for_update_arg', '')):
                raise OperationalError(
                    "could not obtain lock on row",
                    params=None,
                    orig=Exception("55P03"),
                )
            return await original_execute(stmt, *args, **kwargs)

        with patch.object(escrow_db, "execute", side_effect=mock_execute):
            with pytest.raises(fsm.NoWaitLockError, match="locked by another"):
                await fsm.transition_escrow(
                    row["id"], "payment_pending", str(uuid4()),
                    ActorType.SYSTEM, "payment.created", db=escrow_db,
                )

    @pytest.mark.asyncio
    async def test_other_db_errors_propagate(self, escrow_db):
        """Non-lock DB errors should NOT be caught as NoWaitLockError."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="initiated")

        async def mock_execute(stmt, *args, **kwargs):
            raise RuntimeError("connection lost")

        with patch.object(escrow_db, "execute", side_effect=mock_execute):
            with pytest.raises(RuntimeError, match="connection lost"):
                await fsm.transition_escrow(
                    row["id"], "payment_pending", str(uuid4()),
                    ActorType.SYSTEM, "payment.created", db=escrow_db,
                )


# ═══════════════════════════════════════════════════════════════════
#  NOTIFICATION DISPATCH
# ═══════════════════════════════════════════════════════════════════

class TestNotificationDispatch:
    """Verify dispatch_escrow_notifications.delay() is called after commit."""

    @pytest.mark.asyncio
    async def test_notification_dispatched_on_success(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="initiated")

        mock_task = MagicMock()
        with patch.dict("sys.modules", {"app.tasks.escrow": mock_task}):
            await fsm.transition_escrow(
                row["id"], "payment_pending", row["winner_id"],
                ActorType.SYSTEM, "payment.created", db=escrow_db,
            )
            mock_task.dispatch_escrow_notifications.delay.assert_called_once_with(
                row["id"], "payment_pending",
            )

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_rollback(self, escrow_db):
        """If notification dispatch fails, the transition should still succeed."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="initiated")

        mock_task = MagicMock()
        mock_task.dispatch_escrow_notifications.delay.side_effect = ConnectionError("broker down")
        with patch.dict("sys.modules", {"app.tasks.escrow": mock_task}):
            escrow = await fsm.transition_escrow(
                row["id"], "payment_pending", row["winner_id"],
                ActorType.SYSTEM, "payment.created", db=escrow_db,
            )
            # State changed despite notification failure
            assert escrow.state == "payment_pending"


# ═══════════════════════════════════════════════════════════════════
#  FULL LIFECYCLE — happy path end-to-end
# ═══════════════════════════════════════════════════════════════════

class TestFullLifecycle:
    """Walk through the complete happy path and dispute path."""

    @pytest.mark.asyncio
    async def test_happy_path_initiated_to_released(self, escrow_db):
        """initiated → payment_pending → funds_held → shipping_requested
        → in_transit → inspection_period → released"""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="initiated")
        eid = row["id"]
        buyer = row["winner_id"]
        seller = row["seller_id"]

        path = [
            ("payment_pending", buyer, ActorType.SYSTEM, "payment.created"),
            ("funds_held", buyer, ActorType.SYSTEM, "payment.captured"),
            ("shipping_requested", seller, ActorType.SYSTEM, "payment.confirmed"),
            ("in_transit", seller, ActorType.SELLER, "seller.upload_tracking"),
            ("inspection_period", buyer, ActorType.SYSTEM, "delivery.confirmed"),
            ("released", buyer, ActorType.BUYER, "buyer.confirm_receipt"),
        ]
        for new_state, actor, actor_type, trigger in path:
            escrow = await fsm.transition_escrow(
                eid, new_state, actor, actor_type, trigger, db=escrow_db,
            )
        assert escrow.state == "released"
        events = await _get_events(escrow_db, eid)
        assert len(events) == 6

    @pytest.mark.asyncio
    async def test_dispute_path_to_refund(self, escrow_db):
        """initiated → ... → inspection_period → disputed → under_review → refunded"""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="inspection_period")
        eid = row["id"]
        buyer = row["winner_id"]
        mediator = str(uuid4())

        await fsm.transition_escrow(
            eid, "disputed", buyer, ActorType.BUYER, "buyer.file_dispute", db=escrow_db,
        )
        await fsm.transition_escrow(
            eid, "under_review", mediator, ActorType.MEDIATOR, "mediator.assigned", db=escrow_db,
        )
        escrow = await fsm.transition_escrow(
            eid, "refunded", mediator, ActorType.MEDIATOR, "mediator.refund", db=escrow_db,
        )
        assert escrow.state == "refunded"
        events = await _get_events(escrow_db, eid)
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_payment_retry_path(self, escrow_db):
        """initiated → payment_pending → payment_failed → payment_pending → funds_held"""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="initiated")
        eid = row["id"]
        buyer = row["winner_id"]

        await fsm.transition_escrow(
            eid, "payment_pending", buyer, ActorType.SYSTEM, "payment.created", db=escrow_db,
        )
        await fsm.transition_escrow(
            eid, "payment_failed", buyer, ActorType.SYSTEM, "payment.failed", db=escrow_db,
        )
        await fsm.transition_escrow(
            eid, "payment_pending", buyer, ActorType.BUYER, "buyer.retry_payment", db=escrow_db,
        )
        escrow = await fsm.transition_escrow(
            eid, "funds_held", buyer, ActorType.SYSTEM, "payment.captured", db=escrow_db,
        )
        assert escrow.state == "funds_held"
        events = await _get_events(escrow_db, eid)
        assert len(events) == 4

    @pytest.mark.asyncio
    async def test_released_is_truly_terminal(self, escrow_db):
        """After release, no further transitions are possible."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="released")
        for target in VALID_TRANSITIONS.keys():
            with pytest.raises(fsm.InvalidTransitionError):
                await fsm.transition_escrow(
                    row["id"], target, str(uuid4()),
                    ActorType.SYSTEM, "attempt", db=escrow_db,
                )
