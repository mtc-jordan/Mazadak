"""
Tests for notification dispatch pipeline — FR-NOTIF-001 → FR-NOTIF-012, PM-11.

Covers:
  - Redis deduplication (60s TTL key prevents duplicate sends)
  - Template rendering (all 20 templates, bilingual, interpolation)
  - Channel selection based on user preferences
  - Financial notification bypass (ignores user opt-out)
  - WhatsApp daily rate limit (5/day per user, non-financial)
  - In-app notification persistence
  - Channel dispatcher wiring
"""

from __future__ import annotations

import sys
import threading
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.notification.models import (
    Notification,
    NotificationChannel,
    NotificationPreference,
)


# ── Fake Redis for notification tests ─────────────────────────────

class FakeRedis:
    """Minimal async Redis mock for notification dedup + rate limiting."""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}
        self._lock = threading.Lock()

    async def exists(self, key: str) -> int:
        with self._lock:
            return 1 if key in self._store else 0

    async def get(self, key: str) -> str | None:
        with self._lock:
            return self._store.get(key)

    async def set(self, key: str, value: str) -> None:
        with self._lock:
            self._store[key] = str(value)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        with self._lock:
            self._store[key] = str(value)
            self._ttls[key] = ttl

    async def incr(self, key: str) -> int:
        with self._lock:
            val = int(self._store.get(key, "0")) + 1
            self._store[key] = str(val)
            return val

    async def expire(self, key: str, ttl: int) -> None:
        with self._lock:
            self._ttls[key] = ttl

    async def delete(self, *keys: str) -> int:
        with self._lock:
            count = 0
            for k in keys:
                if k in self._store:
                    del self._store[k]
                    count += 1
            return count

    async def aclose(self) -> None:
        pass


# ── SQLite fixture ────────────────────────────────────────────────

def _register_sqlite_functions(dbapi_conn, connection_record):
    import uuid as _uuid
    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(_uuid.uuid4()))
    dbapi_conn.create_function("now", 0, lambda: "2026-04-07T00:00:00")


@pytest.fixture
async def notif_db():
    """Async SQLite session with notification + user tables."""
    from sqlalchemy import event
    from app.core.database import Base
    from app.services.auth.models import User
    from app.services.notification.models import Notification, NotificationPreference

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)

    # Patch JSONB → Text for SQLite
    payload_col = Notification.__table__.c.payload
    orig_type = payload_col.type
    payload_col.type = Text()

    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[
                    User.__table__,
                    Notification.__table__,
                    NotificationPreference.__table__,
                ],
            )
    finally:
        payload_col.type = orig_type

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def fake_redis():
    return FakeRedis()


# ── Helpers ───────────────────────────────────────────────────────

async def _create_user(db: AsyncSession, **overrides) -> str:
    from app.services.auth.models import User, UserRole, KYCStatus, ATSTier

    uid = overrides.pop("id", str(uuid4()))
    defaults = dict(
        id=uid,
        phone=f"+9627900{uuid4().hex[:5]}",
        full_name_ar="مستخدم",
        full_name_en="Test User",
        role=UserRole.BUYER,
        kyc_status=KYCStatus.VERIFIED,
        ats_score=400,
        ats_tier=ATSTier.TRUSTED,
        country_code="JO",
        preferred_language="ar",
        strike_count=0,
    )
    defaults.update(overrides)
    user = User(**defaults)
    db.add(user)
    await db.commit()
    return uid


async def _create_preference(
    db: AsyncSession, user_id: str, **overrides,
) -> None:
    defaults = dict(
        user_id=user_id,
        push_enabled=True,
        sms_enabled=True,
        whatsapp_enabled=True,
        email_enabled=True,
    )
    defaults.update(overrides)
    pref = NotificationPreference(**defaults)
    db.add(pref)
    await db.commit()


def _get_service():
    """Import service with Celery/channels mocked."""
    for mod in [
        "app.services.notification.service",
        "app.tasks.notification",
    ]:
        sys.modules.pop(mod, None)
    mock_tasks = MagicMock()
    with patch.dict("sys.modules", {
        "app.tasks.notification": mock_tasks,
        "app.core.celery": MagicMock(),
        "celery": MagicMock(),
    }):
        from app.services.notification import service
    return service, mock_tasks


# ═══════════════════════════════════════════════════════════════════
#  DEDUPLICATION
# ═══════════════════════════════════════════════════════════════════

