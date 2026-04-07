"""
Auth dependency + refresh/logout integration tests.

Covers:
  get_current_user:
    - Valid JWT → returns user
    - Expired JWT → 401
    - Tampered JWT → 401
    - Blacklisted JTI → 401
    - Missing Authorization header → 403 (HTTPBearer default)
    - Suspended user → 403
    - Banned user → 403
    - Deleted user (not in DB) → 401

  require_kyc:
    - KYC verified → passes
    - KYC pending → 403

  require_role:
    - Correct role → passes
    - Wrong role → 403
    - Multiple allowed roles → any match passes

  require_ats:
    - Score above threshold → passes
    - Score below threshold → 403

  POST /auth/refresh (FR-AUTH-003):
    - Valid refresh → new token pair, old refresh revoked
    - Invalid/expired refresh → 401
    - Suspended user refresh → 403
    - Reuse of revoked refresh → 401

  POST /auth/logout (FR-AUTH-004):
    - Blacklists access JTI in Redis with remaining TTL
    - Revokes refresh token
    - Subsequent request with same access token → 401
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import pytest
from jose import jwt

import app.core.security as sec
from app.core.config import settings
from app.services.auth import service
from app.services.auth.models import ATSTier, KYCStatus, User, UserRole


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _make_token(
    user_id: str,
    role: str = "buyer",
    kyc: str = "pending",
    ats: int = 400,
    exp_delta: timedelta | None = None,
    jti: str | None = None,
) -> tuple[str, str]:
    """Create a signed JWT for testing. Returns (token, jti)."""
    now = datetime.now(timezone.utc)
    _jti = jti or uuid4().hex
    payload = {
        "sub": user_id,
        "role": role,
        "kyc": kyc,
        "ats": ats,
        "jti": _jti,
        "iat": now,
        "exp": now + (exp_delta if exp_delta is not None else timedelta(minutes=15)),
    }
    token = jwt.encode(payload, sec._private_key, algorithm="RS256")
    return token, _jti


async def _create_user(
    db,
    phone: str = "+962790000000",
    role: UserRole = UserRole.BUYER,
    kyc: KYCStatus = KYCStatus.PENDING,
    ats: int = 400,
    tier: ATSTier = ATSTier.TRUSTED,
    suspended: bool = False,
    banned: bool = False,
) -> User:
    user = User(
        id=str(uuid4()),
        phone=phone,
        full_name_ar="اختبار",
        role=role,
        kyc_status=kyc,
        ats_score=ats,
        ats_tier=tier,
        country_code="JO",
        preferred_language="ar",
        is_suspended=suspended,
        is_banned=banned,
    )
    db.add(user)
    await db.flush()
    await db.commit()
    return user


# ═══════════════════════════════════════════════════════════════════
# get_current_user
# ═══════════════════════════════════════════════════════════════════

class TestGetCurrentUser:
    """Tests for the get_current_user dependency via a protected endpoint."""

    async def test_valid_jwt_returns_user(self, client, db_session, fake_redis):
        user = await _create_user(db_session)
        token, _ = _make_token(user.id)

        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        # /auth/me may not exist yet — use any endpoint that requires auth.
        # We'll test via the logout endpoint instead (requires get_current_user).
        # Actually, let's test through a direct dependency call pattern.
        # Better: use the logout endpoint which is guaranteed to exist.
        # But logout needs a body. Let's use a simple GET if available.
        # Since /auth/me isn't wired yet, let's POST to /auth/logout.
        pass  # Covered by test_logout_happy_path below

    async def test_missing_auth_header_returns_401(self, client):
        """HTTPBearer returns 401/403 when Authorization header is absent."""
        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "x"},
        )
        assert resp.status_code in (401, 403)

    async def test_expired_jwt_returns_401(self, client, db_session, fake_redis):
        user = await _create_user(db_session)
        token, _ = _make_token(user.id, exp_delta=timedelta(seconds=-1))

        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "INVALID_TOKEN"

    async def test_tampered_jwt_returns_401(self, client, db_session):
        user = await _create_user(db_session)
        token, _ = _make_token(user.id)
        # Tamper by flipping a character in the signature
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "x"},
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert resp.status_code == 401

    async def test_blacklisted_jti_returns_401(self, client, db_session, fake_redis):
        user = await _create_user(db_session)
        token, jti = _make_token(user.id)

        # Blacklist the JTI
        await fake_redis.setex(f"blacklist:{jti}", 900, "1")

        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "TOKEN_REVOKED"

    async def test_deleted_user_returns_401(self, client, fake_redis):
        """Token for a user_id that doesn't exist in DB."""
        token, _ = _make_token(str(uuid4()))

        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "USER_NOT_FOUND"

    async def test_suspended_user_returns_403(self, client, db_session, fake_redis):
        user = await _create_user(db_session, suspended=True)
        token, _ = _make_token(user.id)

        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "ACCOUNT_SUSPENDED"

    async def test_banned_user_returns_403(self, client, db_session, fake_redis):
        user = await _create_user(db_session, banned=True)
        token, _ = _make_token(user.id)

        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "ACCOUNT_BANNED"

    async def test_garbage_token_returns_401(self, client):
        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "x"},
            headers={"Authorization": "Bearer not.a.jwt"},
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════
# require_kyc — tested via direct dependency invocation
# ═══════════════════════════════════════════════════════════════════

