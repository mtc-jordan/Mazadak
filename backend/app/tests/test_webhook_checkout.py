"""
Tests for checkout webhook handler — app/services/webhook/checkout_handler.py.

8 tests with real HMAC signatures:
  1. test_valid_signature_payment_captured → escrow transitions correctly
  2. test_invalid_signature → 403 returned
  3. test_missing_signature → 403 returned
  4. test_duplicate_webhook_payment_captured → 200 returned, no double transition
  5. test_amount_mismatch → flagged for review, no transition
  6. test_payment_declined_first_retry → buyer notified, no cancellation
  7. test_payment_declined_third_retry → cancelled, second bidder notified
  8. test_unknown_event_type → 200 returned (ignore gracefully)

All tests use real HMAC signatures computed with a test secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.escrow.models import Escrow, EscrowEvent


# ── Constants ─────────────────────────────────────────────────────

TEST_WEBHOOK_SECRET = "whsec_checkout_handler_test_secret"


# ── Helpers ───────────────────────────────────────────────────────

def generate_test_signature(secret: str, body: bytes) -> str:
    """Compute HMAC-SHA256 signature matching Checkout.com format."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ── SQLite fixture ────────────────────────────────────────────────

def _register_sqlite_functions(dbapi_conn, connection_record):
    import uuid as _uuid
    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(_uuid.uuid4()))
    dbapi_conn.create_function("now", 0, lambda: "2026-04-08T00:00:00")


@pytest.fixture
async def webhook_db():
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


# ── Insert helper ─────────────────────────────────────────────────

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


async def _get_events(db: AsyncSession, escrow_id: str) -> list:
    result = await db.execute(
        select(EscrowEvent)
        .where(EscrowEvent.escrow_id == escrow_id)
        .order_by(EscrowEvent.created_at)
    )
    return result.scalars().all()


# ── Module import helper (mock Celery) ────────────────────────────

def _get_handler():
    """Import checkout handler with Celery mocked out."""
    for mod_name in [
        "app.services.webhook.checkout_handler",
        "app.services.escrow.fsm",
    ]:
        sys.modules.pop(mod_name, None)

    mock_tasks = MagicMock()
    with patch.dict("sys.modules", {
        "app.tasks.escrow": mock_tasks,
        "app.core.celery": MagicMock(),
        "celery": MagicMock(),
    }):
        from app.services.webhook import checkout_handler
    return checkout_handler, mock_tasks


# ── Build payloads ────────────────────────────────────────────────

def _captured_payload(escrow_id: str, amount_minor: int = 500_000, currency: str = "JOD") -> dict:
    return {
        "type": "payment.captured",
        "data": {
            "id": f"pay_{uuid4().hex[:12]}",
            "reference": escrow_id,
            "amount": amount_minor,
            "currency": currency,
        },
    }


def _declined_payload(escrow_id: str, reason: str = "Insufficient Funds") -> dict:
    return {
        "type": "payment.declined",
        "data": {
            "id": f"pay_{uuid4().hex[:12]}",
            "reference": escrow_id,
            "amount": 500_000,
            "currency": "JOD",
            "response_summary": reason,
        },
    }


# ── Mock Request factory ─────────────────────────────────────────

def _make_mock_request(body: bytes, signature: str | None = None) -> MagicMock:
    """Create a mock FastAPI Request with body() and headers."""
    request = MagicMock()
    request.body = AsyncMock(return_value=body)
    headers = {}
    if signature is not None:
        headers["cko-signature"] = signature
    request.headers = headers
    return request


# ═══════════════════════════════════════════════════════════════════
#  TEST 1: Valid signature — payment.captured transitions correctly
# ═══════════════════════════════════════════════════════════════════