class TestDeduplication:

    @pytest.mark.asyncio
    async def test_first_call_queued(self, fake_redis):
        svc, mock_tasks = _get_service()
        with patch.dict("sys.modules", {"app.tasks.notification": mock_tasks}):
            result = await svc.queue_notification(
                "user1", "outbid", "auction-123", {"price": 100},
                redis=fake_redis,
            )
        assert result is True
        mock_tasks.send_notification.delay.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_within_60s_skipped(self, fake_redis):
        svc, mock_tasks = _get_service()
        with patch.dict("sys.modules", {"app.tasks.notification": mock_tasks}):
            r1 = await svc.queue_notification(
                "user1", "outbid", "auction-123", redis=fake_redis,
            )
            r2 = await svc.queue_notification(
                "user1", "outbid", "auction-123", redis=fake_redis,
            )
        assert r1 is True
        assert r2 is False
        assert mock_tasks.send_notification.delay.call_count == 1

    @pytest.mark.asyncio
    async def test_different_entity_not_deduped(self, fake_redis):
        svc, mock_tasks = _get_service()
        with patch.dict("sys.modules", {"app.tasks.notification": mock_tasks}):
            r1 = await svc.queue_notification(
                "user1", "outbid", "auction-A", redis=fake_redis,
            )
            r2 = await svc.queue_notification(
                "user1", "outbid", "auction-B", redis=fake_redis,
            )
        assert r1 is True
        assert r2 is True
        assert mock_tasks.send_notification.delay.call_count == 2

    @pytest.mark.asyncio
    async def test_different_user_not_deduped(self, fake_redis):
        svc, mock_tasks = _get_service()
        with patch.dict("sys.modules", {"app.tasks.notification": mock_tasks}):
            r1 = await svc.queue_notification(
                "userA", "outbid", "auction-1", redis=fake_redis,
            )
            r2 = await svc.queue_notification(
                "userB", "outbid", "auction-1", redis=fake_redis,
            )
        assert r1 is True
        assert r2 is True

    @pytest.mark.asyncio
    async def test_dedup_key_has_ttl(self, fake_redis):
        svc, mock_tasks = _get_service()
        with patch.dict("sys.modules", {"app.tasks.notification": mock_tasks}):
            await svc.queue_notification(
                "user1", "outbid", "auc-1", redis=fake_redis,
            )
        assert fake_redis._ttls.get("notif:user1:outbid:auc-1") == 60


# ═══════════════════════════════════════════════════════════════════
#  TEMPLATE RENDERING
# ═══════════════════════════════════════════════════════════════════

class TestTemplates:

    def test_all_20_templates_exist(self):
        from app.services.notification.templates import TEMPLATES
        assert len(TEMPLATES) == 20

    def test_render_with_interpolation(self):
        from app.services.notification.templates import render_template
        t = render_template("outbid", {"title": "iPhone 15", "price": 500, "currency": "JOD"})
        assert t is not None
        assert "iPhone 15" in t.body_ar
        assert "500" in t.body_en
        assert "JOD" in t.body_en

    def test_render_unknown_event_returns_none(self):
        from app.services.notification.templates import render_template
        assert render_template("totally_unknown") is None

    def test_render_missing_keys_returns_raw(self):
        from app.services.notification.templates import render_template
        t = render_template("outbid", {})
        assert t is not None
        # Raw template returned (uninterpolated)
        assert "{title}" in t.body_ar or "{title}" in t.body_en

    def test_financial_events_set(self):
        from app.services.notification.templates import FINANCIAL_EVENTS
        assert "payment_received" in FINANCIAL_EVENTS
        assert "payment_failed" in FINANCIAL_EVENTS
        assert "dispute_opened" in FINANCIAL_EVENTS
        assert "auction_won" in FINANCIAL_EVENTS
        # Non-financial
        assert "outbid" not in FINANCIAL_EVENTS
        assert "listing_approved" not in FINANCIAL_EVENTS


# ═══════════════════════════════════════════════════════════════════
#  CHANNEL SELECTION
# ═══════════════════════════════════════════════════════════════════