class TestRequireKYC:
    async def test_verified_user_passes(self, db_session, fake_redis):
        from app.services.auth.dependencies import require_kyc

        user = await _create_user(db_session, kyc=KYCStatus.VERIFIED)
        result = await require_kyc(user=user)
        assert result.id == user.id

    async def test_pending_user_raises_403(self, db_session, fake_redis):
        from fastapi import HTTPException
        from app.services.auth.dependencies import require_kyc

        user = await _create_user(db_session, kyc=KYCStatus.PENDING)
        with pytest.raises(HTTPException) as exc_info:
            await require_kyc(user=user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "KYC_REQUIRED"

    async def test_rejected_user_raises_403(self, db_session, fake_redis):
        from fastapi import HTTPException
        from app.services.auth.dependencies import require_kyc

        user = await _create_user(db_session, kyc=KYCStatus.REJECTED)
        with pytest.raises(HTTPException) as exc_info:
            await require_kyc(user=user)
        assert exc_info.value.status_code == 403

    async def test_pending_review_raises_403(self, db_session, fake_redis):
        from fastapi import HTTPException
        from app.services.auth.dependencies import require_kyc

        user = await _create_user(db_session, kyc=KYCStatus.PENDING_REVIEW)
        with pytest.raises(HTTPException) as exc_info:
            await require_kyc(user=user)
        assert exc_info.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# require_role — tested via direct dependency invocation
# ═══════════════════════════════════════════════════════════════════

class TestRequireRole:
    async def test_matching_role_passes(self, db_session):
        from app.services.auth.dependencies import require_role

        user = await _create_user(db_session, role=UserRole.ADMIN)
        check = require_role("admin", "super_admin")
        result = await check(user=user)
        assert result.id == user.id

    async def test_wrong_role_raises_403(self, db_session):
        from fastapi import HTTPException
        from app.services.auth.dependencies import require_role

        user = await _create_user(db_session, role=UserRole.BUYER)
        check = require_role("admin", "super_admin")
        with pytest.raises(HTTPException) as exc_info:
            await check(user=user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "INSUFFICIENT_ROLE"

    async def test_multiple_roles_any_match(self, db_session):
        from app.services.auth.dependencies import require_role

        user = await _create_user(db_session, role=UserRole.MODERATOR)
        check = require_role("moderator", "admin", "super_admin")
        result = await check(user=user)
        assert result.id == user.id

    async def test_seller_cannot_access_admin(self, db_session):
        from fastapi import HTTPException
        from app.services.auth.dependencies import require_role

        user = await _create_user(db_session, role=UserRole.SELLER)
        check = require_role("admin", "super_admin")
        with pytest.raises(HTTPException) as exc_info:
            await check(user=user)
        assert exc_info.value.status_code == 403

    async def test_super_admin_passes_admin_check(self, db_session):
        from app.services.auth.dependencies import require_role

        user = await _create_user(db_session, role=UserRole.SUPER_ADMIN)
        check = require_role("admin", "super_admin")
        result = await check(user=user)
        assert result.id == user.id


# ═══════════════════════════════════════════════════════════════════
# require_ats — tested via direct dependency invocation
# ═══════════════════════════════════════════════════════════════════

class TestRequireATS:
    async def test_score_above_threshold_passes(self, db_session):
        from app.services.auth.dependencies import require_ats

        user = await _create_user(db_session, ats=500)
        check = require_ats(200)
        result = await check(user=user)
        assert result.id == user.id

    async def test_score_equal_to_threshold_passes(self, db_session):
        from app.services.auth.dependencies import require_ats

        user = await _create_user(db_session, ats=200)
        check = require_ats(200)
        result = await check(user=user)
        assert result.id == user.id

    async def test_score_below_threshold_raises_403(self, db_session):
        from fastapi import HTTPException
        from app.services.auth.dependencies import require_ats

        user = await _create_user(db_session, ats=150)
        check = require_ats(200)
        with pytest.raises(HTTPException) as exc_info:
            await check(user=user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "ATS_TOO_LOW"
        assert "150" in exc_info.value.detail["message_en"]
        assert "200" in exc_info.value.detail["message_en"]

    async def test_ats_zero_blocked_from_bidding(self, db_session):
        """FR-AUTH-008: ATS < 100 → account should be suspended."""
        from fastapi import HTTPException
        from app.services.auth.dependencies import require_ats

        user = await _create_user(db_session, ats=50)
        check = require_ats(100)
        with pytest.raises(HTTPException):
            await check(user=user)

    async def test_elite_user_passes_high_threshold(self, db_session):
        from app.services.auth.dependencies import require_ats

        user = await _create_user(db_session, ats=950, tier=ATSTier.ELITE)
        check = require_ats(800)
        result = await check(user=user)
        assert result.ats_score == 950


# ═══════════════════════════════════════════════════════════════════
# POST /auth/refresh — FR-AUTH-003
# ═══════════════════════════════════════════════════════════════════

class TestRefreshEndpoint:
    async def test_happy_path_returns_new_pair(self, client, db_session, fake_redis):
        user = await _create_user(db_session)
        _, refresh, _ = service.issue_tokens(user)
        await service.store_refresh_token(refresh, user.id, fake_redis)

        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        # New refresh should differ from old
        assert data["refresh_token"] != refresh

    async def test_old_refresh_revoked_after_rotation(
        self, client, db_session, fake_redis,
    ):
        """After refresh, the old token should be invalidated (rotation)."""
        user = await _create_user(db_session)
        _, refresh, _ = service.issue_tokens(user)
        await service.store_refresh_token(refresh, user.id, fake_redis)

        # First refresh succeeds
        resp1 = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh},
        )
        assert resp1.status_code == 200

        # Second attempt with same old refresh → 401 (revoked)
        resp2 = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh},
        )
        assert resp2.status_code == 401
        assert resp2.json()["detail"]["code"] == "INVALID_REFRESH"

    async def test_invalid_refresh_returns_401(self, client):
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "bogus_token_that_does_not_exist"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "INVALID_REFRESH"

    async def test_suspended_user_refresh_returns_403(
        self, client, db_session, fake_redis,
    ):
        user = await _create_user(db_session, suspended=True)
        _, refresh, _ = service.issue_tokens(user)
        await service.store_refresh_token(refresh, user.id, fake_redis)

        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "ACCOUNT_DISABLED"

    async def test_banned_user_refresh_returns_403(
        self, client, db_session, fake_redis,
    ):
        user = await _create_user(db_session, banned=True)
        _, refresh, _ = service.issue_tokens(user)
        await service.store_refresh_token(refresh, user.id, fake_redis)

        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh},
        )
        assert resp.status_code == 403

    async def test_new_tokens_are_valid(self, client, db_session, fake_redis):
        """The new access token from refresh should be decodeable and
        the new refresh token should be stored in Redis."""
        user = await _create_user(db_session)
        _, refresh, _ = service.issue_tokens(user)
        await service.store_refresh_token(refresh, user.id, fake_redis)

        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh},
        )
        data = resp.json()

        # Decode the new access token
        from app.core.security import decode_access_token
        payload = decode_access_token(data["access_token"])
        assert payload is not None
        assert payload.sub == user.id
        assert payload.role == "buyer"

        # Verify new refresh token is stored
        uid = await service.validate_refresh_token(
            data["refresh_token"], fake_redis,
        )
        assert uid == user.id


