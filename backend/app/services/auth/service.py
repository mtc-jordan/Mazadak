"""
Auth business logic — SDD §3.1, FR-AUTH-001, FR-AUTH-015.

Handles: phone OTP registration/login, JWT issuance/refresh,
         OTP rate limiting, attempt tracking, lockout enforcement.

Redis key layout (SDD §4.3):
  otp:{phone}            — SHA-256(OTP), STR, TTL 5min
  otp:attempts:{phone}   — verify attempt counter, STR, TTL 5min
  otp:lockout:{phone}    — lockout flag, STR, TTL 15min
  rate:otp:{phone}       — hourly OTP request counter, STR, TTL 1h
  blacklist:{jti}        — "1", STR, TTL = remaining JWT validity
"""

from __future__ import annotations

import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token
from app.services.auth.models import (
    KYCStatus, RefreshToken, User, UserRole, UserStatus,
)
from app.services.auth.sms import send_sms

logger = logging.getLogger(__name__)

# ── Redis key prefixes ──────────────────────────────────────────
OTP_KEY = "otp:{phone}"
OTP_ATTEMPTS_KEY = "otp:attempts:{phone}"
OTP_LOCKOUT_KEY = "otp:lockout:{phone}"
OTP_RATE_KEY = "rate:otp:{phone}"
BLACKLIST_KEY = "blacklist:{jti}"


def _phone_last4(phone: str) -> str:
    """Return last 4 digits for structured logging (PII-safe)."""
    return phone[-4:] if len(phone) >= 4 else phone


# ═══════════════════════════════════════════════════════════════════
# OTP — Send
# ═══════════════════════════════════════════════════════════════════


async def check_otp_rate_limit(phone: str, redis: Redis) -> tuple[bool, int | None]:
    """Check if phone has exceeded 5 OTP requests/hour (FR-AUTH-015).

    Returns (allowed, retry_after_seconds).
    """
    key = OTP_RATE_KEY.format(phone=phone)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 3600)

    if count > settings.OTP_MAX_REQUESTS_PER_HOUR:
        ttl = await redis.ttl(key)
        return False, max(ttl, 0)

    return True, None


async def check_otp_lockout(phone: str, redis: Redis) -> tuple[bool, int | None]:
    """Check if phone is in OTP lockout (FR-AUTH-001 alt flow A6.2).

    Returns (locked_out, retry_after_seconds).
    """
    key = OTP_LOCKOUT_KEY.format(phone=phone)
    ttl = await redis.ttl(key)
    if ttl > 0:
        return True, ttl
    return False, None


async def send_otp(phone: str, redis: Redis) -> tuple[bool, str | None, dict | None]:
    """Generate OTP, hash it, store in Redis, send via SMS.

    Returns (success, error_code, error_detail).
    """
    last4 = _phone_last4(phone)

    # Check lockout first
    locked, lockout_ttl = await check_otp_lockout(phone, redis)
    if locked:
        logger.info("otp_send_blocked phone_last4=%s reason=lockout", last4)
        return False, "OTP_LOCKED_OUT", {
            "code": "OTP_LOCKED_OUT",
            "message_en": "Account locked due to too many failed attempts. Try again later.",
            "message_ar": "تم قفل الحساب بسبب محاولات فاشلة كثيرة. حاول لاحقاً.",
            "retry_after_seconds": lockout_ttl,
        }

    # Check rate limit (5 per hour)
    allowed, rate_ttl = await check_otp_rate_limit(phone, redis)
    if not allowed:
        logger.info("otp_send_blocked phone_last4=%s reason=rate_limit", last4)
        return False, "OTP_RATE_LIMITED", {
            "code": "OTP_RATE_LIMITED",
            "message_en": "Too many OTP requests. Try again later.",
            "message_ar": "طلبات كثيرة لرمز التحقق. حاول لاحقاً.",
            "retry_after_seconds": rate_ttl,
        }

    # Generate 6-digit OTP (zero-padded)
    otp = f"{secrets.randbelow(1000000):06d}"
    otp_hash = sha256(otp.encode()).hexdigest()

    # Store hash in Redis with 5-min TTL
    otp_key = OTP_KEY.format(phone=phone)
    await redis.setex(otp_key, settings.OTP_EXPIRE_SECONDS, otp_hash)

    # Reset attempt counter for this OTP
    attempts_key = OTP_ATTEMPTS_KEY.format(phone=phone)
    await redis.setex(attempts_key, settings.OTP_EXPIRE_SECONDS, "0")

    # Send SMS (Twilio primary, SNS fallback)
    message = f"MZADAK: Your verification code is: {otp}"
    sent = await send_sms(phone, message)
    if not sent:
        logger.error("otp_sms_failed phone_last4=%s providers=all", last4)

    logger.info("otp_sent phone_last4=%s", last4)
    return True, None, None


