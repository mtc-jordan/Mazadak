"""
Tests for escrow deadline monitoring — FR-ESC-019, PM-08.

6 deadline types, each with time-controlled tests:
  1. PAYMENT_PENDING past payment_deadline → CANCELLED
  2. SHIPPING_REQUESTED past shipping_deadline + 15 min → DISPUTED + seller strike
  3. INSPECTION_PERIOD past inspection_deadline + 15 min → RELEASED
  4. UNDER_REVIEW 72 h → escalate to admin
  5. UNDER_REVIEW 120 h → propose 50/50 split
  6. UNDER_REVIEW 144 h → auto-execute 50/50 (RESOLVED_SPLIT)

Time control: tests inject a fixed ``now`` via monkeypatch on
``datetime.now`` inside the deadlines module so no real delays occur.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import Integer, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.escrow.models import (
    ActorType,
    Escrow,
    EscrowEvent,
)


# ── SQLite fixture with escrow + users tables ────────────────────

def _register_sqlite_functions(dbapi_conn, connection_record):
    import uuid as _uuid
    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(_uuid.uuid4()))
    dbapi_conn.create_function("now", 0, lambda: "2026-04-07T00:00:00")


@pytest.fixture
async def escrow_db():
    from sqlalchemy import event, Column, String, Boolean, Table, MetaData
    from app.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)

    # Patch ARRAY/JSONB → Text for SQLite
    from app.services.auth.models import RefreshToken as _RT
    patch_targets = [
        (Escrow.__table__.c.evidence_s3_keys, None),
        (Escrow.__table__.c.evidence_hashes, None),
        (EscrowEvent.__table__.c.meta, None),
        (_RT.__table__.c.device_info, None),
    ]
    for i, (col, _) in enumerate(patch_targets):
        patch_targets[i] = (col, col.type)
        col.type = Text()

    try:
        # Also create User + related tables for seller strike tests
        from app.services.auth.models import User, UserKycDocument, RefreshToken
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
    finally:
        for col, orig_type in patch_targets:
            col.type = orig_type

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


# ── Helpers ───────────────────────────────────────────────────────

T0 = datetime(2026, 4, 7, 12, 0, 0, tzinfo=timezone.utc)


async def _insert_escrow(
    db: AsyncSession, state: str, **overrides,
) -> dict:
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


async def _insert_user(db: AsyncSession, user_id: str) -> None:
    from app.services.auth.models import User, UserRole, UserStatus, KYCStatus

    user = User(
        id=user_id,
        phone=f"+9627900{uuid4().hex[:5]}",
        full_name_ar="بائع",
        full_name="Seller",
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


async def _insert_event(
    db: AsyncSession,
    escrow_id: str,
    from_state: str,
    to_state: str,
    trigger: str,
    created_at: datetime | None = None,
) -> None:
    """Insert an escrow event with a controlled created_at timestamp."""
    ev = EscrowEvent(
        id=str(uuid4()),
        escrow_id=escrow_id,
        from_state=from_state,
        to_state=to_state,
        actor_id=None,
        actor_type=ActorType.SYSTEM.value,
        trigger=trigger,
        meta={},
    )
    # Set created_at directly on the object to bypass server_default
    # and avoid identity-map staleness from raw SQL UPDATE.
    if created_at:
        ev.created_at = created_at
    db.add(ev)
    await db.commit()


async def _get_events(db: AsyncSession, escrow_id: str) -> list[EscrowEvent]:
    result = await db.execute(
        select(EscrowEvent)
        .where(EscrowEvent.escrow_id == escrow_id)
        .order_by(EscrowEvent.created_at)
    )
    return list(result.scalars().all())


def _get_deadlines_module():
    """Import deadlines with Celery mocked out."""
    for mod in [
        "app.services.escrow.deadlines",
        "app.services.escrow.fsm",
    ]:
        sys.modules.pop(mod, None)
    mock_tasks = MagicMock()
    with patch.dict("sys.modules", {
        "app.tasks.escrow": mock_tasks,
        "app.core.celery": MagicMock(),
        "celery": MagicMock(),
    }):
        from app.services.escrow import deadlines
    return deadlines, mock_tasks


# ═══════════════════════════════════════════════════════════════════
#  1. PAYMENT_PENDING → CANCELLED
# ═══════════════════════════════════════════════════════════════════

class TestPaymentDeadline:

    @pytest.mark.asyncio
    async def test_expired_payment_cancelled(self, escrow_db):
        """Escrow with expired payment_deadline is auto-cancelled."""
        dl, _ = _get_deadlines_module()
        past = (T0 - timedelta(hours=1))
        row = await _insert_escrow(
            escrow_db, "payment_pending", payment_deadline=past,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["payment_expired"] == 1
        escrow = await escrow_db.get(Escrow, row["id"])
        assert escrow.state == "cancelled"

    @pytest.mark.asyncio
    async def test_unexpired_payment_untouched(self, escrow_db):
        """Escrow with future payment_deadline is not touched."""
        dl, _ = _get_deadlines_module()
        future = (T0 + timedelta(hours=2))
        row = await _insert_escrow(
            escrow_db, "payment_pending", payment_deadline=future,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["payment_expired"] == 0
        escrow = await escrow_db.get(Escrow, row["id"])
        assert escrow.state == "payment_pending"

    @pytest.mark.asyncio
    async def test_payment_no_deadline_skipped(self, escrow_db):
        """Escrow with no payment_deadline set is skipped."""
        dl, _ = _get_deadlines_module()
        await _insert_escrow(escrow_db, "payment_pending")

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["payment_expired"] == 0

    @pytest.mark.asyncio
    async def test_payment_void_dispatched(self, escrow_db):
        """Voiding Checkout.com intent is dispatched after cancellation."""
        dl, mock_tasks = _get_deadlines_module()
        past = (T0 - timedelta(hours=1))
        row = await _insert_escrow(
            escrow_db, "payment_pending",
            payment_deadline=past, payment_intent_id="pay_abc123",
        )

        with patch.dict("sys.modules", {
            "app.tasks.escrow": mock_tasks,
            "app.core.celery": MagicMock(),
        }):
            with patch.object(dl, "datetime") as mock_dt:
                mock_dt.now.return_value = T0
    
                await dl.check_escrow_deadlines(escrow_db)

        mock_tasks.void_payment_intent.delay.assert_called_once_with("pay_abc123")

    @pytest.mark.asyncio
    async def test_payment_event_log_written(self, escrow_db):
        dl, _ = _get_deadlines_module()
        past = (T0 - timedelta(hours=1))
        row = await _insert_escrow(
            escrow_db, "payment_pending", payment_deadline=past,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            await dl.check_escrow_deadlines(escrow_db)

        events = await _get_events(escrow_db, row["id"])
        assert len(events) == 1
        assert events[0].trigger == "system.payment_deadline_expired"
        assert events[0].to_state == "cancelled"


# ═══════════════════════════════════════════════════════════════════
#  2. SHIPPING_REQUESTED → DISPUTED + seller strike
# ═══════════════════════════════════════════════════════════════════

class TestShippingDeadline:

    @pytest.mark.asyncio
    async def test_expired_shipping_disputed(self, escrow_db):
        """Past shipping_deadline + 15 min grace → DISPUTED."""
        dl, _ = _get_deadlines_module()
        seller_id = str(uuid4())
        await _insert_user(escrow_db, seller_id)
        # Deadline was 20 min ago — past the 15-min grace
        past = (T0 - timedelta(minutes=20))
        row = await _insert_escrow(
            escrow_db, "shipping_requested",
            shipping_deadline=past, seller_id=seller_id,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["shipping_expired"] == 1
        escrow = await escrow_db.get(Escrow, row["id"])
        assert escrow.state == "disputed"

    @pytest.mark.asyncio
    async def test_shipping_within_grace_untouched(self, escrow_db):
        """Deadline expired but still within 15-min grace → not processed."""
        dl, _ = _get_deadlines_module()
        # Deadline was 10 min ago — within 15-min grace
        past = (T0 - timedelta(minutes=10))
        await _insert_escrow(
            escrow_db, "shipping_requested", shipping_deadline=past,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["shipping_expired"] == 0

    @pytest.mark.asyncio
    async def test_seller_strike_incremented(self, escrow_db):
        """Seller gets +1 strike_count on shipping no-show."""
        from app.services.auth.models import User

        dl, _ = _get_deadlines_module()
        seller_id = str(uuid4())
        await _insert_user(escrow_db, seller_id)
        past = (T0 - timedelta(hours=1))
        await _insert_escrow(
            escrow_db, "shipping_requested",
            shipping_deadline=past, seller_id=seller_id,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            await dl.check_escrow_deadlines(escrow_db)

        result = await escrow_db.execute(select(User).where(User.id == seller_id))
        seller = result.scalar_one()
        assert seller.strike_count == 1

    @pytest.mark.asyncio
    async def test_shipping_event_trigger(self, escrow_db):
        dl, _ = _get_deadlines_module()
        seller_id = str(uuid4())
        await _insert_user(escrow_db, seller_id)
        past = (T0 - timedelta(hours=1))
        row = await _insert_escrow(
            escrow_db, "shipping_requested",
            shipping_deadline=past, seller_id=seller_id,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            await dl.check_escrow_deadlines(escrow_db)

        events = await _get_events(escrow_db, row["id"])
        assert any(e.trigger == "system.seller_no_show_48h" for e in events)


# ═══════════════════════════════════════════════════════════════════
#  3. INSPECTION_PERIOD → RELEASED (auto-release)
# ═══════════════════════════════════════════════════════════════════

class TestInspectionDeadline:

    @pytest.mark.asyncio
    async def test_expired_inspection_released(self, escrow_db):
        """Past inspection_deadline + 15 min grace → RELEASED."""
        dl, _ = _get_deadlines_module()
        past = (T0 - timedelta(minutes=20))
        row = await _insert_escrow(
            escrow_db, "inspection_period", inspection_deadline=past,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["inspection_expired"] == 1
        escrow = await escrow_db.get(Escrow, row["id"])
        assert escrow.state == "released"

    @pytest.mark.asyncio
    async def test_inspection_within_grace_untouched(self, escrow_db):
        dl, _ = _get_deadlines_module()
        past = (T0 - timedelta(minutes=10))
        await _insert_escrow(
            escrow_db, "inspection_period", inspection_deadline=past,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["inspection_expired"] == 0

    @pytest.mark.asyncio
    async def test_inspection_event_trigger(self, escrow_db):
        dl, _ = _get_deadlines_module()
        past = (T0 - timedelta(hours=1))
        row = await _insert_escrow(
            escrow_db, "inspection_period", inspection_deadline=past,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            await dl.check_escrow_deadlines(escrow_db)

        events = await _get_events(escrow_db, row["id"])
        assert events[-1].trigger == "system.inspection_auto_release"
        assert events[-1].to_state == "released"


# ═══════════════════════════════════════════════════════════════════
#  4. UNDER_REVIEW 72 h → escalate to admin
# ═══════════════════════════════════════════════════════════════════

class TestMediatorSLA72h:

    @pytest.mark.asyncio
    async def test_72h_escalation(self, escrow_db):
        """Under review for 73 h → escalation event inserted."""
        dl, _ = _get_deadlines_module()
        entered = T0 - timedelta(hours=73)
        row = await _insert_escrow(escrow_db, "under_review")
        await _insert_event(
            escrow_db, row["id"], "disputed", "under_review",
            "mediator.assigned", created_at=entered,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["mediator_escalated"] == 1
        events = await _get_events(escrow_db, row["id"])
        triggers = [e.trigger for e in events]
        assert "system.mediator_sla_72h_escalation" in triggers

    @pytest.mark.asyncio
    async def test_72h_not_reached_skipped(self, escrow_db):
        """Under review for only 50 h → no escalation."""
        dl, _ = _get_deadlines_module()
        entered = T0 - timedelta(hours=50)
        row = await _insert_escrow(escrow_db, "under_review")
        await _insert_event(
            escrow_db, row["id"], "disputed", "under_review",
            "mediator.assigned", created_at=entered,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["mediator_escalated"] == 0

    @pytest.mark.asyncio
    async def test_72h_idempotent(self, escrow_db):
        """Second scan after 72 h escalation → no duplicate event."""
        dl, _ = _get_deadlines_module()
        entered = T0 - timedelta(hours=73)
        row = await _insert_escrow(escrow_db, "under_review")
        await _insert_event(
            escrow_db, row["id"], "disputed", "under_review",
            "mediator.assigned", created_at=entered,
        )
        # Already escalated
        await _insert_event(
            escrow_db, row["id"], "under_review", "under_review",
            "system.mediator_sla_72h_escalation",
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["mediator_escalated"] == 0


# ═══════════════════════════════════════════════════════════════════
#  5. UNDER_REVIEW 120 h → propose 50/50
# ═══════════════════════════════════════════════════════════════════

class TestMediatorSLA120h:

    @pytest.mark.asyncio
    async def test_120h_proposal(self, escrow_db):
        """Under review for 121 h → 50/50 proposal event."""
        dl, _ = _get_deadlines_module()
        entered = T0 - timedelta(hours=121)
        row = await _insert_escrow(escrow_db, "under_review")
        await _insert_event(
            escrow_db, row["id"], "disputed", "under_review",
            "mediator.assigned", created_at=entered,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["mediator_proposed"] == 1
        # State stays under_review — proposal is advisory, not a transition
        escrow = await escrow_db.get(Escrow, row["id"])
        assert escrow.state == "under_review"

        events = await _get_events(escrow_db, row["id"])
        triggers = [e.trigger for e in events]
        assert "system.mediator_sla_120h_propose" in triggers

    @pytest.mark.asyncio
    async def test_120h_idempotent(self, escrow_db):
        dl, _ = _get_deadlines_module()
        entered = T0 - timedelta(hours=121)
        row = await _insert_escrow(escrow_db, "under_review")
        await _insert_event(
            escrow_db, row["id"], "disputed", "under_review",
            "mediator.assigned", created_at=entered,
        )
        await _insert_event(
            escrow_db, row["id"], "under_review", "under_review",
            "system.mediator_sla_120h_propose",
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["mediator_proposed"] == 0


# ═══════════════════════════════════════════════════════════════════
#  6. UNDER_REVIEW 144 h → auto-execute 50/50
# ═══════════════════════════════════════════════════════════════════

class TestMediatorSLA144h:

    @pytest.mark.asyncio
    async def test_144h_auto_execute(self, escrow_db):
        """Under review for 145 h → RESOLVED_SPLIT + seller_amount set."""
        dl, _ = _get_deadlines_module()
        entered = T0 - timedelta(hours=145)
        row = await _insert_escrow(escrow_db, "under_review", amount=1000.0)
        await _insert_event(
            escrow_db, row["id"], "disputed", "under_review",
            "mediator.assigned", created_at=entered,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["mediator_auto_executed"] == 1
        escrow = await escrow_db.get(Escrow, row["id"])
        assert escrow.state == "resolved_split"
        assert float(escrow.seller_amount) == 500.0

    @pytest.mark.asyncio
    async def test_144h_event_trigger(self, escrow_db):
        dl, _ = _get_deadlines_module()
        entered = T0 - timedelta(hours=145)
        row = await _insert_escrow(escrow_db, "under_review")
        await _insert_event(
            escrow_db, row["id"], "disputed", "under_review",
            "mediator.assigned", created_at=entered,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            await dl.check_escrow_deadlines(escrow_db)

        events = await _get_events(escrow_db, row["id"])
        triggers = [e.trigger for e in events]
        assert "system.mediator_sla_144h_auto_execute" in triggers

    @pytest.mark.asyncio
    async def test_144h_idempotent(self, escrow_db):
        """Second scan after auto-execute → escrow already terminal, skip."""
        dl, _ = _get_deadlines_module()
        entered = T0 - timedelta(hours=145)
        # Already executed — state is resolved_split (terminal)
        row = await _insert_escrow(escrow_db, "resolved_split")
        await _insert_event(
            escrow_db, row["id"], "disputed", "under_review",
            "mediator.assigned", created_at=entered,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        # Not counted — not in under_review state anymore
        assert results["mediator_auto_executed"] == 0


# ═══════════════════════════════════════════════════════════════════
#  MULTI-ESCROW SCAN
# ═══════════════════════════════════════════════════════════════════

class TestMultiEscrowScan:

    @pytest.mark.asyncio
    async def test_mixed_deadlines_processed(self, escrow_db):
        """Single scan handles multiple escrows in different states."""
        dl, _ = _get_deadlines_module()
        seller_id = str(uuid4())
        await _insert_user(escrow_db, seller_id)

        past_payment = (T0 - timedelta(hours=2))
        past_shipping = (T0 - timedelta(hours=1))
        past_inspection = (T0 - timedelta(hours=1))
        await _insert_escrow(
            escrow_db, "payment_pending", payment_deadline=past_payment,
        )
        await _insert_escrow(
            escrow_db, "shipping_requested",
            shipping_deadline=past_shipping, seller_id=seller_id,
        )
        await _insert_escrow(
            escrow_db, "inspection_period",
            inspection_deadline=past_inspection,
        )

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert results["payment_expired"] == 1
        assert results["shipping_expired"] == 1
        assert results["inspection_expired"] == 1

    @pytest.mark.asyncio
    async def test_unrelated_states_ignored(self, escrow_db):
        """Escrows in non-deadline states are not touched."""
        dl, _ = _get_deadlines_module()
        await _insert_escrow(escrow_db, "payment_pending")
        await _insert_escrow(escrow_db, "funds_held")
        await _insert_escrow(escrow_db, "in_transit")
        await _insert_escrow(escrow_db, "released")
        await _insert_escrow(escrow_db, "cancelled")

        with patch.object(dl, "datetime") as mock_dt:
            mock_dt.now.return_value = T0

            results = await dl.check_escrow_deadlines(escrow_db)

        assert sum(results.values()) == 0