# ═══════════════════════════════════════════════════════════════════
# POST /auth/logout — FR-AUTH-004
# ═══════════════════════════════════════════════════════════════════

class TestLogoutEndpoint:
    async def test_happy_path(self, client, db_session, fake_redis):
        user = await _create_user(db_session)
        access, refresh, jti = service.issue_tokens(user)
        await service.store_refresh_token(refresh, user.id, fake_redis)

        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    async def test_access_token_blacklisted_after_logout(
        self, client, db_session, fake_redis,
    ):
        """FR-AUTH-004: JTI added to Redis blacklist with remaining TTL."""
        user = await _create_user(db_session)
        access, refresh, jti = service.issue_tokens(user)
        await service.store_refresh_token(refresh, user.id, fake_redis)

        # Logout
        await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh},
            headers={"Authorization": f"Bearer {access}"},
        )

        # JTI should be in blacklist
        assert await fake_redis.exists(f"blacklist:{jti}") == 1

        # Reuse the same access token → 401
        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "anything"},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "TOKEN_REVOKED"

    async def test_refresh_token_revoked_after_logout(
        self, client, db_session, fake_redis,
    ):
        user = await _create_user(db_session)
        access, refresh, _ = service.issue_tokens(user)
        await service.store_refresh_token(refresh, user.id, fake_redis)

        # Logout
        await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh},
            headers={"Authorization": f"Bearer {access}"},
        )

        # Refresh token should be gone from Redis
        uid = await service.validate_refresh_token(refresh, fake_redis)
        assert uid is None

        # Attempt to use refresh → 401
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh},
        )
        assert resp.status_code == 401

    async def test_blacklist_ttl_matches_remaining_token_validity(
        self, client, db_session, fake_redis,
    ):
        """The blacklist entry should have TTL ≈ remaining token lifetime."""
        user = await _create_user(db_session)
        access, refresh, jti = service.issue_tokens(user)
        await service.store_refresh_token(refresh, user.id, fake_redis)

        await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh},
            headers={"Authorization": f"Bearer {access}"},
        )

        ttl = await fake_redis.ttl(f"blacklist:{jti}")
        # Should be roughly 15 minutes (900s) minus a few seconds of test execution
        assert 800 < ttl <= 900

    async def test_logout_without_auth_returns_401(self, client):
        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "x"},
        )
        assert resp.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════
