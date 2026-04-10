"""
Tests for Escrow FSM — SDD §3.3, PM-08.

12-state escrow state machine tests.

Covers:
  1. test_payment_pending_to_funds_held
  2. test_funds_held_to_shipping_requested
  3. test_inspection_period_to_released
  4. test_inspection_period_to_disputed
  5. test_invalid_transition_released_to_any (InvalidTransitionError)
  6. test_invalid_transition_skips_state (payment_pending -> in_transit)
  7. test_concurrent_transition_raises_lock_error (asyncio.gather)
  8. test_event_inserted_before_state_update (check DB event count)
  9. test_deadlines_set_correctly_per_state
 10. test_terminal_state_cannot_transition (all 4 terminal states)

SQLite notes:
  - Escrow model uses ARRAY(Text) / JSONB which SQLite doesn't support.
    We monkey-patch column types to Text before create_all, then restore.
  - SQLite ignores FOR UPDATE NOWAIT; lock contention is tested by
    mocking the OperationalError that PostgreSQL would raise.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.escrow.models import (
    Escrow,
    EscrowEvent,
    VALID_TRANSITIONS,
    TERMINAL_STATES,
)


# ── Fixture: SQLite-compatible escrow tables ──────────────────────

def _register_sqlite_functions(dbapi_conn, connection_record):
    import uuid as _uuid
    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(_uuid.uuid4()))
    dbapi_conn.create_function("now", 0, lambda: "2026-04-07T00:00:00")


@pytest.fixture
async def escrow_db():
    """Async SQLite session with escrow tables.

    Monkey-patches ARRAY/JSONB columns -> Text for SQLite DDL,
    then restores original types so production code is unaffected.
    Also creates User + UserKycDocument + RefreshToken tables so
    SQLAlchemy relationship configuration doesn't fail.
    """
    from sqlalchemy import event
    from app.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)

    # Save original types, swap to Text for SQLite create_all
    # (ARRAY/JSONB not supported in SQLite)
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
                tables=[
                    Escrow.__table__,
                    EscrowEvent.__table__,
                ],
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

async def _insert_escrow(db: AsyncSession, state: str = "payment_pending", **overrides) -> dict:
    """Insert an escrow via raw INSERT to avoid ORM mapper configuration
    issues with User.kyc_documents FK in SQLite tests."""
    from sqlalchemy import insert

    defaults = dict(
        id=str(uuid4()),
        auction_id=str(uuid4()),
        winner_id=str(uuid4()),
        seller_id=str(uuid4()),
        amount=500.0,
        currency="JOD",
        transition_count=0,
        retry_count=0,
    )
    defaults.update(overrides)
    defaults["state"] = state
    await db.execute(insert(Escrow.__table__).values(**defaults))
    await db.commit()
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
    sys.modules.pop("app.services.escrow.fsm", None)
    with _CELERY_PATCH:
        from app.services.escrow import fsm
    return fsm


# ═══════════════════════════════════════════════════════════════════
#  1. test_payment_pending_to_funds_held
# ═══════════════════════════════════════════════════════════════════

class TestPaymentPendingToFundsHeld:

    @pytest.mark.asyncio
    async def test_payment_pending_to_funds_held(self, escrow_db):
        """payment_pending -> funds_held on payment capture."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="payment_pending")
        escrow = await fsm.transition_escrow(
            row["id"], "funds_held", row["winner_id"],
            "webhook", "webhook.payment_captured", {}, escrow_db,
        )
        assert escrow.state == "funds_held"
        events = await _get_events(escrow_db, row["id"])
        assert len(events) == 1
        assert events[0]["from_state"] == "payment_pending"
        assert events[0]["to_state"] == "funds_held"


# ═══════════════════════════════════════════════════════════════════
#  2. test_funds_held_to_shipping_requested
# ═══════════════════════════════════════════════════════════════════

class TestFundsHeldToShippingRequested:

    @pytest.mark.asyncio
    async def test_funds_held_to_shipping_requested(self, escrow_db):
        """funds_held -> shipping_requested after payment confirmed."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="funds_held")
        escrow = await fsm.transition_escrow(
            row["id"], "shipping_requested", row["seller_id"],
            "system", "system.funds_confirmed", {}, escrow_db,
        )
        assert escrow.state == "shipping_requested"


# ═══════════════════════════════════════════════════════════════════
#  3. test_inspection_period_to_released
# ═══════════════════════════════════════════════════════════════════

class TestInspectionPeriodToReleased:

    @pytest.mark.asyncio
    async def test_inspection_period_to_released(self, escrow_db):
        """inspection_period -> released on buyer confirmation."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="inspection_period")
        escrow = await fsm.transition_escrow(
            row["id"], "released", row["winner_id"],
            "buyer", "buyer.confirm_receipt", {}, escrow_db,
        )
        assert escrow.state == "released"


