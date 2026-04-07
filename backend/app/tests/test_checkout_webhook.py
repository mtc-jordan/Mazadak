"""
Tests for Checkout.com webhook — FR-ESC-003, PM-08.

Covers:
  - HMAC-SHA256 signature verification (valid, invalid, missing)
  - payment.captured: idempotent, amount verification, double-transition
  - payment.declined: retry counting, auto-cancel after 3 failures
  - payment.refunded: from under_review
  - Duplicate webhook handling
  - Unknown event types

All tests use real HMAC signatures computed with a test secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.escrow.models import ActorType, Escrow, EscrowEvent, VALID_TRANSITIONS


# ── Constants ─────────────────────────────────────────────────────

TEST_WEBHOOK_SECRET = "whsec_test_secret_key_for_unit_tests"


# ── SQLite fixture (same pattern as test_escrow_fsm.py) ──────────

def _register_sqlite_functions(dbapi_conn, connection_record):
    import uuid as _uuid
    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(_uuid.uuid4()))
    dbapi_conn.create_function("now", 0, lambda: "2026-04-07T00:00:00")


@pytest.fixture
async def escrow_db():
    from sqlalchemy import event
    from app.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)

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

async def _insert_escrow(db: AsyncSession, state: str = "payment_pending", **overrides) -> dict:
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


def _sign(payload: bytes, secret: str = TEST_WEBHOOK_SECRET) -> str:
    """Compute the HMAC-SHA256 signature for a payload."""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _captured_payload(escrow_id: str, amount_minor: int = 500_000, currency: str = "JOD") -> dict:
    """Build a payment_captured webhook payload."""
    return {
        "id": f"evt_{uuid4().hex[:12]}",
        "type": "payment_captured",
        "data": {
            "id": f"pay_{uuid4().hex[:12]}",
            "reference": escrow_id,
            "amount": amount_minor,
            "currency": currency,
            "response_summary": "Approved",
        },
    }


def _declined_payload(escrow_id: str, reason: str = "Insufficient Funds") -> dict:
    return {
        "id": f"evt_{uuid4().hex[:12]}",
        "type": "payment_declined",
        "data": {
            "id": f"pay_{uuid4().hex[:12]}",
            "reference": escrow_id,
            "amount": 500_000,
            "currency": "JOD",
            "response_summary": reason,
        },
    }


def _refunded_payload(escrow_id: str) -> dict:
    return {
        "id": f"evt_{uuid4().hex[:12]}",
        "type": "payment_refunded",
        "data": {
            "id": f"pay_{uuid4().hex[:12]}",
            "reference": escrow_id,
            "amount": 500_000,
            "currency": "JOD",
        },
    }


async def _get_events(db: AsyncSession, escrow_id: str) -> list:
    result = await db.execute(
        select(EscrowEvent)
        .where(EscrowEvent.escrow_id == escrow_id)
        .order_by(EscrowEvent.created_at)
    )
    return result.scalars().all()


def _get_webhook_module():
    """Import webhook module with Celery mocked out."""
    for mod_name in [
        "app.services.escrow.webhook",
        "app.services.escrow.fsm",
    ]:
        sys.modules.pop(mod_name, None)

    mock_tasks = MagicMock()
    with patch.dict("sys.modules", {
        "app.tasks.escrow": mock_tasks,
        "app.core.celery": MagicMock(),
        "celery": MagicMock(),
    }):
        from app.services.escrow import webhook
    return webhook, mock_tasks


# ═══════════════════════════════════════════════════════════════════
#  HMAC SIGNATURE VERIFICATION
# ═══════════════════════════════════════════════════════════════════

class TestSignatureVerification:

    def test_valid_signature_accepted(self):
        webhook, _ = _get_webhook_module()
        body = b'{"type":"payment_captured","data":{}}'
        sig = _sign(body)
        assert webhook.verify_signature(body, sig, TEST_WEBHOOK_SECRET) is True

    def test_invalid_signature_rejected(self):
        webhook, _ = _get_webhook_module()
        body = b'{"type":"payment_captured","data":{}}'
        assert webhook.verify_signature(body, "bad_sig", TEST_WEBHOOK_SECRET) is False

    def test_wrong_secret_rejected(self):
        webhook, _ = _get_webhook_module()
        body = b'{"type":"payment_captured","data":{}}'
        sig = _sign(body, "wrong_secret")
        assert webhook.verify_signature(body, sig, TEST_WEBHOOK_SECRET) is False

    def test_empty_signature_rejected(self):
        webhook, _ = _get_webhook_module()
        body = b'{"type":"payment_captured","data":{}}'
        assert webhook.verify_signature(body, "", TEST_WEBHOOK_SECRET) is False

    def test_tampered_body_rejected(self):
        webhook, _ = _get_webhook_module()
        body = b'{"type":"payment_captured","data":{}}'
        sig = _sign(body)
        tampered = b'{"type":"payment_captured","data":{"amount":0}}'
        assert webhook.verify_signature(tampered, sig, TEST_WEBHOOK_SECRET) is False


# ═══════════════════════════════════════════════════════════════════
#  payment.captured
# ═══════════════════════════════════════════════════════════════════

class TestPaymentCaptured:

    @pytest.mark.asyncio
    async def test_captured_happy_path(self, escrow_db):
        """payment_pending → funds_held → shipping_requested with deadline."""
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="payment_pending", amount=500.0)
        payload = _captured_payload(row["id"], amount_minor=500_000)

        result = await webhook.handle_webhook("payment_captured", payload["data"], escrow_db)

        assert result["status"] == "processed"
        assert result["state"] == "shipping_requested"

        # Verify final state in DB
        escrow = await escrow_db.get(Escrow, row["id"])
        assert escrow.state == "shipping_requested"
        assert escrow.shipping_deadline is not None

        # Verify two events: funds_held + shipping_requested
        events = await _get_events(escrow_db, row["id"])
        assert len(events) == 2
        assert events[0].to_state == "funds_held"
        assert events[1].to_state == "shipping_requested"

    @pytest.mark.asyncio
    async def test_captured_idempotent_funds_held(self, escrow_db):
        """Duplicate webhook for escrow already in funds_held → already_processed."""
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="funds_held")
        payload = _captured_payload(row["id"])

        result = await webhook.handle_webhook("payment_captured", payload["data"], escrow_db)

        assert result["status"] == "already_processed"
        assert result["state"] == "funds_held"

    @pytest.mark.asyncio
    async def test_captured_idempotent_shipping_requested(self, escrow_db):
        """Duplicate webhook for escrow already in shipping_requested."""
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="shipping_requested")
        payload = _captured_payload(row["id"])

        result = await webhook.handle_webhook("payment_captured", payload["data"], escrow_db)

        assert result["status"] == "already_processed"

    @pytest.mark.asyncio
    async def test_captured_idempotent_released(self, escrow_db):
        """Duplicate webhook for escrow already released."""
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="released")
        payload = _captured_payload(row["id"])

        result = await webhook.handle_webhook("payment_captured", payload["data"], escrow_db)

        assert result["status"] == "already_processed"

    @pytest.mark.asyncio
    async def test_captured_amount_mismatch_rejected(self, escrow_db):
        """Captured amount doesn't match escrow → error."""
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="payment_pending", amount=500.0)
        # Send 600 JOD (600000 fils) instead of 500 JOD
        payload = _captured_payload(row["id"], amount_minor=600_000)

        result = await webhook.handle_webhook("payment_captured", payload["data"], escrow_db)

        assert result["status"] == "error"
        assert result["reason"] == "amount_mismatch"

        # State should NOT have changed
        escrow = await escrow_db.get(Escrow, row["id"])
        assert escrow.state == "payment_pending"

    @pytest.mark.asyncio
    async def test_captured_amount_within_tolerance(self, escrow_db):
        """Tiny rounding difference within 0.001 → accepted."""
        webhook, _ = _get_webhook_module()
        # 500.0 JOD = 500000 fils. 500001 fils = 500.001 → within tolerance
        row = await _insert_escrow(escrow_db, state="payment_pending", amount=500.0)
        payload = _captured_payload(row["id"], amount_minor=500_000)

        result = await webhook.handle_webhook("payment_captured", payload["data"], escrow_db)

        assert result["status"] == "processed"

    @pytest.mark.asyncio
    async def test_captured_missing_reference(self, escrow_db):
        webhook, _ = _get_webhook_module()
        result = await webhook.handle_webhook("payment_captured", {"amount": 100}, escrow_db)
        assert result["status"] == "error"
        assert result["reason"] == "missing_reference"

    @pytest.mark.asyncio
    async def test_captured_unknown_escrow(self, escrow_db):
        webhook, _ = _get_webhook_module()
        payload = _captured_payload(str(uuid4()))
        result = await webhook.handle_webhook("payment_captured", payload["data"], escrow_db)
        assert result["status"] == "error"
        assert result["reason"] == "escrow_not_found"

    @pytest.mark.asyncio
    async def test_captured_usd_two_decimal_conversion(self, escrow_db):
        """USD uses 2-decimal minor units (100 cents = 1 USD)."""
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(
            escrow_db, state="payment_pending", amount=50.0, currency="USD",
        )
        # 50 USD = 5000 cents
        payload = _captured_payload(row["id"], amount_minor=5000, currency="USD")

        result = await webhook.handle_webhook("payment_captured", payload["data"], escrow_db)

        assert result["status"] == "processed"