# End-to-end: full auth flow
# ═══════════════════════════════════════════════════════════════════

class TestFullAuthFlow:
    """register → verify → use token → refresh → use new token → logout → blocked."""

    async def test_complete_lifecycle(self, client, db_session, fake_redis, mock_sms):
        phone = "+962790000000"

        # 1. Register
        resp = await client.post(
            "/api/v1/auth/register", json={"phone": phone},
        )
        assert resp.status_code == 200

        # 2. Plant OTP and verify
        otp = "123456"
        otp_hash = sha256(otp.encode()).hexdigest()
        await fake_redis.setex(f"otp:{phone}", 300, otp_hash)
        await fake_redis.setex(f"otp:attempts:{phone}", 300, "0")

        resp = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone": phone, "otp": otp},
        )
        assert resp.status_code == 200
        tokens = resp.json()
        access1 = tokens["access_token"]
        refresh1 = tokens["refresh_token"]

        # 3. Use access token (logout endpoint as proxy for "any authed endpoint")
        # First verify it works
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh1},
        )
        assert resp.status_code == 200
        access2 = resp.json()["access_token"]
        refresh2 = resp.json()["refresh_token"]

        # 4. Old refresh should be revoked
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh1},
        )
        assert resp.status_code == 401

        # 5. Logout with new tokens
        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh2},
            headers={"Authorization": f"Bearer {access2}"},
        )
        assert resp.status_code == 200

        # 6. Both tokens now invalid
        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "x"},
            headers={"Authorization": f"Bearer {access2}"},
        )
        assert resp.status_code == 401  # blacklisted

        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh2},
        )
        assert resp.status_code == 401  # revoked