# ═══════════════════════════════════════════════════════════════════
# OTP — Verify
# ═══════════════════════════════════════════════════════════════════


async def verify_otp(
    phone: str, otp: str, redis: Redis,
) -> tuple[bool, str | None, dict | None]:
    """Verify OTP against stored hash using constant-time comparison.

    FR-AUTH-001: Max 3 attempts, then 15-min lockout.
    Returns (success, error_code, error_detail).
    """
    last4 = _phone_last4(phone)

    # Check lockout
    locked, lockout_ttl = await check_otp_lockout(phone, redis)
    if locked:
        return False, "OTP_LOCKED_OUT", {
            "code": "OTP_LOCKED_OUT",
            "message_en": "Account locked due to too many failed attempts. Try again later.",
            "message_ar": "تم قفل الحساب بسبب محاولات فاشلة كثيرة. حاول لاحقاً.",
            "retry_after_seconds": lockout_ttl,
        }

    otp_key = OTP_KEY.format(phone=phone)
    stored_hash = await redis.get(otp_key)
    if not stored_hash:
        return False, "OTP_EXPIRED", {
            "code": "OTP_EXPIRED",
            "message_en": "OTP has expired. Please request a new one.",
            "message_ar": "انتهت صلاحية رمز التحقق. يرجى طلب رمز جديد.",
        }

    # Increment attempt counter
    attempts_key = OTP_ATTEMPTS_KEY.format(phone=phone)
    attempts = await redis.incr(attempts_key)

    # Check if max attempts exceeded → lockout
    if attempts > settings.OTP_MAX_VERIFY_ATTEMPTS:
        lockout_key = OTP_LOCKOUT_KEY.format(phone=phone)
        await redis.setex(lockout_key, settings.OTP_LOCKOUT_SECONDS, "1")
        await redis.delete(otp_key, attempts_key)
        logger.warning("otp_lockout phone_last4=%s attempts=%d", last4, attempts)
        return False, "OTP_LOCKED_OUT", {
            "code": "OTP_LOCKED_OUT",
            "message_en": "Too many failed attempts. Locked for 15 minutes.",
            "message_ar": "محاولات فاشلة كثيرة. تم القفل لمدة 15 دقيقة.",
            "retry_after_seconds": settings.OTP_LOCKOUT_SECONDS,
        }

    # Constant-time comparison (prevents timing attacks)
    otp_hash = sha256(otp.encode()).hexdigest()
    stored = stored_hash if isinstance(stored_hash, str) else stored_hash.decode()
    if not hmac.compare_digest(otp_hash, stored):
        remaining = settings.OTP_MAX_VERIFY_ATTEMPTS - attempts
        logger.info("otp_invalid phone_last4=%s remaining=%d", last4, remaining)
        return False, "INVALID_OTP", {
            "code": "INVALID_OTP",
            "message_en": f"Invalid OTP. {remaining} attempt(s) remaining.",
            "message_ar": f"رمز التحقق غير صحيح. متبقي {remaining} محاولة.",
            "attempts_remaining": remaining,
        }

    # Success — clean up Redis
    await redis.delete(otp_key, attempts_key)
    logger.info("otp_verified phone_last4=%s", last4)

    return True, None, None