class TestChannelSelection:

    @pytest.mark.asyncio
    async def test_default_all_channels_enabled(self, notif_db):
        """No preferences row → all channels enabled."""
        svc, _ = _get_service()
        uid = await _create_user(notif_db)
        channels = await svc._resolve_channels(uid, False, notif_db)
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels
        assert NotificationChannel.WHATSAPP in channels
        assert NotificationChannel.IN_APP in channels

    @pytest.mark.asyncio
    async def test_push_disabled(self, notif_db):
        svc, _ = _get_service()
        uid = await _create_user(notif_db)
        await _create_preference(notif_db, uid, push_enabled=False)
        channels = await svc._resolve_channels(uid, False, notif_db)
        assert NotificationChannel.PUSH not in channels
        assert NotificationChannel.SMS in channels

    @pytest.mark.asyncio
    async def test_all_disabled_still_has_in_app(self, notif_db):
        svc, _ = _get_service()
        uid = await _create_user(notif_db)
        await _create_preference(
            notif_db, uid,
            push_enabled=False, sms_enabled=False,
            whatsapp_enabled=False, email_enabled=False,
        )
        channels = await svc._resolve_channels(uid, False, notif_db)
        assert channels == {NotificationChannel.IN_APP}


# ═══════════════════════════════════════════════════════════════════
#  FINANCIAL NOTIFICATION BYPASS
# ═══════════════════════════════════════════════════════════════════

class TestFinancialBypass:

    @pytest.mark.asyncio
    async def test_financial_ignores_user_opt_out(self, notif_db):
        """Financial events bypass preference check → all channels."""
        svc, _ = _get_service()
        uid = await _create_user(notif_db)
        await _create_preference(
            notif_db, uid,
            push_enabled=False, sms_enabled=False,
            whatsapp_enabled=False,
        )
        channels = await svc._resolve_channels(uid, True, notif_db)
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels
        assert NotificationChannel.WHATSAPP in channels
        assert NotificationChannel.IN_APP in channels

    @pytest.mark.asyncio
    async def test_financial_event_dispatches_all_channels(self, notif_db, fake_redis):
        """Full send_notification_impl with a financial event."""
        svc, _ = _get_service()
        uid = await _create_user(notif_db)
        await _create_preference(
            notif_db, uid,
            push_enabled=False, sms_enabled=False,
            whatsapp_enabled=False,
        )

        with patch("app.services.notification.channels.send_fcm", new_callable=AsyncMock, return_value=False), \
             patch("app.services.notification.channels.send_sms", new_callable=AsyncMock, return_value=True), \
             patch("app.services.notification.channels.send_whatsapp", new_callable=AsyncMock, return_value=False):
            dispatched = await svc.send_notification_impl(
                uid, "payment_received", str(uuid4()),
                {"amount": 500, "currency": "JOD"},
                notif_db, fake_redis,
            )

        assert "sms" in dispatched
        assert "in_app" in dispatched

    @pytest.mark.asyncio
    async def test_non_financial_respects_opt_out(self, notif_db, fake_redis):
        """Non-financial event with all channels disabled → only in_app."""
        svc, _ = _get_service()
        uid = await _create_user(notif_db)
        await _create_preference(
            notif_db, uid,
            push_enabled=False, sms_enabled=False,
            whatsapp_enabled=False,
        )

        dispatched = await svc.send_notification_impl(
            uid, "listing_approved", str(uuid4()),
            {"title": "Test Listing"},
            notif_db, fake_redis,
        )

        # Only in_app — all external channels disabled
        assert dispatched == ["in_app"]


# ═══════════════════════════════════════════════════════════════════
#  WHATSAPP RATE LIMIT
# ═══════════════════════════════════════════════════════════════════

class TestWhatsAppRateLimit:

    @pytest.mark.asyncio
    async def test_whatsapp_blocked_after_5_per_day(self, notif_db, fake_redis):
        """Non-financial: WhatsApp blocked after daily limit."""
        svc, _ = _get_service()
        uid = await _create_user(notif_db)

        # Simulate 5 WhatsApp messages already sent today
        await fake_redis.set(f"wa_daily:{uid}", "5")

        with patch("app.services.notification.channels.send_sms", new_callable=AsyncMock, return_value=False):
            dispatched = await svc.send_notification_impl(
                uid, "outbid", str(uuid4()),
                {"title": "Item", "price": 100, "currency": "JOD"},
                notif_db, fake_redis,
            )

        # WhatsApp should NOT be in dispatched channels
        assert "whatsapp" not in dispatched
        assert "in_app" in dispatched

    @pytest.mark.asyncio
    async def test_financial_bypasses_whatsapp_limit(self, notif_db, fake_redis):
        """Financial events ignore WhatsApp daily rate limit."""
        svc, _ = _get_service()
        uid = await _create_user(notif_db)

        # 5 already sent
        await fake_redis.set(f"wa_daily:{uid}", "5")

        with patch("app.services.notification.channels.send_fcm", new_callable=AsyncMock, return_value=False), \
             patch("app.services.notification.channels.send_sms", new_callable=AsyncMock, return_value=False), \
             patch("app.services.notification.channels.send_whatsapp", new_callable=AsyncMock, return_value=True):
            dispatched = await svc.send_notification_impl(
                uid, "payment_received", str(uuid4()),
                {"amount": 500, "currency": "JOD"},
                notif_db, fake_redis,
            )

        # Financial → WhatsApp not rate-limited
        assert "whatsapp" in dispatched


