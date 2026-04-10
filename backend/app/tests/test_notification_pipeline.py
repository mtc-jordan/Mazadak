"""
Tests for notification dispatch pipeline — FR-NOTIF-001 -> FR-NOTIF-012, PM-11.

6 tests:
  1. test_dedup_prevents_duplicate_notification  — Redis SET NX dedup
  2. test_financial_bypasses_preferences         — financial ignores opt-out
  3. test_fcm_stale_token_removed                — stale FCM token triggers removal task
  4. test_whatsapp_rate_limited_after_5_per_day   — 5/day/user limit for non-financial
  5. test_sms_falls_back_to_sns                  — Twilio failure -> SNS fallback
  6. test_all_20_templates_render_without_error   — all templates render with sample data
"""

from __future__ import annotations

import json
import sys
import threading
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import JSON, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.notification.models import (
    Notification,
    NotificationChannel,
    NotificationPreference,
)


# -- Fake Redis -------------------------------------------------------

class FakeRedis:
    """Minimal async Redis mock for notification dedup + rate limiting."""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}
        self._lock = threading.Lock()

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        with self._lock:
            if nx and key in self._store:
                return None  # SET NX returns None if key exists
            self._store[key] = str(value)
            if ex is not None:
                self._ttls[key] = ex
            return True

    async def get(self, key: str) -> str | None:
        with self._lock:
            return self._store.get(key)

    async def exists(self, key: str) -> int:
        with self._lock:
            return 1 if key in self._store else 0

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


# -- SQLite fixture ---------------------------------------------------

def _register_sqlite_functions(dbapi_conn, connection_record):
    import uuid as _uuid
    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(_uuid.uuid4()))
    dbapi_conn.create_function("now", 0, lambda: "2026-04-08T00:00:00")


@pytest.fixture
async def notif_db():
    """Async SQLite session with notification + user tables."""
    from sqlalchemy import event
    from app.core.database import Base
    from app.services.auth.models import User, UserKycDocument, RefreshToken
    from app.services.notification.models import Notification, NotificationPreference

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)

    # Patch JSONB -> Text for SQLite (keep patched for entire test)
    patch_targets = []
    jsonb_cols = [
        Notification.__table__.c.data,
        Notification.__table__.c.channels_sent,
        User.__table__.c.fcm_tokens,
    ]

    for col in jsonb_cols:
        patch_targets.append((col, col.type))
        col.type = JSON()

    # Also patch RefreshToken.device_info JSONB for SQLite
    rt_device_col = RefreshToken.__table__.c.device_info
    patch_targets.append((rt_device_col, rt_device_col.type))
    rt_device_col.type = JSON()

    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                UserKycDocument.__table__,
                RefreshToken.__table__,
                Notification.__table__,
                NotificationPreference.__table__,
            ],
        )

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    # Restore original column types after test
    for col, orig_type in patch_targets:
        col.type = orig_type
    await engine.dispose()


@pytest.fixture
def fake_redis():
    return FakeRedis()


# -- Helpers ----------------------------------------------------------

async def _create_user(db: AsyncSession, **overrides) -> str:
    from app.services.auth.models import User, UserRole, UserStatus, KYCStatus

    uid = overrides.pop("id", str(uuid4()))
    defaults = dict(
        id=uid,
        phone=f"+9627900{uuid4().hex[:5]}",
        full_name_ar="مستخدم",
        full_name="Test User",
        role=UserRole.BUYER,
        status=UserStatus.ACTIVE,
        kyc_status=KYCStatus.VERIFIED,
        ats_score=400,
        preferred_language="ar",
        strike_count=0,
        fcm_tokens=[],
        is_pro_seller=False,
    )
    defaults.update(overrides)
    user = User(**defaults)
    db.add(user)
    await db.commit()
    return uid


async def _create_preference(db: AsyncSession, user_id: str, **overrides) -> None:
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


async def _insert_notification(
    db: AsyncSession, user_id: str, event_type: str = "outbid", **overrides,
) -> Notification:
    defaults = dict(
        id=str(uuid4()),
        user_id=user_id,
        event_type=event_type,
        entity_id=str(uuid4()),
        entity_type="auction",
        title_en="Test Title",
        title_ar="عنوان تجريبي",
        body_en="Test body",
        body_ar="نص تجريبي",
        data={"test": True},
        channels_sent=[],
    )
    defaults.update(overrides)
    notif = Notification(**defaults)
    db.add(notif)
    await db.commit()
    return notif