# ═══════════════════════════════════════════════════════════════════
# User management
# ═══════════════════════════════════════════════════════════════════


async def get_or_create_user(phone: str, db: AsyncSession) -> tuple[User, bool]:
    """Load existing user or create a new one with SELECT FOR UPDATE.

    Returns (user, is_new).
    Raises ValueError if user is banned.
    """
    # SELECT FOR UPDATE prevents race on concurrent OTP verifies
    result = await db.execute(
        select(User).where(User.phone == phone).with_for_update()
    )
    user = result.scalar_one_or_none()

    if user:
        # Check banned status
        if user.is_banned:
            raise ValueError("ACCOUNT_BANNED")

        # Update last_login_at
        user.last_login_at = datetime.now(timezone.utc)
        user.phone_verified = True
        await db.flush()
        return user, False

    user = User(
        id=str(uuid4()),
        phone=phone,
        phone_verified=True,
        role=UserRole.BUYER,
        status=UserStatus.PENDING_KYC,
        kyc_status=KYCStatus.NOT_STARTED,
        ats_score=400,
        preferred_language="ar",
        last_login_at=datetime.now(timezone.utc),
        fcm_tokens=[],
        is_pro_seller=False,
    )
    db.add(user)
    await db.flush()
    return user, True


# ═══════════════════════════════════════════════════════════════════
# Token issuance & management (DB-based refresh tokens)
# ═══════════════════════════════════════════════════════════════════


def issue_tokens(user: User) -> tuple[str, str, str]:
    """Create RS256 access token (15min) + random refresh token.

    Returns (access_token, refresh_token, jti).
    """
    access_token, jti = create_access_token(
        user_id=user.id,
        role=user.role.value if hasattr(user.role, "value") else user.role,
        kyc_status=(
            user.kyc_status.value
            if hasattr(user.kyc_status, "value")
            else user.kyc_status
        ),
        ats_score=user.ats_score,
    )
    refresh_token = create_refresh_token()
    return access_token, refresh_token, jti


async def store_refresh_token(
    refresh_token: str, user_id: str, db: AsyncSession,
    device_info: dict | None = None,
) -> None:
    """Store SHA-256(refresh_token) in refresh_tokens table."""
    token_hash = sha256(refresh_token.encode()).hexdigest()
    rt = RefreshToken(
        id=str(uuid4()),
        user_id=user_id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS,
        ),
        device_info=device_info,
    )
    db.add(rt)
    await db.flush()


async def validate_refresh_token(
    refresh_token: str, db: AsyncSession,
) -> str | None:
    """Return user_id if the refresh token is valid and not revoked/expired."""
    token_hash = sha256(refresh_token.encode()).hexdigest()
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    rt = result.scalar_one_or_none()
    return rt.user_id if rt else None


async def revoke_refresh_token(refresh_token: str, db: AsyncSession) -> None:
    """Soft-revoke a refresh token by setting revoked_at."""
    token_hash = sha256(refresh_token.encode()).hexdigest()
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    rt = result.scalar_one_or_none()
    if rt:
        rt.revoked_at = datetime.now(timezone.utc)
        await db.flush()


async def revoke_all_user_tokens(user_id: str, db: AsyncSession) -> int:
    """Revoke all active refresh tokens for a user. Returns count revoked."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
    )
    tokens = result.scalars().all()
    for rt in tokens:
        rt.revoked_at = now
    await db.flush()
    return len(tokens)


async def blacklist_token(jti: str, ttl_seconds: int, redis: Redis) -> None:
    """Add token JTI to Redis blacklist with remaining TTL."""
    await redis.setex(f"blacklist:{jti}", ttl_seconds, "1")


async def is_token_blacklisted(jti: str, redis: Redis) -> bool:
    return await redis.exists(f"blacklist:{jti}") > 0