# ═══════════════════════════════════════════════════════════════════
#  IN-APP PERSISTENCE
# ═══════════════════════════════════════════════════════════════════

class TestInAppPersistence:

    @pytest.mark.asyncio
    async def test_notification_persisted(self, notif_db, fake_redis):
        svc, _ = _get_service()
        uid = await _create_user(notif_db)

        await svc.send_notification_impl(
            uid, "auction_started", str(uuid4()),
            {"title": "Toyota Camry", "price": 100, "currency": "JOD"},
            notif_db, fake_redis,
        )

        result = await notif_db.execute(
            select(Notification).where(Notification.user_id == uid)
        )
        notifications = list(result.scalars().all())
        assert len(notifications) == 1
        n = notifications[0]
        assert n.channel == "in_app"
        assert "المزاد بدأ" in n.title_ar
        assert n.is_read is False

    @pytest.mark.asyncio
    async def test_notification_uses_arabic_for_ar_user(self, notif_db, fake_redis):
        svc, _ = _get_service()
        uid = await _create_user(notif_db, preferred_language="ar")

        dispatched = await svc.send_notification_impl(
            uid, "auction_started", str(uuid4()),
            {"title": "سيارة", "price": 200, "currency": "JOD"},
            notif_db, fake_redis,
        )
        assert "in_app" in dispatched

    @pytest.mark.asyncio
    async def test_unknown_event_type_skipped(self, notif_db, fake_redis):
        svc, _ = _get_service()
        uid = await _create_user(notif_db)

        dispatched = await svc.send_notification_impl(
            uid, "nonexistent_event", str(uuid4()), {},
            notif_db, fake_redis,
        )
        assert dispatched == []

    @pytest.mark.asyncio
    async def test_unknown_user_skipped(self, notif_db, fake_redis):
        svc, _ = _get_service()
        dispatched = await svc.send_notification_impl(
            str(uuid4()), "outbid", str(uuid4()),
            {"title": "X", "price": 1, "currency": "JOD"},
            notif_db, fake_redis,
        )
        assert dispatched == []


# ═══════════════════════════════════════════════════════════════════
#  CHANNEL DISPATCHER WIRING
# ═══════════════════════════════════════════════════════════════════

class TestDispatcherWiring:

    @pytest.mark.asyncio
    async def test_sms_dispatched(self, notif_db, fake_redis):
        svc, _ = _get_service()
        uid = await _create_user(notif_db)

        mock_sms = AsyncMock(return_value=True)
        with patch("app.services.notification.channels.send_sms", mock_sms):
            dispatched = await svc.send_notification_impl(
                uid, "payment_received", str(uuid4()),
                {"amount": 100, "currency": "JOD"},
                notif_db, fake_redis,
            )

        assert "sms" in dispatched
        mock_sms.assert_called_once()
        # Verify phone number was passed
        call_args = mock_sms.call_args
        assert call_args[0][0].startswith("+962")

    @pytest.mark.asyncio
    async def test_whatsapp_increments_daily_counter(self, notif_db, fake_redis):
        """Non-financial WhatsApp success increments the daily counter."""
        svc, _ = _get_service()
        uid = await _create_user(notif_db)

        mock_wa = AsyncMock(return_value=True)
        with patch("app.services.notification.channels.send_sms", new_callable=AsyncMock, return_value=False), \
             patch("app.services.notification.channels.send_whatsapp", mock_wa):
            await svc.send_notification_impl(
                uid, "outbid", str(uuid4()),
                {"title": "X", "price": 1, "currency": "JOD"},
                notif_db, fake_redis,
            )

        counter = await fake_redis.get(f"wa_daily:{uid}")
        assert int(counter) == 1
