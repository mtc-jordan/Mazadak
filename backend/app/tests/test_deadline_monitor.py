"""
Tests for escrow deadline monitor — app/services/escrow/deadline_monitor.py.

8 tests (mock datetime.utcnow() for time travel):
  1. test_payment_deadline_triggers_cancellation
  2. test_shipping_deadline_triggers_dispute_and_strike
  3. test_inspection_deadline_triggers_release_and_payout
  4. test_under_review_72h_notifies_mediator
  5. test_under_review_120h_proposes_split
  6. test_under_review_144h_auto_split_executes
  7. test_grace_period_respected
  8. test_idempotency_repeated_run_does_not_double_transition
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import JSON, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.escrow.models import Escrow, EscrowEvent


# ── Time control ──────────────────────────────────────────────────

T0 = datetime(2026, 4, 8, 12, 0, 0)  # naive UTC — matches utcnow()


# ── SQLite fixture ────────────────────────────────────────────────

def _register_sqlite_functions(dbapi_conn, connection_record):
    import uuid as _uuid
    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(_uuid.uuid4()))
    dbapi_conn.create_function("now", 0, lambda: "2026-04-08T00:00:00")


@pytest.fixture
async def deadline_db():
    from sqlalchemy import event
    from app.core.database import Base
    from app.services.auth.models import User, UserKycDocument, RefreshToken

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)

    # Patch ARRAY/JSONB for SQLite compatibility
    patch_targets = []
    # ARRAY columns → Text
    for col in [Escrow.__table__.c.evidence_s3_keys, Escrow.__table__.c.evidence_hashes]:
        patch_targets.append((col, col.type))
        col.type = Text()
    # JSONB columns → JSON (supports dict serialization on SQLite)
    for col in [
        EscrowEvent.__table__.c.meta,
        RefreshToken.__table__.c.device_info,
        User.__table__.c.fcm_tokens,
    ]:
        patch_targets.append((col, col.type))
        col.type = JSON()

    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                UserKycDocument.__table__,
                RefreshToken.__table__,
                Escrow.__table__,
                EscrowEvent.__table__,
            ],
        )

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    # Restore original column types after test
    for col, orig_type in patch_targets:
        col.type = orig_type
    await engine.dispose()


# ── Helpers ───────────────────────────────────────────────────────

async def _insert_escrow(db: AsyncSession, state: str, **overrides) -> dict:
    defaults = dict(
        id=str(uuid4()),
        auction_id=str(uuid4()),
        winner_id=str(uuid4()),
        seller_id=str(uuid4()),
        amount=500.0,
        currency="JOD",
        retry_count=0,
    )
    defaults.update(overrides)
    escrow = Escrow(**defaults, state=state)
    db.add(escrow)
    await db.commit()
    defaults["state"] = state
    return defaults


async def _insert_user(db: AsyncSession, user_id: str) -> None:
    from app.services.auth.models import User, UserRole, UserStatus, KYCStatus

    user = User(
        id=user_id,
        phone=f"+9627900{uuid4().hex[:5]}",
        full_name="Seller",
        full_name_ar="بائع",
        role=UserRole.SELLER,
        status=UserStatus.ACTIVE,
        kyc_status=KYCStatus.VERIFIED,
        ats_score=500,
        preferred_language="ar",
        strike_count=0,
        fcm_tokens=[],
        is_pro_seller=False,
    )
    db.add(user)
    await db.commit()


async def _get_events(db: AsyncSession, escrow_id: str) -> list[EscrowEvent]:
    result = await db.execute(
        select(EscrowEvent)
        .where(EscrowEvent.escrow_id == escrow_id)
        .order_by(EscrowEvent.created_at)
    )
    return list(result.scalars().all())


def _get_monitor():
    """Import deadline_monitor with Celery mocked out."""
    for mod in [
        "app.services.escrow.deadline_monitor",
        "app.services.escrow.fsm",
    ]:
        sys.modules.pop(mod, None)
    mock_tasks = MagicMock()
    with patch.dict("sys.modules", {
        "app.tasks.escrow": mock_tasks,
        "app.core.celery": MagicMock(),
        "celery": MagicMock(),
    }):
        from app.services.escrow import deadline_monitor
    return deadline_monitor, mock_tasks


# ═══════════════════════════════════════════════════════════════════
#  1. Payment deadline → cancellation
# ═══════════════════════════════════════════════════════════════════

class TestPaymentDeadlineCancellation:

    @pytest.mark.asyncio
    async def test_payment_deadline_triggers_cancellation(self, deadline_db):
        """Escrow with expired payment_deadline + grace → CANCELLED + void."""
        monitor, mock_tasks = _get_monitor()

        # Deadline was 1 hour ago — well past 15-min grace
        deadline = (T0 - timedelta(hours=1)).isoformat()
        row = await _insert_escrow(
            deadline_db, "payment_pending",
            payment_deadline=deadline,
            payment_intent_id="pay_intent_abc",
        )

        with patch.dict("sys.modules", {
            "app.tasks.escrow": mock_tasks,
            "app.core.celery": MagicMock(),
        }):
            with patch.object(monitor, "datetime") as mock_dt:
                mock_dt.utcnow.return_value = T0
                mock_dt.fromisoformat = datetime.fromisoformat
                await monitor.check_escrow_deadlines(deadline_db)

        # Escrow cancelled
        escrow = await deadline_db.get(Escrow, row["id"])
        assert escrow.state == "cancelled"

        # Audit event with correct trigger
        events = await _get_events(deadline_db, row["id"])
        assert any(e.trigger == "deadline.payment_expired" for e in events)

        # Checkout.com void dispatched
        mock_tasks.void_checkout_payment.delay.assert_called_once_with("pay_intent_abc")


# ═══════════════════════════════════════════════════════════════════
#  2. Shipping deadline → dispute + seller strike
# ═══════════════════════════════════════════════════════════════════

class TestShippingDeadlineDisputeAndStrike:

    @pytest.mark.asyncio
    async def test_shipping_deadline_triggers_dispute_and_strike(self, deadline_db):
        """Past shipping_deadline + grace → DISPUTED + seller strike + ATS."""
        from app.services.auth.models import User

        monitor, mock_tasks = _get_monitor()
        seller_id = str(uuid4())
        await _insert_user(deadline_db, seller_id)

        # Deadline 20 min ago — past 15-min grace
        deadline = (T0 - timedelta(minutes=20)).isoformat()
        row = await _insert_escrow(
            deadline_db, "shipping_requested",
            shipping_deadline=deadline,
            seller_id=seller_id,
        )

        with patch.dict("sys.modules", {
            "app.tasks.escrow": mock_tasks,
            "app.core.celery": MagicMock(),
        }):
            with patch.object(monitor, "datetime") as mock_dt:
                mock_dt.utcnow.return_value = T0
                mock_dt.fromisoformat = datetime.fromisoformat
                await monitor.check_escrow_deadlines(deadline_db)

        # Escrow disputed
        escrow = await deadline_db.get(Escrow, row["id"])
        assert escrow.state == "disputed"

        # Seller strike incremented
        result = await deadline_db.execute(select(User).where(User.id == seller_id))
        seller = result.scalar_one()
        assert seller.strike_count == 1

        # ATS update dispatched
        mock_tasks.update_ats_score.delay.assert_called_once_with(
            seller_id, "shipping_deadline_missed",
        )

        # Correct trigger
        events = await _get_events(deadline_db, row["id"])
        assert any(e.trigger == "deadline.shipping_expired" for e in events)


# ═══════════════════════════════════════════════════════════════════
#  3. Inspection deadline → release + payout
# ═══════════════════════════════════════════════════════════════════

class TestInspectionDeadlineReleaseAndPayout:

    @pytest.mark.asyncio
    async def test_inspection_deadline_triggers_release_and_payout(self, deadline_db):
        """Past inspection_deadline + grace → RELEASED + seller payout."""
        monitor, mock_tasks = _get_monitor()

        deadline = (T0 - timedelta(minutes=20)).isoformat()
        row = await _insert_escrow(
            deadline_db, "inspection_period",
            inspection_deadline=deadline,
        )

        with patch.dict("sys.modules", {
            "app.tasks.escrow": mock_tasks,
            "app.core.celery": MagicMock(),
        }):
            with patch.object(monitor, "datetime") as mock_dt:
                mock_dt.utcnow.return_value = T0
                mock_dt.fromisoformat = datetime.fromisoformat
                await monitor.check_escrow_deadlines(deadline_db)

        # Escrow released
        escrow = await deadline_db.get(Escrow, row["id"])
        assert escrow.state == "released"

        # Seller payout dispatched
        mock_tasks.trigger_seller_payout.delay.assert_called_once_with(row["id"])

        # Correct trigger
        events = await _get_events(deadline_db, row["id"])
        assert any(e.trigger == "deadline.inspection_expired" for e in events)


# ═══════════════════════════════════════════════════════════════════
#  4. Under review 72h → mediator SLA breach notification
# ═══════════════════════════════════════════════════════════════════

class TestUnderReview72hNotifiesMediator:

    @pytest.mark.asyncio
    async def test_under_review_72h_notifies_mediator(self, deadline_db):
        """Under review for 73h → mediator SLA breach dispatched."""
        monitor, mock_tasks = _get_monitor()

        entered = (T0 - timedelta(hours=73)).isoformat()
        row = await _insert_escrow(
            deadline_db, "under_review",
            last_transition_at=entered,
            mediator_id=str(uuid4()),
        )

        with patch.dict("sys.modules", {
            "app.tasks.escrow": mock_tasks,
            "app.core.celery": MagicMock(),
        }):
            with patch.object(monitor, "datetime") as mock_dt:
                mock_dt.utcnow.return_value = T0
                mock_dt.fromisoformat = datetime.fromisoformat
                await monitor.check_escrow_deadlines(deadline_db)

        # SLA breach notification dispatched
        mock_tasks.notify_mediator_sla_breach.delay.assert_called_once_with(row["id"])

        # State stays under_review (no transition)
        escrow = await deadline_db.get(Escrow, row["id"])
        assert escrow.state == "under_review"


# ═══════════════════════════════════════════════════════════════════
#  5. Under review 120h → propose split
# ═══════════════════════════════════════════════════════════════════

class TestUnderReview120hProposesSplit:

    @pytest.mark.asyncio
    async def test_under_review_120h_proposes_split(self, deadline_db):
        """Under review for 121h → propose 50/50 split to mediator."""
        monitor, mock_tasks = _get_monitor()

        mediator_id = str(uuid4())
        entered = (T0 - timedelta(hours=121)).isoformat()
        row = await _insert_escrow(
            deadline_db, "under_review",
            last_transition_at=entered,
            mediator_id=mediator_id,
        )

        with patch.dict("sys.modules", {
            "app.tasks.escrow": mock_tasks,
            "app.core.celery": MagicMock(),
        }):
            with patch.object(monitor, "datetime") as mock_dt:
                mock_dt.utcnow.return_value = T0
                mock_dt.fromisoformat = datetime.fromisoformat
                await monitor.check_escrow_deadlines(deadline_db)

        # Propose-split notification dispatched with mediator_id
        mock_tasks.notify_mediator_propose_split.delay.assert_called_once_with(
            mediator_id, row["id"],
        )

        # State stays under_review
        escrow = await deadline_db.get(Escrow, row["id"])
        assert escrow.state == "under_review"


# ═══════════════════════════════════════════════════════════════════
#  6. Under review 144h → auto-split execution
# ═══════════════════════════════════════════════════════════════════

class TestUnderReview144hAutoSplitExecutes:

    @pytest.mark.asyncio
    async def test_under_review_144h_auto_split_executes(self, deadline_db):
        """Under review for 145h → RESOLVED_SPLIT + split payout."""
        monitor, mock_tasks = _get_monitor()

        entered = (T0 - timedelta(hours=145)).isoformat()
        row = await _insert_escrow(
            deadline_db, "under_review",
            last_transition_at=entered,
            amount=1000.0,
            mediator_id=str(uuid4()),
        )

        with patch.dict("sys.modules", {
            "app.tasks.escrow": mock_tasks,
            "app.core.celery": MagicMock(),
        }):
            with patch.object(monitor, "datetime") as mock_dt:
                mock_dt.utcnow.return_value = T0
                mock_dt.fromisoformat = datetime.fromisoformat
                await monitor.check_escrow_deadlines(deadline_db)

        # Escrow resolved_split
        escrow = await deadline_db.get(Escrow, row["id"])
        assert escrow.state == "resolved_split"

        # Split payout dispatched
        mock_tasks.trigger_split_payout.delay.assert_called_once_with(row["id"])

        # FSM event with correct trigger
        events = await _get_events(deadline_db, row["id"])
        assert any(e.trigger == "deadline.auto_split" for e in events)


# ═══════════════════════════════════════════════════════════════════
#  7. Grace period respected (10 min overdue → NOT triggered)
# ═══════════════════════════════════════════════════════════════════

class TestGracePeriodRespected:

    @pytest.mark.asyncio
    async def test_grace_period_respected(self, deadline_db):
        """Deadline expired only 10 min ago (within 15-min grace) → no action."""
        monitor, _ = _get_monitor()

        # Payment deadline 10 min ago — within grace
        payment_dl = (T0 - timedelta(minutes=10)).isoformat()
        row_p = await _insert_escrow(
            deadline_db, "payment_pending", payment_deadline=payment_dl,
        )

        # Shipping deadline 10 min ago — within grace
        shipping_dl = (T0 - timedelta(minutes=10)).isoformat()
        row_s = await _insert_escrow(
            deadline_db, "shipping_requested", shipping_deadline=shipping_dl,
        )

        # Inspection deadline 10 min ago — within grace
        inspection_dl = (T0 - timedelta(minutes=10)).isoformat()
        row_i = await _insert_escrow(
            deadline_db, "inspection_period", inspection_deadline=inspection_dl,
        )

        with patch.object(monitor, "datetime") as mock_dt:
            mock_dt.utcnow.return_value = T0
            mock_dt.fromisoformat = datetime.fromisoformat
            await monitor.check_escrow_deadlines(deadline_db)

        # All states unchanged — grace period respected
        escrow_p = await deadline_db.get(Escrow, row_p["id"])
        assert escrow_p.state == "payment_pending"

        escrow_s = await deadline_db.get(Escrow, row_s["id"])
        assert escrow_s.state == "shipping_requested"

        escrow_i = await deadline_db.get(Escrow, row_i["id"])
        assert escrow_i.state == "inspection_period"

        # No events at all
        for row_id in [row_p["id"], row_s["id"], row_i["id"]]:
            events = await _get_events(deadline_db, row_id)
            assert len(events) == 0


# ═══════════════════════════════════════════════════════════════════
#  8. Idempotency — repeated run does not double-transition
# ═══════════════════════════════════════════════════════════════════

class TestIdempotencyRepeatedRun:

    @pytest.mark.asyncio
    async def test_idempotency_repeated_run_does_not_double_transition(self, deadline_db):
        """Running check twice → second run finds terminal state, no extra events."""
        monitor, mock_tasks = _get_monitor()

        deadline = (T0 - timedelta(hours=1)).isoformat()
        row = await _insert_escrow(
            deadline_db, "payment_pending", payment_deadline=deadline,
        )

        with patch.dict("sys.modules", {
            "app.tasks.escrow": mock_tasks,
            "app.core.celery": MagicMock(),
        }):
            with patch.object(monitor, "datetime") as mock_dt:
                mock_dt.utcnow.return_value = T0
                mock_dt.fromisoformat = datetime.fromisoformat

                # First run — cancels
                await monitor.check_escrow_deadlines(deadline_db)
                escrow = await deadline_db.get(Escrow, row["id"])
                assert escrow.state == "cancelled"

                events_after_first = await _get_events(deadline_db, row["id"])
                assert len(events_after_first) == 1

                # Second run — escrow is already cancelled (terminal),
                # not in payment_pending, so query won't match it
                await monitor.check_escrow_deadlines(deadline_db)

        events_after_second = await _get_events(deadline_db, row["id"])
        assert len(events_after_second) == 1  # no duplicate
