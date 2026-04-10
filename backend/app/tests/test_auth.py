"""
Auth endpoint tests — FR-AUTH-001, FR-AUTH-015.

Covers:
  - Happy path: register → OTP sent, verify → user created + JWT pair
  - Phone validation: E.164, allowed countries, invalid formats
  - Duplicate phone: returns existing user on verify
  - Expired OTP: returns 401
  - Wrong OTP with attempt tracking: returns remaining attempts
  - Lockout after 3 failed attempts: returns 429 for 15 minutes
  - Rate limit: 5 OTP requests per phone per hour
  - JWT pair structure: access_token + refresh_token + user object
"""

from __future__ import annotations

import secrets
from hashlib import sha256
from unittest.mock import AsyncMock, patch

import pytest

from app.services.auth import service
from app.services.auth.schemas import RegisterRequest, VerifyOTPRequest

# ═══════════════════════════════════════════════════════════════════
# Schema validation tests (phonenumbers library)
# ═══════════════════════════════════════════════════════════════════


class TestPhoneValidation:
    def test_valid_jordan_number(self):
        req = RegisterRequest(phone="+962790000000")
        assert req.phone == "+962790000000"

    def test_valid_saudi_number(self):
        req = RegisterRequest(phone="+966501234567")
        assert req.phone == "+966501234567"

    def test_valid_uae_number(self):
        req = RegisterRequest(phone="+971501234567")
        assert req.phone == "+971501234567"

    def test_rejects_us_number(self):
        with pytest.raises(ValueError, match="Jordan.*Saudi.*UAE"):
            RegisterRequest(phone="+12025551234")

    def test_rejects_invalid_format(self):
        with pytest.raises(ValueError):
            RegisterRequest(phone="0790000000")

    def test_rejects_too_short(self):
        with pytest.raises(ValueError):
            RegisterRequest(phone="+96279")

    def test_normalizes_to_e164(self):
        # phonenumbers should normalize
        req = RegisterRequest(phone="+962 79 000 0000")
        assert req.phone.startswith("+962")
        assert " " not in req.phone

    def test_otp_must_be_6_digits(self):
        with pytest.raises(ValueError):
            VerifyOTPRequest(phone="+962790000000", otp="12345")

    def test_otp_rejects_non_numeric(self):
        with pytest.raises(ValueError):
            VerifyOTPRequest(phone="+962790000000", otp="abcdef")


# ═══════════════════════════════════════════════════════════════════
# Service-level unit tests (no HTTP, direct function calls)
# ═══════════════════════════════════════════════════════════════════


class TestSendOTP:
    async def test_happy_path(self, fake_redis, mock_sms):
        success, err, detail = await service.send_otp("+962790000000", fake_redis)

        assert success is True
        assert err is None
        # OTP hash stored in Redis
        stored = await fake_redis.get("otp:+962790000000")
        assert stored is not None
        assert len(stored) == 64  # SHA-256 hex
        # Attempt counter initialized
        attempts = await fake_redis.get("otp:attempts:+962790000000")
        assert attempts == "0"
        # SMS sent
        mock_sms.assert_called_once()

    async def test_rate_limit_after_5_requests(self, fake_redis, mock_sms):
        phone = "+962790000001"
        for i in range(5):
            success, _, _ = await service.send_otp(phone, fake_redis)
            assert success is True

        # 6th request should be rate limited
        success, err, detail = await service.send_otp(phone, fake_redis)
        assert success is False
        assert err == "OTP_RATE_LIMITED"
        assert detail["code"] == "OTP_RATE_LIMITED"

    async def test_lockout_blocks_send(self, fake_redis, mock_sms):
        phone = "+962790000002"
        # Simulate lockout
        await fake_redis.setex(f"otp:lockout:{phone}", 900, "1")

        success, err, detail = await service.send_otp(phone, fake_redis)
        assert success is False
        assert err == "OTP_LOCKED_OUT"


