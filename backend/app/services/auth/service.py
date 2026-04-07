"""
Auth business logic — SDD §3.1, FR-AUTH-001, FR-AUTH-015.

Handles: phone OTP registration/login, JWT issuance/refresh,
         OTP rate limiting, attempt tracking, lockout enforcement.

Redis key layout (SDD §4.3):
  otp:{phone}            — SHA-256(OTP), STR, TTL 5min
  otp:attempts:{phone}   — verify attempt counter, STR, TTL 5min
  otp:lockout:{phone}    — lockout flag, STR, TTL 15min
  rate:otp:{phone}       — hourly OTP request counter, STR, TTL 1h
  session:{sha256(token)} — user_id, STR, TTL 30d
  blacklist:{jti}        — "1", STR, TTL = remaining JWT validity
"""

from __future__ import annotations

import logging
import secrets
from hashlib import sha256
from uuid import uuid4

import phonenumbers
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token
from app.services.auth.models import ATSTier, KYCStatus, User, UserRole
from app.services.auth.sms import send_sms

logger = logging.getLogger(__name__)

# ── Redis key prefixes ──────────────────────────────────────────
OTP_KEY = "otp:{phone}"
OTP_ATTEMPTS_KEY = "otp:attempts:{phone}"
OTP_LOCKOUT_KEY = "otp:lockout:{phone}"
OTP_RATE_KEY = "rate:otp:{phone}"
SESSION_KEY = "session:{hash}"
BLACKLIST_KEY = "blacklist:{jti}"


def _country_code_from_phone(phone: str) -> str:
    """Extract ISO 3166-1 alpha-2 country code from E.164 phone."""
    try:
        parsed = phonenumbers.parse(phone, None)
        return phonenumbers.region_code_for_number(parsed) or "JO"
    except phonenumbers.NumberParseException:
        return "JO"


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
    # Check lockout first
    locked, lockout_ttl = await check_otp_lockout(phone, redis)
    if locked:
        return False, "OTP_LOCKED_OUT", {
            "code": "OTP_LOCKED_OUT",
            "message_en": "Account locked due to too many failed attempts. Try again later.",
            "message_ar": "تم قفل الحساب بسبب محاولات فاشلة كثيرة. حاول لاحقاً.",
            "retry_after_seconds": lockout_ttl,
        }

    # Check rate limit (5 per hour)
    allowed, rate_ttl = await check_otp_rate_limit(phone, redis)
    if not allowed:
        return False, "OTP_RATE_LIMITED", {
            "code": "OTP_RATE_LIMITED",
            "message_en": "Too many OTP requests. Try again later.",
            "message_ar": "طلبات كثيرة لرمز التحقق. حاول لاحقاً.",
            "retry_after_seconds": rate_ttl,
        }

    # Generate 6-digit OTP
    otp = f"{secrets.randbelow(900000) + 100000}"
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
        logger.error("Failed to send OTP SMS to %s via all providers", phone)
        # Still return success — OTP is stored, user can retry
        # In production, would queue for retry

    return True, None, None


# ═══════════════════════════════════════════════════════════════════
# OTP — Verify
# ═══════════════════════════════════════════════════════════════════


async def verify_otp(
    phone: str, otp: str, redis: Redis,
) -> tuple[bool, str | None, dict | None]:
    """Verify OTP against stored hash.

    FR-AUTH-001: Max 3 attempts, then 15-min lockout.
    Returns (success, error_code, error_detail).
    """
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
        # Set lockout
        lockout_key = OTP_LOCKOUT_KEY.format(phone=phone)
        await redis.setex(lockout_key, settings.OTP_LOCKOUT_SECONDS, "1")
        # Clear OTP and attempts
        await redis.delete(otp_key, attempts_key)
        logger.warning("AUTH-OTP-LOCKOUT: phone=%s after %d attempts", phone, attempts)
        return False, "OTP_LOCKED_OUT", {
            "code": "OTP_LOCKED_OUT",
            "message_en": "Too many failed attempts. Locked for 15 minutes.",
            "message_ar": "محاولات فاشلة كثيرة. تم القفل لمدة 15 دقيقة.",
            "retry_after_seconds": settings.OTP_LOCKOUT_SECONDS,
        }

    # Verify hash
    otp_hash = sha256(otp.encode()).hexdigest()
    if otp_hash != stored_hash:
        remaining = settings.OTP_MAX_VERIFY_ATTEMPTS - attempts
        return False, "INVALID_OTP", {
            "code": "INVALID_OTP",
            "message_en": f"Invalid OTP. {remaining} attempt(s) remaining.",
            "message_ar": f"رمز التحقق غير صحيح. متبقي {remaining} محاولة.",
            "attempts_remaining": remaining,
        }

    # Success — clean up Redis
    await redis.delete(otp_key, attempts_key)

    return True, None, None


# ═══════════════════════════════════════════════════════════════════
# User management
# ═══════════════════════════════════════════════════════════════════


async def get_or_create_user(phone: str, db: AsyncSession) -> tuple[User, bool]:
    """Load existing user or create a new one (PENDING_KYC, ats_score=400).

    Returns (user, is_new).
    """
    result = await db.execute(select(User).where(User.phone == phone))
    user = result.scalar_one_or_none()
    if user:
        return user, False

    country = _country_code_from_phone(phone)
    lang = "ar" if country == "JO" else "ar"

    user = User(
        id=str(uuid4()),
        phone=phone,
        full_name_ar="",
        role=UserRole.BUYER,
        kyc_status=KYCStatus.PENDING,
        ats_score=400,
        ats_tier=ATSTier.TRUSTED,
        country_code=country,
        preferred_language=lang,
    )
    db.add(user)
    await db.flush()
    await db.commit()
    return user, True


# ═══════════════════════════════════════════════════════════════════
# Token issuance & management
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
    refresh_token: str, user_id: str, redis: Redis,
) -> None:
    """Store SHA-256(refresh_token) → user_id in Redis with 30-day TTL."""
    token_hash = sha256(refresh_token.encode()).hexdigest()
    await redis.setex(
        f"session:{token_hash}",
        settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        user_id,
    )


async def validate_refresh_token(
    refresh_token: str, redis: Redis,
) -> str | None:
    """Return user_id if the refresh token is valid, else None."""
    token_hash = sha256(refresh_token.encode()).hexdigest()
    return await redis.get(f"session:{token_hash}")


async def revoke_refresh_token(refresh_token: str, redis: Redis) -> None:
    """Delete refresh token hash from Redis (FR-AUTH-004)."""
    token_hash = sha256(refresh_token.encode()).hexdigest()
    await redis.delete(f"session:{token_hash}")


async def blacklist_token(jti: str, ttl_seconds: int, redis: Redis) -> None:
    """Add token JTI to blacklist with remaining TTL."""
    await redis.setex(f"blacklist:{jti}", ttl_seconds, "1")


async def is_token_blacklisted(jti: str, redis: Redis) -> bool:
    return await redis.exists(f"blacklist:{jti}") > 0