class TestValidSignaturePaymentCaptured:

    @pytest.mark.asyncio
    async def test_valid_signature_payment_captured(self, webhook_db):
        """Correctly signed payment.captured → funds_held → shipping_requested."""
        handler, _ = _get_handler()
        row = await _insert_escrow(webhook_db, state="payment_pending", amount=500.0)
        payload = _captured_payload(row["id"], amount_minor=500_000)
        raw_body = json.dumps(payload).encode()

        # Verify signature passes
        sig = generate_test_signature(TEST_WEBHOOK_SECRET, raw_body)
        request = _make_mock_request(raw_body, sig)

        with patch.object(handler, "settings") as mock_settings:
            mock_settings.CHECKOUT_WEBHOOK_SECRET = TEST_WEBHOOK_SECRET
            verified_body = await handler.verify_checkout_signature(request)

        assert verified_body == raw_body

        # Process the webhook
        result = await handler.handle_checkout_webhook(raw_body, webhook_db)

        assert result == {"success": True}

        # Verify escrow transitioned to shipping_requested
        escrow = await webhook_db.get(Escrow, row["id"])
        assert escrow.state == "shipping_requested"
        assert escrow.checkout_payment_id is not None

        # Verify two FSM events: funds_held + shipping_requested
        events = await _get_events(webhook_db, row["id"])
        assert len(events) == 2
        assert events[0].to_state == "funds_held"
        assert events[0].trigger == "webhook.payment_captured"
        assert events[1].to_state == "shipping_requested"
        assert events[1].trigger == "system.auto_shipping_request"


# ═══════════════════════════════════════════════════════════════════
#  TEST 2: Invalid signature → 403
# ═══════════════════════════════════════════════════════════════════

class TestInvalidSignature:

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_403(self):
        """Wrong HMAC signature → HTTPException 403."""
        handler, _ = _get_handler()
        body = b'{"type":"payment.captured","data":{}}'
        bad_sig = generate_test_signature("wrong_secret", body)
        request = _make_mock_request(body, bad_sig)

        with patch.object(handler, "settings") as mock_settings:
            mock_settings.CHECKOUT_WEBHOOK_SECRET = TEST_WEBHOOK_SECRET
            with pytest.raises(HTTPException) as exc_info:
                await handler.verify_checkout_signature(request)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Invalid webhook signature"


# ═══════════════════════════════════════════════════════════════════
#  TEST 3: Missing signature → 403
# ═══════════════════════════════════════════════════════════════════

class TestMissingSignature:

    @pytest.mark.asyncio
    async def test_missing_signature_returns_403(self):
        """No cko-signature header → HTTPException 403."""
        handler, _ = _get_handler()
        body = b'{"type":"payment.captured","data":{}}'
        request = _make_mock_request(body, signature=None)

        with pytest.raises(HTTPException) as exc_info:
            await handler.verify_checkout_signature(request)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Missing webhook signature"


# ═══════════════════════════════════════════════════════════════════
#  TEST 4: Duplicate webhook — 200, no double transition
# ═══════════════════════════════════════════════════════════════════

class TestDuplicateWebhook:

    @pytest.mark.asyncio
    async def test_duplicate_webhook_payment_captured(self, webhook_db):
        """Second identical captured webhook → 200, no double transition."""
        handler, _ = _get_handler()
        row = await _insert_escrow(webhook_db, state="payment_pending", amount=500.0)
        payload = _captured_payload(row["id"], amount_minor=500_000)
        raw_body = json.dumps(payload).encode()

        # First call processes transitions
        result1 = await handler.handle_checkout_webhook(raw_body, webhook_db)
        assert result1 == {"success": True}

        # Second call — already past payment_pending, idempotent
        result2 = await handler.handle_checkout_webhook(raw_body, webhook_db)
        assert result2 == {"success": True}

        # Only 2 events (funds_held + shipping_requested), not 4
        events = await _get_events(webhook_db, row["id"])
        assert len(events) == 2

        # State unchanged after duplicate
        escrow = await webhook_db.get(Escrow, row["id"])
        assert escrow.state == "shipping_requested"


# ═══════════════════════════════════════════════════════════════════
#  TEST 5: Amount mismatch → flagged for review, no transition
# ═══════════════════════════════════════════════════════════════════