# ═══════════════════════════════════════════════════════════════════
#  4. test_inspection_period_to_disputed
# ═══════════════════════════════════════════════════════════════════

class TestInspectionPeriodToDisputed:

    @pytest.mark.asyncio
    async def test_inspection_period_to_disputed(self, escrow_db):
        """inspection_period -> disputed when buyer files dispute."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="inspection_period")
        escrow = await fsm.transition_escrow(
            row["id"], "disputed", row["winner_id"],
            "buyer", "buyer.file_dispute",
            {"reason": "Item not as described"}, escrow_db,
        )
        assert escrow.state == "disputed"


# ═══════════════════════════════════════════════════════════════════
#  5. test_invalid_transition_released_to_any
# ═══════════════════════════════════════════════════════════════════

class TestInvalidTransitionReleasedToAny:

    @pytest.mark.asyncio
    async def test_invalid_transition_released_to_any(self, escrow_db):
        """released is terminal — cannot transition to any state."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="released")
        for target in VALID_TRANSITIONS.keys():
            with pytest.raises(fsm.InvalidTransitionError):
                await fsm.transition_escrow(
                    row["id"], target, str(uuid4()),
                    "system", "attempt", {}, escrow_db,
                )


# ═══════════════════════════════════════════════════════════════════
#  6. test_invalid_transition_skips_state
# ═══════════════════════════════════════════════════════════════════

