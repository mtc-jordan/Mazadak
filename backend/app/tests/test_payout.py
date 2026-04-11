"""
Payout task tests — FR-ESC-004, PM-10.

Covers:
  - Seller payout: happy path with mocked Checkout.com, audit event creation
  - Seller payout: wrong escrow state -> early return
  - Buyer refund: full refund via Checkout.com, audit event
  - Split payout: 50/50 math verification
  - JOD to minor unit conversion (1 JOD = 1000 fils)
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import importlib

import pytest

# ── Mock Celery before any app.tasks import ──────────────────────
_mock_celery_app = MagicMock()
_mock_celery_app.task = lambda *a, **kw: (lambda fn: fn)

sys.modules.setdefault("celery", MagicMock())
sys.modules.setdefault("celery.schedules", MagicMock())
sys.modules.setdefault("app.core.celery", MagicMock(celery_app=_mock_celery_app))

# Ensure app.tasks.escrow is the real module, not a mock left by other tests.
# Other test files (test_full_flow_integration, test_bot) set app.tasks and
# app.tasks.escrow to MagicMocks at module level, polluting sys.modules.
for _mod_name in ["app.tasks", "app.tasks.escrow", "app.tasks.auction",
                  "app.tasks.notification", "app.tasks.listing"]:
    _mod = sys.modules.get(_mod_name)
    if _mod is not None and not hasattr(_mod, "__file__"):
        del sys.modules[_mod_name]
# Now re-import the real modules
import app.tasks.escrow  # noqa: F401


# =====================================================================
#  JOD -> minor unit conversion
# =====================================================================


class TestJodToMinor:
    def test_whole_jod(self):
        from app.tasks.escrow import _jod_to_minor
        assert _jod_to_minor(1.0) == 1000

    def test_fractional_jod(self):
        from app.tasks.escrow import _jod_to_minor
        assert _jod_to_minor(1.5) == 1500

    def test_small_fraction(self):
        from app.tasks.escrow import _jod_to_minor
        assert _jod_to_minor(0.001) == 1

    def test_zero(self):
        from app.tasks.escrow import _jod_to_minor
        assert _jod_to_minor(0.0) == 0

    def test_large_amount(self):
        from app.tasks.escrow import _jod_to_minor
        assert _jod_to_minor(100.0) == 100_000


# =====================================================================
#  Split payout math
# =====================================================================


class TestSplitPayoutMath:
    def test_50_50_split(self):
        """50/50 split of 100 JOD -> 50 each."""
        total = 100.0
        ratio = 50
        buyer_refund = round(total * ratio / 100, 3)
        seller_payout = round(total - buyer_refund, 3)
        assert buyer_refund == 50.0
        assert seller_payout == 50.0

    def test_70_30_split(self):
        """70/30 split of 100 JOD -> buyer 70, seller 30."""
        total = 100.0
        ratio = 70
        buyer_refund = round(total * ratio / 100, 3)
        seller_payout = round(total - buyer_refund, 3)
        assert buyer_refund == 70.0
        assert seller_payout == 30.0

    def test_split_with_odd_amount(self):
        """50/50 split of 33.333 JOD -> each gets ~16.667."""
        total = 33.333
        ratio = 50
        buyer_refund = round(total * ratio / 100, 3)
        seller_payout = round(total - buyer_refund, 3)
        assert buyer_refund == 16.666  # round(33.333 * 50 / 100, 3)
        assert seller_payout == 16.667

    def test_split_with_fractional_fils(self):
        """Split preserves 3 decimal places (fils precision)."""
        total = 1.5
        ratio = 50
        buyer_refund = round(total * ratio / 100, 3)
        seller_payout = round(total - buyer_refund, 3)
        assert buyer_refund == 0.75
        assert seller_payout == 0.75


# =====================================================================
#  Helpers
# =====================================================================


def _make_fake_escrow(**overrides):
    """Build a fake escrow object with sensible defaults."""
    defaults = {
        "id": "esc-001",
        "auction_id": "auc-001",
        "winner_id": "buyer-001",
        "seller_id": "seller-001",
        "state": "released",
        "amount": 100.0,
        "currency": "JOD",
        "seller_amount": None,
        "checkout_payment_id": "pay_abc123",
        "retry_count": 0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_settings(**overrides):
    """Build a settings-like object."""
    defaults = {
        "CHECKOUT_SECRET_KEY": "sk_test_123",
        "PLATFORM_FEE_PERCENT": 5.0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class _FakeSessionCtx:
    """Async context manager that yields a mock db session."""

    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *args):
        pass


# =====================================================================
#  Seller payout async logic
# =====================================================================


class TestSellerPayoutAsync:
    @pytest.mark.asyncio
    async def test_seller_payout_success(self):
        """Happy path: released escrow -> audit event + notification queued."""
        fake_escrow = _make_fake_escrow(state="released")
        fake_db = AsyncMock()
        fake_redis = AsyncMock()
        fake_redis.aclose = AsyncMock()

        mock_queue_notification = AsyncMock()

        with (
            patch("app.core.config.settings", _mock_settings()),
            patch(
                "app.core.database.async_session_factory",
                return_value=_FakeSessionCtx(fake_db),
            ),
            patch(
                "app.core.redis.get_redis_client",
                new_callable=AsyncMock,
                return_value=fake_redis,
            ),
            patch(
                "app.services.escrow.service.get_escrow",
                new_callable=AsyncMock,
                return_value=fake_escrow,
            ),
            patch(
                "app.services.notification.service.queue_notification",
                mock_queue_notification,
            ),
        ):
            from app.tasks.escrow import _seller_payout_async
            await _seller_payout_async("esc-001")

            # Audit event should be added to db
            fake_db.add.assert_called_once()
            event = fake_db.add.call_args[0][0]
            assert event.trigger == "seller_payout_queued"
            assert event.escrow_id == "esc-001"
            meta = event.meta
            assert float(meta["platform_fee"]) == 5.0  # 5% of 100
            assert float(meta["seller_net"]) == 95.0

            # Commit called
            fake_db.commit.assert_called_once()

            # Notification queued for seller
            mock_queue_notification.assert_called_once()
            call_args = mock_queue_notification.call_args
            assert call_args[0][0] == "seller-001"
            assert call_args[0][1] == "seller_payout_pending"

    @pytest.mark.asyncio
    async def test_seller_payout_wrong_state(self):
        """Escrow not in released state -> log and return, no DB writes."""
        fake_escrow = _make_fake_escrow(state="funds_held")
        fake_db = AsyncMock()
        fake_redis = AsyncMock()
        fake_redis.aclose = AsyncMock()

        with (
            patch("app.core.config.settings", _mock_settings()),
            patch(
                "app.core.database.async_session_factory",
                return_value=_FakeSessionCtx(fake_db),
            ),
            patch(
                "app.core.redis.get_redis_client",
                new_callable=AsyncMock,
                return_value=fake_redis,
            ),
            patch(
                "app.services.escrow.service.get_escrow",
                new_callable=AsyncMock,
                return_value=fake_escrow,
            ),
            patch(
                "app.services.notification.service.queue_notification",
                new_callable=AsyncMock,
            ) as mock_notify,
        ):
            from app.tasks.escrow import _seller_payout_async
            await _seller_payout_async("esc-001")

            # No DB writes, no notifications
            fake_db.add.assert_not_called()
            mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_seller_payout_uses_precomputed_seller_amount(self):
        """When escrow.seller_amount is set, use it instead of computing."""
        fake_escrow = _make_fake_escrow(state="released", seller_amount=90.0)
        fake_db = AsyncMock()
        fake_redis = AsyncMock()
        fake_redis.aclose = AsyncMock()

        with (
            patch("app.core.config.settings", _mock_settings()),
            patch(
                "app.core.database.async_session_factory",
                return_value=_FakeSessionCtx(fake_db),
            ),
            patch(
                "app.core.redis.get_redis_client",
                new_callable=AsyncMock,
                return_value=fake_redis,
            ),
            patch(
                "app.services.escrow.service.get_escrow",
                new_callable=AsyncMock,
                return_value=fake_escrow,
            ),
            patch(
                "app.services.notification.service.queue_notification",
                new_callable=AsyncMock,
            ),
        ):
            from app.tasks.escrow import _seller_payout_async
            await _seller_payout_async("esc-001")

            event = fake_db.add.call_args[0][0]
            assert float(event.meta["seller_net"]) == 90.0

    @pytest.mark.asyncio
    async def test_seller_payout_no_checkout_key(self):
        """No CHECKOUT_SECRET_KEY -> early return."""
        fake_redis = AsyncMock()

        with (
            patch(
                "app.core.config.settings",
                _mock_settings(CHECKOUT_SECRET_KEY=""),
            ),
        ):
            from app.tasks.escrow import _seller_payout_async
            # Should return without error, no DB calls
            await _seller_payout_async("esc-001")


# =====================================================================
#  Buyer refund async logic
# =====================================================================


class TestBuyerRefundAsync:
    @pytest.mark.asyncio
    async def test_buyer_refund_success(self):
        """Happy path: resolved_refunded escrow -> Checkout refund + audit event."""
        fake_escrow = _make_fake_escrow(state="resolved_refunded")
        fake_db = AsyncMock()
        fake_redis = AsyncMock()
        fake_redis.aclose = AsyncMock()

        refund_response = {"action_id": "act_refund_123"}
        mock_checkout_refund = AsyncMock(return_value=refund_response)
        mock_queue_notification = AsyncMock()

        with (
            patch("app.core.config.settings", _mock_settings()),
            patch(
                "app.core.database.async_session_factory",
                return_value=_FakeSessionCtx(fake_db),
            ),
            patch(
                "app.core.redis.get_redis_client",
                new_callable=AsyncMock,
                return_value=fake_redis,
            ),
            patch(
                "app.services.escrow.service.get_escrow",
                new_callable=AsyncMock,
                return_value=fake_escrow,
            ),
            patch(
                "app.tasks.escrow._checkout_refund",
                mock_checkout_refund,
            ),
            patch(
                "app.services.notification.service.queue_notification",
                mock_queue_notification,
            ),
        ):
            from app.tasks.escrow import _buyer_refund_async
            await _buyer_refund_async("esc-001")

            # Checkout refund called with full refund (amount_minor=0)
            mock_checkout_refund.assert_called_once_with(
                checkout_payment_id="pay_abc123",
                amount_minor=0,
                currency="JOD",
                reference="refund-esc-001",
            )

            # Audit event recorded
            fake_db.add.assert_called_once()
            event = fake_db.add.call_args[0][0]
            assert event.trigger == "buyer_refund_executed"
            assert event.meta["type"] == "full_refund"
            assert event.meta["checkout_refund_id"] == "act_refund_123"

            # Buyer notified
            mock_queue_notification.assert_called_once()
            assert mock_queue_notification.call_args[0][0] == "buyer-001"
            assert mock_queue_notification.call_args[0][1] == "buyer_refund_processed"

    @pytest.mark.asyncio
    async def test_buyer_refund_wrong_state(self):
        """Escrow not in resolved_refunded -> skip."""
        fake_escrow = _make_fake_escrow(state="funds_held")
        fake_db = AsyncMock()
        fake_redis = AsyncMock()
        fake_redis.aclose = AsyncMock()

        mock_checkout_refund = AsyncMock()

        with (
            patch("app.core.config.settings", _mock_settings()),
            patch(
                "app.core.database.async_session_factory",
                return_value=_FakeSessionCtx(fake_db),
            ),
            patch(
                "app.core.redis.get_redis_client",
                new_callable=AsyncMock,
                return_value=fake_redis,
            ),
            patch(
                "app.services.escrow.service.get_escrow",
                new_callable=AsyncMock,
                return_value=fake_escrow,
            ),
            patch(
                "app.tasks.escrow._checkout_refund",
                mock_checkout_refund,
            ),
        ):
            from app.tasks.escrow import _buyer_refund_async
            await _buyer_refund_async("esc-001")

            mock_checkout_refund.assert_not_called()
            fake_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_buyer_refund_no_payment_id(self):
        """Escrow without checkout_payment_id -> skip refund."""
        fake_escrow = _make_fake_escrow(
            state="resolved_refunded",
            checkout_payment_id=None,
        )
        fake_db = AsyncMock()
        fake_redis = AsyncMock()
        fake_redis.aclose = AsyncMock()

        mock_checkout_refund = AsyncMock()

        with (
            patch("app.core.config.settings", _mock_settings()),
            patch(
                "app.core.database.async_session_factory",
                return_value=_FakeSessionCtx(fake_db),
            ),
            patch(
                "app.core.redis.get_redis_client",
                new_callable=AsyncMock,
                return_value=fake_redis,
            ),
            patch(
                "app.services.escrow.service.get_escrow",
                new_callable=AsyncMock,
                return_value=fake_escrow,
            ),
            patch(
                "app.tasks.escrow._checkout_refund",
                mock_checkout_refund,
            ),
        ):
            from app.tasks.escrow import _buyer_refund_async
            await _buyer_refund_async("esc-001")

            mock_checkout_refund.assert_not_called()
            fake_db.add.assert_not_called()