class TestVerifyOTP:
    async def _store_otp(self, redis, phone: str, otp: str = "123456"):
        """Helper: store a hashed OTP in fake Redis."""
        otp_hash = sha256(otp.encode()).hexdigest()
        await redis.setex(f"otp:{phone}", 300, otp_hash)
        await redis.setex(f"otp:attempts:{phone}", 300, "0")
        return otp

    async def test_happy_path(self, fake_redis):
        phone = "+962790000000"
        otp = await self._store_otp(fake_redis, phone)

        success, err, detail = await service.verify_otp(phone, otp, fake_redis)
        assert success is True
        assert err is None
        # OTP and attempts cleaned up
        assert await fake_redis.get(f"otp:{phone}") is None
        assert await fake_redis.get(f"otp:attempts:{phone}") is None

    async def test_wrong_otp_returns_attempts_remaining(self, fake_redis):
        phone = "+962790000000"
        await self._store_otp(fake_redis, phone, "123456")

        success, err, detail = await service.verify_otp(phone, "999999", fake_redis)
        assert success is False
        assert err == "INVALID_OTP"
        assert detail["attempts_remaining"] == 2  # 3 max - 1 used

    async def test_second_wrong_attempt(self, fake_redis):
        phone = "+962790000000"
        await self._store_otp(fake_redis, phone, "123456")

        await service.verify_otp(phone, "999999", fake_redis)  # attempt 1
        success, err, detail = await service.verify_otp(phone, "888888", fake_redis)  # attempt 2
        assert success is False
        assert detail["attempts_remaining"] == 1

    async def test_lockout_after_3_wrong_attempts(self, fake_redis):
        phone = "+962790000003"
        await self._store_otp(fake_redis, phone, "123456")

        await service.verify_otp(phone, "111111", fake_redis)  # 1
        await service.verify_otp(phone, "222222", fake_redis)  # 2
        await service.verify_otp(phone, "333333", fake_redis)  # 3

        # 4th attempt triggers lockout
        success, err, detail = await service.verify_otp(phone, "444444", fake_redis)
        assert success is False
        assert err == "OTP_LOCKED_OUT"
        assert detail["retry_after_seconds"] == 900

        # Lockout flag set
        assert await fake_redis.get(f"otp:lockout:{phone}") == "1"
        # OTP cleaned up
        assert await fake_redis.get(f"otp:{phone}") is None

    async def test_expired_otp(self, fake_redis):
        phone = "+962790000004"
        # Don't store any OTP — simulates expiry

        success, err, detail = await service.verify_otp(phone, "123456", fake_redis)
        assert success is False
        assert err == "OTP_EXPIRED"

    async def test_locked_out_phone_cannot_verify(self, fake_redis):
        phone = "+962790000005"
        await self._store_otp(fake_redis, phone, "123456")
        await fake_redis.setex(f"otp:lockout:{phone}", 900, "1")

        success, err, detail = await service.verify_otp(phone, "123456", fake_redis)
        assert success is False
        assert err == "OTP_LOCKED_OUT"


class TestGetOrCreateUser:
    async def test_creates_new_user(self, db_session):
        user, is_new = await service.get_or_create_user("+962790000000", db_session)
        assert is_new is True
        assert user.phone == "+962790000000"
        assert user.kyc_status.value == "not_started"
        assert user.ats_score == 400
        assert user.ats_tier.value == "trusted"
        assert user.role.value == "buyer"
        assert user.phone_verified is True
        assert user.last_login_at is not None

    async def test_returns_existing_user(self, db_session):
        user1, new1 = await service.get_or_create_user("+962790000000", db_session)
        user2, new2 = await service.get_or_create_user("+962790000000", db_session)
        assert new1 is True
        assert new2 is False
        assert user1.id == user2.id

    async def test_banned_user_raises_error(self, db_session):
        from app.services.auth.models import User, UserRole, UserStatus, KYCStatus
        from uuid import uuid4

        user = User(
            id=str(uuid4()),
            phone="+962790099099",
            role=UserRole.BUYER,
            status=UserStatus.BANNED,
            kyc_status=KYCStatus.NOT_STARTED,
            ats_score=400,
            preferred_language="ar",
            fcm_tokens=[],
            is_pro_seller=False,
        )
        db_session.add(user)
        await db_session.flush()

        with pytest.raises(ValueError, match="ACCOUNT_BANNED"):
            await service.get_or_create_user("+962790099099", db_session)


class TestIssueTokens:
    async def test_returns_token_triple(self, db_session):
        user, _ = await service.get_or_create_user("+962790000000", db_session)
        access, refresh, jti = service.issue_tokens(user)
        assert isinstance(access, str)
        assert len(access) > 50  # JWT is long
        assert isinstance(refresh, str)
        assert len(refresh) == 64  # uuid4().hex * 2
        assert isinstance(jti, str)

    async def test_refresh_token_stored_in_db(self, db_session):
        user, _ = await service.get_or_create_user("+962790000000", db_session)
        _, refresh, _ = service.issue_tokens(user)
        await service.store_refresh_token(refresh, user.id, db_session)

        uid = await service.validate_refresh_token(refresh, db_session)
        assert uid == user.id

    async def test_validate_refresh_token(self, db_session):
        user, _ = await service.get_or_create_user("+962790000000", db_session)
        _, refresh, _ = service.issue_tokens(user)
        await service.store_refresh_token(refresh, user.id, db_session)

        uid = await service.validate_refresh_token(refresh, db_session)
        assert uid == user.id

    async def test_invalid_refresh_returns_none(self, db_session):
        uid = await service.validate_refresh_token("bogus_token", db_session)
        assert uid is None