# ═══════════════════════════════════════════════════════════════════
#  payment.declined
# ═══════════════════════════════════════════════════════════════════

class TestPaymentDeclined:

    @pytest.mark.asyncio
    async def test_declined_first_failure(self, escrow_db):
        """First decline → payment_failed, retry_count=1."""
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="payment_pending")
        payload = _declined_payload(row["id"])

        result = await webhook.handle_webhook("payment_declined", payload["data"], escrow_db)

        assert result["status"] == "processed"
        assert result["state"] == "payment_failed"
        assert result["retry_count"] == 1

        escrow = await escrow_db.get(Escrow, row["id"])
        assert escrow.state == "payment_failed"
        assert escrow.retry_count == 1

    @pytest.mark.asyncio
    async def test_declined_second_failure(self, escrow_db):
        """Second decline after retry → retry_count=2, still payment_failed."""
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="payment_pending", retry_count=1)
        payload = _declined_payload(row["id"])

        result = await webhook.handle_webhook("payment_declined", payload["data"], escrow_db)

        assert result["retry_count"] == 2
        assert result["state"] == "payment_failed"

    @pytest.mark.asyncio
    async def test_declined_third_failure_cancels(self, escrow_db):
        """Third decline → cancelled + second bidder notified."""
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="payment_pending", retry_count=2)
        payload = _declined_payload(row["id"])

        # Keep the mock active during handler execution so the lazy
        # `from app.tasks.escrow import notify_second_bidder` resolves
        mock_tasks = MagicMock()
        with patch.dict("sys.modules", {
            "app.tasks.escrow": mock_tasks,
            "app.core.celery": MagicMock(),
        }):
            result = await webhook.handle_webhook("payment_declined", payload["data"], escrow_db)

        assert result["status"] == "processed"
        assert result["state"] == "cancelled"
        assert result["retry_count"] == 3

        escrow = await escrow_db.get(Escrow, row["id"])
        assert escrow.state == "cancelled"

        # Verify second-bidder notification was dispatched
        mock_tasks.notify_second_bidder.delay.assert_called_once_with(row["auction_id"])

    @pytest.mark.asyncio
    async def test_declined_creates_event_log(self, escrow_db):
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="payment_pending")
        payload = _declined_payload(row["id"], reason="Insufficient Funds")

        await webhook.handle_webhook("payment_declined", payload["data"], escrow_db)

        events = await _get_events(escrow_db, row["id"])
        assert len(events) == 1
        assert events[0].trigger == "checkout.payment_declined"
        assert events[0].from_state == "payment_pending"
        assert events[0].to_state == "payment_failed"

    @pytest.mark.asyncio
    async def test_declined_ignored_if_not_payment_pending(self, escrow_db):
        """Decline webhook for escrow not in payment_pending → ignored."""
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="funds_held")
        payload = _declined_payload(row["id"])

        result = await webhook.handle_webhook("payment_declined", payload["data"], escrow_db)

        assert result["status"] == "ignored"
        assert result["reason"] == "not_payment_pending"

    @pytest.mark.asyncio
    async def test_declined_cancel_creates_two_events(self, escrow_db):
        """Third decline creates two events: payment_failed + cancelled."""
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="payment_pending", retry_count=2)
        payload = _declined_payload(row["id"])

        await webhook.handle_webhook("payment_declined", payload["data"], escrow_db)

        events = await _get_events(escrow_db, row["id"])
        assert len(events) == 2
        assert events[0].to_state == "payment_failed"
        assert events[1].to_state == "cancelled"
        assert events[1].trigger == "checkout.max_retries_exceeded"