# =====================================================================
#  TEST 1: Deduplication — Redis SET NX prevents duplicate
# =====================================================================

class TestDeduplication:

    @pytest.mark.asyncio
    async def test_dedup_prevents_duplicate_notification(self, notif_db, fake_redis):
        """Second queue_notification within 60s is deduplicated via Redis SET NX."""
        uid = await _create_user(notif_db)
        entity_id = str(uuid4())

        mock_redis_factory = AsyncMock(return_value=fake_redis)
        mock_tasks = MagicMock()

        with patch("app.core.redis.get_redis_client", mock_redis_factory), \
             patch.dict("sys.modules", {
                 "app.tasks.notification": mock_tasks,
                 "app.core.celery": MagicMock(),
             }):
            from app.services.notification import service

            # First call — should persist and dispatch
            await service.queue_notification(
                uid, "outbid", entity_id, "auction",
                {"title": "iPhone", "price": 500, "currency": "JOD"},
                notif_db,
            )
            # Second call — should be deduplicated (returns early)
            await service.queue_notification(
                uid, "outbid", entity_id, "auction",
                {"title": "iPhone", "price": 500, "currency": "JOD"},
                notif_db,
            )

        # Only 1 notification persisted in DB (second was deduplicated)
        result = await notif_db.execute(
            select(Notification).where(Notification.user_id == uid)
        )
        notifications = list(result.scalars().all())
        assert len(notifications) == 1


# =====================================================================
#  TEST 2: Financial bypasses user preferences
# =====================================================================

class TestFinancialBypassPreferences:

    @pytest.mark.asyncio
    async def test_financial_bypasses_preferences(self, notif_db):
        """Financial events bypass preference check -> all external channels."""
        from app.services.notification.service import _resolve_channels

        uid = await _create_user(notif_db)
        await _create_preference(
            notif_db, uid,
            push_enabled=False, sms_enabled=False, whatsapp_enabled=False,
        )

        # Non-financial: all disabled -> empty
        channels_non_fin = await _resolve_channels(uid, False, notif_db)
        assert NotificationChannel.PUSH not in channels_non_fin
        assert NotificationChannel.SMS not in channels_non_fin

        # Financial: bypasses preferences
        channels_fin = await _resolve_channels(uid, True, notif_db)
        assert NotificationChannel.PUSH in channels_fin
        assert NotificationChannel.SMS in channels_fin
        assert NotificationChannel.WHATSAPP in channels_fin


# =====================================================================
#  TEST 3: FCM stale token removed
# =====================================================================

class TestFCMStaleTokenRemoved:

    @pytest.mark.asyncio
    async def test_fcm_stale_token_triggers_removal(self, notif_db):
        """UnregisteredError on FCM send triggers remove_fcm_token.delay()."""
        uid = await _create_user(notif_db, fcm_tokens=["token_stale", "token_good"])
        notif = await _insert_notification(notif_db, uid)

        from app.services.auth.models import User
        user = await notif_db.get(User, uid)

        # Mock firebase_admin.messaging
        mock_messaging = MagicMock()
        UnregisteredError = type("UnregisteredError", (Exception,), {})
        mock_messaging.UnregisteredError = UnregisteredError
        mock_messaging.Notification = MagicMock()
        mock_messaging.Message = MagicMock()

        # First token (stale) raises UnregisteredError, second succeeds
        call_count = {"n": 0}
        def mock_send(message):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise UnregisteredError("stale")
        mock_messaging.send = mock_send

        mock_tasks = MagicMock()
        mock_firebase_admin = MagicMock()
        mock_firebase_admin.messaging = mock_messaging

        # Clear cached import
        sys.modules.pop("app.services.notification.dispatchers", None)

        with patch.dict("sys.modules", {
            "firebase_admin": mock_firebase_admin,
            "firebase_admin.messaging": mock_messaging,
            "app.tasks.notification": mock_tasks,
            "app.core.celery": MagicMock(),
        }):
            from app.services.notification.dispatchers import dispatch_fcm
            result = await dispatch_fcm(user, notif)

        assert result["status"] == "sent"  # second token succeeded
        assert result["token_last4"] == "good"
        # Stale token removal dispatched for the first (stale) token
        mock_tasks.remove_fcm_token.delay.assert_called_once_with(str(uid), "token_stale")