# ═══════════════════════════════════════════════════════════════════
# Integration tests (HTTP endpoints via test client)
# ═══════════════════════════════════════════════════════════════════


class TestRegisterEndpoint:
    async def test_happy_path(self, client, mock_sms):
        resp = await client.post(
            "/api/v1/auth/register",
            json={"phone": "+962790000000"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["otp_sent"] is True

    async def test_invalid_phone_returns_422(self, client, mock_sms):
        resp = await client.post(
            "/api/v1/auth/register",
            json={"phone": "not_a_phone"},
        )
        assert resp.status_code == 422

    async def test_us_phone_returns_422(self, client, mock_sms):
        resp = await client.post(
            "/api/v1/auth/register",
            json={"phone": "+12025551234"},
        )
        assert resp.status_code == 422

    async def test_rate_limit_returns_429(self, client, fake_redis, mock_sms):
        phone = "+962790000099"
        # Pre-fill rate counter to 5 (simulates 5 prior requests)
        await fake_redis.set(f"rate:otp:{phone}", "5")
        await fake_redis.expire(f"rate:otp:{phone}", 3600)

        resp = await client.post(
            "/api/v1/auth/register",
            json={"phone": phone},
        )
        assert resp.status_code == 429
        assert resp.json()["detail"]["code"] == "OTP_RATE_LIMITED"


class TestVerifyOTPEndpoint:
    async def _register_and_get_otp(self, client, fake_redis, phone: str) -> str:
        """Register and extract OTP from Redis (hash → we planted it)."""
        # Plant a known OTP directly
        otp = "654321"
        otp_hash = sha256(otp.encode()).hexdigest()
        await fake_redis.setex(f"otp:{phone}", 300, otp_hash)
        await fake_redis.setex(f"otp:attempts:{phone}", 300, "0")
        return otp

    async def test_happy_path_creates_user_and_returns_tokens(
        self, client, fake_redis, mock_sms,
    ):
        phone = "+962790000000"
        otp = await self._register_and_get_otp(client, fake_redis, phone)

        resp = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone": phone, "otp": otp},
        )
        assert resp.status_code == 200
        data = resp.json()

        # JWT pair
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data

        # User object
        user = data["user"]
        assert user["role"] == "buyer"
        assert user["kyc_status"] == "not_started"
        assert user["ats_score"] == 400
        assert user["ats_tier"] == "trusted"
        # Phone should be masked
        assert "X" in user["phone"]

    async def test_duplicate_phone_returns_existing_user(
        self, client, fake_redis, db_session, mock_sms,
    ):
        phone = "+962790000000"

        # First verify — creates user
        otp = await self._register_and_get_otp(client, fake_redis, phone)
        resp1 = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone": phone, "otp": otp},
        )
        user_id_1 = resp1.json()["user"]["id"]

        # Second verify — same phone, same user
        otp2 = await self._register_and_get_otp(client, fake_redis, phone)
        resp2 = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone": phone, "otp": otp2},
        )
        assert resp2.status_code == 200
        user_id_2 = resp2.json()["user"]["id"]
        assert user_id_1 == user_id_2

    async def test_wrong_otp_returns_401_with_attempts(
        self, client, fake_redis, mock_sms,
    ):
        phone = "+962790000010"
        await self._register_and_get_otp(client, fake_redis, phone)

        resp = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone": phone, "otp": "000000"},
        )
        assert resp.status_code == 401
        data = resp.json()["detail"]
        assert data["code"] == "INVALID_OTP"
        assert data["attempts_remaining"] == 2

    async def test_expired_otp_returns_401(self, client, fake_redis, mock_sms):
        resp = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone": "+962790000020", "otp": "123456"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "OTP_EXPIRED"

    async def test_lockout_after_3_failures_returns_429(
        self, client, fake_redis, mock_sms,
    ):
        phone = "+962790000030"
        await self._register_and_get_otp(client, fake_redis, phone)

        for otp in ["111111", "222222", "333333"]:
            await client.post(
                "/api/v1/auth/verify-otp",
                json={"phone": phone, "otp": otp},
            )

        # 4th attempt → lockout
        resp = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone": phone, "otp": "444444"},
        )
        assert resp.status_code == 429
        assert resp.json()["detail"]["code"] == "OTP_LOCKED_OUT"

    async def test_locked_out_phone_stays_locked(
        self, client, fake_redis, mock_sms,
    ):
        phone = "+962790000040"
        await fake_redis.setex(f"otp:lockout:{phone}", 900, "1")

        # Even with correct OTP planted, should be blocked
        otp = await self._register_and_get_otp(client, fake_redis, phone)
        resp = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone": phone, "otp": otp},
        )
        assert resp.status_code == 429
        assert resp.json()["detail"]["code"] == "OTP_LOCKED_OUT"