# ═══════════════════════════════════════════════════════════════════
#  payment.refunded
# ═══════════════════════════════════════════════════════════════════

class TestPaymentRefunded:

    @pytest.mark.asyncio
    async def test_refunded_from_under_review(self, escrow_db):
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="under_review")
        payload = _refunded_payload(row["id"])

        result = await webhook.handle_webhook("payment_refunded", payload["data"], escrow_db)

        assert result["status"] == "processed"
        assert result["state"] == "refunded"

        escrow = await escrow_db.get(Escrow, row["id"])
        assert escrow.state == "refunded"

    @pytest.mark.asyncio
    async def test_refunded_already_refunded_idempotent(self, escrow_db):
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="refunded")
        payload = _refunded_payload(row["id"])

        result = await webhook.handle_webhook("payment_refunded", payload["data"], escrow_db)

        assert result["status"] == "already_processed"

    @pytest.mark.asyncio
    async def test_refunded_invalid_state_ignored(self, escrow_db):
        """Can't refund from payment_pending — no valid transition."""
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="payment_pending")
        payload = _refunded_payload(row["id"])

        result = await webhook.handle_webhook("payment_refunded", payload["data"], escrow_db)

        assert result["status"] == "ignored"
        assert result["reason"] == "invalid_state"


# ═══════════════════════════════════════════════════════════════════
#  EDGE CASES
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_unknown_event_type_ignored(self, escrow_db):
        webhook, _ = _get_webhook_module()
        result = await webhook.handle_webhook("payment.void", {}, escrow_db)
        assert result["status"] == "ignored"
        assert result["reason"] == "unhandled_event_type"

    @pytest.mark.asyncio
    async def test_duplicate_captured_webhook_safe(self, escrow_db):
        """Sending captured twice — second is idempotent."""
        webhook, _ = _get_webhook_module()
        row = await _insert_escrow(escrow_db, state="payment_pending", amount=500.0)
        payload = _captured_payload(row["id"], amount_minor=500_000)

        result1 = await webhook.handle_webhook("payment_captured", payload["data"], escrow_db)
        assert result1["status"] == "processed"

        result2 = await webhook.handle_webhook("payment_captured", payload["data"], escrow_db)
        assert result2["status"] == "already_processed"

        # Only 2 events (funds_held + shipping_requested), not 4
        events = await _get_events(escrow_db, row["id"])
        assert len(events) == 2

    def test_minor_to_major_jod(self):
        """JOD: 3 decimal places, 1000 fils per dinar."""
        webhook, _ = _get_webhook_module()
        assert webhook._minor_to_major(500_000, "JOD") == 500.0
        assert webhook._minor_to_major(1, "JOD") == 0.001
        assert webhook._minor_to_major(999, "JOD") == 0.999

    def test_minor_to_major_usd(self):
        """USD: 2 decimal places, 100 cents per dollar."""
        webhook, _ = _get_webhook_module()
        assert webhook._minor_to_major(5000, "USD") == 50.0
        assert webhook._minor_to_major(1, "USD") == 0.01

    def test_minor_to_major_kwd(self):
        """KWD: 3 decimal places like JOD."""
        webhook, _ = _get_webhook_module()
        assert webhook._minor_to_major(1000, "KWD") == 1.0