class TestInvalidTransitionSkipsState:

    @pytest.mark.asyncio
    async def test_invalid_transition_skips_state(self, escrow_db):
        """payment_pending -> in_transit skips multiple states — rejected."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="payment_pending")
        with pytest.raises(fsm.InvalidTransitionError, match="Cannot transition"):
            await fsm.transition_escrow(
                row["id"], "in_transit", str(uuid4()),
                "system", "skip.attempt", {}, escrow_db,
            )


# ═══════════════════════════════════════════════════════════════════
#  7. test_concurrent_transition_raises_lock_error
# ═══════════════════════════════════════════════════════════════════

class TestConcurrentTransitionRaisesLockError:

    @pytest.mark.asyncio
    async def test_concurrent_transition_raises_lock_error(self, escrow_db):
        """Simulate PostgreSQL 55P03 lock error — raises EscrowLockError.

        Since SQLite doesn't support FOR UPDATE NOWAIT, we simulate by
        patching db.execute to raise OperationalError.
        """
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="payment_pending")

        from sqlalchemy.exc import OperationalError

        original_execute = escrow_db.execute

        async def mock_execute(stmt, *args, **kwargs):
            stmt_str = str(stmt)
            if "FOR UPDATE" in stmt_str:
                raise OperationalError(
                    "could not obtain lock on row",
                    params=None,
                    orig=Exception("55P03"),
                )
            return await original_execute(stmt, *args, **kwargs)

        with patch.object(escrow_db, "execute", side_effect=mock_execute):
            with pytest.raises(fsm.EscrowLockError, match="locked by concurrent"):
                await fsm.transition_escrow(
                    row["id"], "funds_held", row["winner_id"],
                    "webhook", "webhook.payment_captured", {}, escrow_db,
                )


# ═══════════════════════════════════════════════════════════════════
#  8. test_event_inserted_before_state_update
# ═══════════════════════════════════════════════════════════════════

class TestEventInsertedBeforeStateUpdate:

    @pytest.mark.asyncio
    async def test_event_inserted_before_state_update(self, escrow_db):
        """Event is flushed BEFORE escrow.state is updated.

        Walk payment_pending -> funds_held -> shipping_requested and
        verify events are in correct order with correct from/to states.
        """
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="payment_pending")
        eid = row["id"]

        await fsm.transition_escrow(
            eid, "funds_held", row["winner_id"],
            "webhook", "webhook.payment_captured", {}, escrow_db,
        )
        await fsm.transition_escrow(
            eid, "shipping_requested", row["seller_id"],
            "system", "system.funds_confirmed", {}, escrow_db,
        )

        events = await _get_events(escrow_db, eid)
        assert len(events) == 2

        # First event: payment_pending -> funds_held
        assert events[0]["from_state"] == "payment_pending"
        assert events[0]["to_state"] == "funds_held"
        assert events[0]["trigger"] == "webhook.payment_captured"

        # Second event: funds_held -> shipping_requested
        assert events[1]["from_state"] == "funds_held"
        assert events[1]["to_state"] == "shipping_requested"
        assert events[1]["trigger"] == "system.funds_confirmed"

        # No event should exist for invalid transition
        with pytest.raises(fsm.InvalidTransitionError):
            await fsm.transition_escrow(
                eid, "released", str(uuid4()),
                "system", "skip", {}, escrow_db,
            )

        # Still only 2 events (invalid transition didn't create one)
        events = await _get_events(escrow_db, eid)
        assert len(events) == 2


# ═══════════════════════════════════════════════════════════════════
#  9. test_deadlines_set_correctly_per_state
# ═══════════════════════════════════════════════════════════════════

class TestDeadlinesSetCorrectlyPerState:

    @pytest.mark.asyncio
    async def test_deadlines_set_correctly_per_state(self, escrow_db):
        """Each state sets the correct deadline field."""
        fsm = _get_fsm()

        # payment_pending -> payment_deadline (24h)
        row1 = await _insert_escrow(escrow_db, state="payment_pending")
        # We need to test that the deadline is set, but payment_pending is the
        # starting state. Let's test via the transition that ENTERS payment_pending.
        # Since payment_pending is the initial state, test the other deadlines.

        # funds_held -> shipping_requested sets shipping_deadline (48h)
        row2 = await _insert_escrow(escrow_db, state="funds_held")
        escrow = await fsm.transition_escrow(
            row2["id"], "shipping_requested", row2["seller_id"],
            "system", "system.funds_confirmed", {}, escrow_db,
        )
        assert escrow.shipping_deadline is not None
        deadline = datetime.fromisoformat(escrow.shipping_deadline)
        # Should be ~48 hours from now (with some tolerance)
        now = datetime.utcnow()
        assert timedelta(hours=47) < (deadline - now) < timedelta(hours=49)

        # Walk to inspection_period for inspection_deadline (72h)
        row3 = await _insert_escrow(escrow_db, state="inspection_period")
        # Can't enter inspection_period via transition from payment_pending directly
        # so test by entering via delivered -> inspection_period
        row4 = await _insert_escrow(escrow_db, state="delivered")
        escrow = await fsm.transition_escrow(
            row4["id"], "inspection_period", row4["winner_id"],
            "system", "delivery.confirmed", {}, escrow_db,
        )
        assert escrow.inspection_deadline is not None
        deadline = datetime.fromisoformat(escrow.inspection_deadline)
        now = datetime.utcnow()
        assert timedelta(hours=71) < (deadline - now) < timedelta(hours=73)

        # disputed -> under_review sets release_deadline (144h)
        row5 = await _insert_escrow(escrow_db, state="disputed")
        escrow = await fsm.transition_escrow(
            row5["id"], "under_review", str(uuid4()),
            "admin", "admin.assign_mediator", {}, escrow_db,
        )
        assert escrow.release_deadline is not None
        deadline = datetime.fromisoformat(escrow.release_deadline)
        now = datetime.utcnow()
        assert timedelta(hours=143) < (deadline - now) < timedelta(hours=145)


# ═══════════════════════════════════════════════════════════════════
#  10. test_terminal_state_cannot_transition (all 4 terminal states)
# ═══════════════════════════════════════════════════════════════════

class TestTerminalStateCannotTransition:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("terminal", sorted(TERMINAL_STATES))
    async def test_terminal_state_cannot_transition(self, escrow_db, terminal):
        """All terminal states have empty allowed lists — nothing can follow."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state=terminal)
        with pytest.raises(fsm.InvalidTransitionError, match="Cannot transition"):
            await fsm.transition_escrow(
                row["id"], "payment_pending", str(uuid4()),
                "system", "should.fail", {}, escrow_db,
            )

    @pytest.mark.asyncio
    async def test_all_terminal_states_covered(self, escrow_db):
        """Verify TERMINAL_STATES matches states with empty transition lists."""
        empty_states = {s for s, allowed in VALID_TRANSITIONS.items() if not allowed}
        assert TERMINAL_STATES == empty_states


# ═══════════════════════════════════════════════════════════════════
#  BONUS: Full lifecycle paths
# ═══════════════════════════════════════════════════════════════════