# =====================================================================
#  TEST 4: WhatsApp rate limited after 5/day
# =====================================================================

class TestWhatsAppRateLimit:

    @pytest.mark.asyncio
    async def test_whatsapp_rate_limited_after_5_per_day(self, notif_db, fake_redis):
        """Non-financial: WhatsApp blocked after 5 messages per day (incr > 5)."""
        from datetime import date

        uid = await _create_user(notif_db)
        notif = await _insert_notification(notif_db, uid, event_type="outbid")

        from app.services.auth.models import User
        user = await notif_db.get(User, uid)

        # Simulate 5 WhatsApp messages already sent today
        daily_key = f"notif:wa:daily:{uid}:{date.today()}"
        await fake_redis.set(daily_key, "5")

        # dispatch_whatsapp should incr to 6 and return False (> 5)
        mock_settings = MagicMock()
        mock_settings.WHATSAPP_ACCESS_TOKEN = "test_token"
        mock_settings.WHATSAPP_PHONE_NUMBER_ID = "12345"

        with patch("app.core.config.settings", mock_settings):
            from app.services.notification.dispatchers import dispatch_whatsapp
            result = await dispatch_whatsapp(user, notif, fake_redis)

        assert result == {"status": "rate_limited"}
        # Counter was incremented to 6
        assert int(await fake_redis.get(daily_key)) == 6


# =====================================================================
#  TEST 5: SMS falls back to SNS
# =====================================================================

class TestSMSFallback:

    @pytest.mark.asyncio
    async def test_sms_falls_back_to_sns(self, notif_db):
        """Twilio failure -> AWS SNS fallback succeeds."""
        uid = await _create_user(notif_db)
        notif = await _insert_notification(notif_db, uid, event_type="payment_captured")

        from app.services.auth.models import User
        user = await notif_db.get(User, uid)

        mock_twilio = AsyncMock(return_value=False)
        mock_sns = AsyncMock(return_value=True)

        with patch("app.services.notification.dispatchers._send_sms_twilio", mock_twilio), \
             patch("app.services.notification.dispatchers._send_sms_sns", mock_sns):
            from app.services.notification.dispatchers import dispatch_sms
            result = await dispatch_sms(user, notif)

        assert result == {"status": "sent_via_sns"}
        mock_twilio.assert_called_once()
        mock_sns.assert_called_once()

        # Verify body was truncated to 160 chars
        sms_body = mock_sns.call_args[0][1]
        assert len(sms_body) <= 160


# =====================================================================
#  TEST 6: All 20 templates render without error
# =====================================================================

class TestAllTemplatesRender:

    def test_all_20_templates_render_without_error(self):
        """All 20 templates render with sample data without raising."""
        from app.services.notification.templates import TEMPLATES, render_template

        assert len(TEMPLATES) == 20

        # Sample data that covers all possible {{variables}}
        sample_data = {
            "title": "iPhone 15 Pro",
            "amount": "500",
            "currency": "JOD",
            "price": "500",
            "deadline_hours": "48",
            "hours_remaining": "12",
            "hours": "72",
            "carrier": "Aramex",
            "tracking": "ARX123456",
            "tracking_number": "ARX123456",
            "reason": "Incomplete documents",
            "resolution": "refund_buyer",
            "retry_count": "2",
            "count": "1",
            "message": "System maintenance scheduled.",
        }

        for event_type, tmpl in TEMPLATES.items():
            rendered = render_template(event_type, sample_data)
            assert rendered is not None, f"Template {event_type} returned None"
            assert rendered.title_ar, f"Template {event_type} has empty title_ar"
            assert rendered.title_en, f"Template {event_type} has empty title_en"
            assert rendered.body_ar, f"Template {event_type} has empty body_ar"
            assert rendered.body_en, f"Template {event_type} has empty body_en"
            assert rendered.icon, f"Template {event_type} has empty icon"
            assert isinstance(rendered.is_financial, bool)
            # Verify Jinja2 interpolation happened (no {{ left)
            assert "{{" not in rendered.body_en, f"Template {event_type} has unrendered variable in body_en"
            assert "{{" not in rendered.body_ar, f"Template {event_type} has unrendered variable in body_ar"