class TestAmountMismatch:

    @pytest.mark.asyncio
    async def test_amount_mismatch_flagged(self, webhook_db):
        """Captured amount differs by >1 minor unit → flagged, no transition."""
        handler, _ = _get_handler()
        row = await _insert_escrow(webhook_db, state="payment_pending", amount=500.0)
        # Send 600 JOD (600_000 fils) instead of 500 JOD (500_000 fils)
        payload = _captured_payload(row["id"], amount_minor=600_000)
        raw_body = json.dumps(payload).encode()

        result = await handler.handle_checkout_webhook(raw_body, webhook_db)

        assert result == {"success": True}

        # State should NOT have changed
        escrow = await webhook_db.get(Escrow, row["id"])
        assert escrow.state == "payment_pending"

        # A flag_for_review event should exist
        events = await _get_events(webhook_db, row["id"])
        assert len(events) == 1
        assert events[0].trigger == "system.flag_for_review"


# ═══════════════════════════════════════════════════════════════════
#  TEST 6: Declined first retry → buyer notified, no cancellation
# ═══════════════════════════════════════════════════════════════════

class TestDeclinedFirstRetry:

    @pytest.mark.asyncio
    async def test_payment_declined_first_retry(self, webhook_db):
        """First decline → stays payment_pending, buyer notified to retry."""
        handler, mock_tasks = _get_handler()
        row = await _insert_escrow(webhook_db, state="payment_pending")
        payload = _declined_payload(row["id"])
        raw_body = json.dumps(payload).encode()

        with patch.dict("sys.modules", {
            "app.tasks.escrow": mock_tasks,
            "app.core.celery": MagicMock(),
        }):
            result = await handler.handle_checkout_webhook(raw_body, webhook_db)

        assert result == {"success": True}

        # State unchanged
        escrow = await webhook_db.get(Escrow, row["id"])
        assert escrow.state == "payment_pending"
        assert escrow.retry_count == 1

        # No FSM transition event (no state change)
        events = await _get_events(webhook_db, row["id"])
        assert len(events) == 0

        # Buyer notified to retry
        mock_tasks.notify_payment_failed.delay.assert_called_once_with(
            str(row["winner_id"]), 1,
        )

        # Second-place bidder NOT notified (only on 3rd failure)
        mock_tasks.notify_second_place_bidder.delay.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
#  TEST 7: Declined third retry → cancelled, second bidder notified
# ═══════════════════════════════════════════════════════════════════

class TestDeclinedThirdRetry:

    @pytest.mark.asyncio
    async def test_payment_declined_third_retry(self, webhook_db):
        """Third decline (>= MAX) → cancelled + second-place bidder notified."""
        handler, _ = _get_handler()
        row = await _insert_escrow(webhook_db, state="payment_pending", retry_count=2)
        payload = _declined_payload(row["id"])
        raw_body = json.dumps(payload).encode()

        mock_tasks = MagicMock()
        with patch.dict("sys.modules", {
            "app.tasks.escrow": mock_tasks,
            "app.core.celery": MagicMock(),
        }):
            result = await handler.handle_checkout_webhook(raw_body, webhook_db)

        assert result == {"success": True}

        # Escrow cancelled
        escrow = await webhook_db.get(Escrow, row["id"])
        assert escrow.state == "cancelled"
        assert escrow.retry_count == 3

        # Second-place bidder notified
        mock_tasks.notify_second_place_bidder.delay.assert_called_once_with(
            str(row["auction_id"]),
        )

        # One FSM event: payment_pending → cancelled
        events = await _get_events(webhook_db, row["id"])
        assert len(events) == 1
        assert events[0].from_state == "payment_pending"
        assert events[0].to_state == "cancelled"
        assert events[0].trigger == "payment.declined.max_retries"


# ═══════════════════════════════════════════════════════════════════
#  TEST 8: Unknown event type → 200 returned (ignore gracefully)
# ═══════════════════════════════════════════════════════════════════

class TestUnknownEventType:

    @pytest.mark.asyncio
    async def test_unknown_event_type(self, webhook_db):
        """Unrecognised event type → 200 with success=True."""
        handler, _ = _get_handler()
        payload = {"type": "payment.void", "data": {}}
        raw_body = json.dumps(payload).encode()

        result = await handler.handle_checkout_webhook(raw_body, webhook_db)

        assert result == {"success": True}