class TestFullLifecycle:
    """Walk through complete happy path and dispute path."""

    @pytest.mark.asyncio
    async def test_happy_path_to_released(self, escrow_db):
        """payment_pending -> funds_held -> shipping_requested -> label_generated
        -> shipped -> in_transit -> delivered -> inspection_period -> released"""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="payment_pending")
        eid = row["id"]
        buyer = row["winner_id"]
        seller = row["seller_id"]

        path = [
            ("funds_held",         buyer,  "webhook", "webhook.payment_captured"),
            ("shipping_requested", seller, "system",  "system.funds_confirmed"),
            ("label_generated",    seller, "seller",  "seller.generate_label"),
            ("shipped",            seller, "seller",  "seller.mark_shipped"),
            ("in_transit",         seller, "system",  "carrier.scan_pickup"),
            ("delivered",          buyer,  "system",  "carrier.delivered"),
            ("inspection_period",  buyer,  "system",  "delivery.confirmed"),
            ("released",           buyer,  "buyer",   "buyer.confirm_receipt"),
        ]
        for new_state, actor, actor_type, trigger in path:
            escrow = await fsm.transition_escrow(
                eid, new_state, actor, actor_type, trigger, {}, escrow_db,
            )
        assert escrow.state == "released"
        events = await _get_events(escrow_db, eid)
        assert len(events) == 8

    @pytest.mark.asyncio
    async def test_dispute_path_to_resolved_refunded(self, escrow_db):
        """inspection_period -> disputed -> under_review -> resolved_refunded"""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="inspection_period")
        eid = row["id"]
        buyer = row["winner_id"]
        mediator = str(uuid4())

        await fsm.transition_escrow(
            eid, "disputed", buyer, "buyer", "buyer.file_dispute",
            {"reason": "Item damaged"}, escrow_db,
        )
        await fsm.transition_escrow(
            eid, "under_review", mediator, "admin", "admin.assign_mediator",
            {}, escrow_db,
        )
        escrow = await fsm.transition_escrow(
            eid, "resolved_refunded", mediator, "admin", "admin.refund",
            {"refund_amount": 500.0}, escrow_db,
        )
        assert escrow.state == "resolved_refunded"
        events = await _get_events(escrow_db, eid)
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_dispute_path_to_resolved_split(self, escrow_db):
        """under_review -> resolved_split (50/50 split)"""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="under_review")
        escrow = await fsm.transition_escrow(
            row["id"], "resolved_split", str(uuid4()),
            "admin", "admin.split",
            {"seller_pct": 50, "buyer_pct": 50}, escrow_db,
        )
        assert escrow.state == "resolved_split"

    @pytest.mark.asyncio
    async def test_cancellation_from_funds_held(self, escrow_db):
        """funds_held -> cancelled"""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="funds_held")
        escrow = await fsm.transition_escrow(
            row["id"], "cancelled", row["winner_id"],
            "system", "deadline.expired", {}, escrow_db,
        )
        assert escrow.state == "cancelled"


# ═══════════════════════════════════════════════════════════════════
#  Notification dispatch
# ═══════════════════════════════════════════════════════════════════

class TestNotificationDispatch:
    """Verify dispatch_escrow_notifications.delay() is called after commit."""

    @pytest.mark.asyncio
    async def test_notification_dispatched_on_success(self, escrow_db):
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="payment_pending")

        mock_task = MagicMock()
        with patch.dict("sys.modules", {"app.tasks.escrow": mock_task}):
            await fsm.transition_escrow(
                row["id"], "funds_held", row["winner_id"],
                "webhook", "webhook.payment_captured", {"payment_id": "pay_123"},
                escrow_db,
            )
            mock_task.dispatch_escrow_notifications.delay.assert_called_once_with(
                escrow_id=row["id"],
                from_state="payment_pending",
                to_state="funds_held",
                trigger="webhook.payment_captured",
                metadata={"payment_id": "pay_123"},
            )

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_rollback(self, escrow_db):
        """If notification dispatch fails, the transition should still succeed."""
        fsm = _get_fsm()
        row = await _insert_escrow(escrow_db, state="payment_pending")

        mock_task = MagicMock()
        mock_task.dispatch_escrow_notifications.delay.side_effect = ConnectionError("broker down")
        with patch.dict("sys.modules", {"app.tasks.escrow": mock_task}):
            escrow = await fsm.transition_escrow(
                row["id"], "funds_held", row["winner_id"],
                "webhook", "webhook.payment_captured", {}, escrow_db,
            )
            assert escrow.state == "funds_held"


# ═══════════════════════════════════════════════════════════════════
#  Nonexistent escrow
# ═══════════════════════════════════════════════════════════════════

class TestNonexistentEscrow:

    @pytest.mark.asyncio
    async def test_nonexistent_escrow_raises_value_error(self, escrow_db):
        fsm = _get_fsm()
        with pytest.raises(ValueError, match="not found"):
            await fsm.transition_escrow(
                str(uuid4()), "funds_held", str(uuid4()),
                "system", "ghost", {}, escrow_db,
            )
