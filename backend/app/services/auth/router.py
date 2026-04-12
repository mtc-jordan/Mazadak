"""Auth endpoints — SDD §5.2, FR-AUTH-001, FR-AUTH-003, FR-AUTH-004, FR-AUTH-005, FR-AUTH-015."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.services.auth import schemas, service
from app.services.auth import kyc_service
from app.services.auth.dependencies import get_current_user
from app.services.auth.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


# ── POST /auth/register — FR-AUTH-001 ──────────────────────────

@router.post(
    "/register",
    response_model=schemas.OTPSentResponse,
    status_code=status.HTTP_200_OK,
    responses={
        429: {"description": "Rate limited or locked out"},
    },
)
async def register(
    body: schemas.RegisterRequest,
    redis: Redis = Depends(get_redis),
):
    """Register new user — sends OTP to phone.

    FR-AUTH-001: 6-digit OTP via SMS (Twilio → SNS fallback).
    FR-AUTH-015: Max 5 OTP requests per phone per hour.
    """
    success, _error_code, error_detail = await service.send_otp(body.phone, redis)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_detail,
        )
    return schemas.OTPSentResponse()


# ── POST /auth/verify-otp — FR-AUTH-001 ────────────────────────

@router.post(
    "/verify-otp",
    response_model=schemas.AuthResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Invalid or expired OTP"},
        403: {"description": "Account banned"},
        429: {"description": "Locked out after too many attempts"},
    },
)
async def verify_otp(
    body: schemas.VerifyOTPRequest,
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Verify OTP → create/load user → issue JWT pair.

    FR-AUTH-001: Max 3 verify attempts, then 15-min lockout.
    """
    valid, error_code, error_detail = await service.verify_otp(
        body.phone, body.otp, redis,
    )
    if not valid:
        status_code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if error_code == "OTP_LOCKED_OUT"
            else status.HTTP_401_UNAUTHORIZED
        )
        raise HTTPException(status_code=status_code, detail=error_detail)

    try:
        user, _is_new = await service.get_or_create_user(body.phone, db)
    except ValueError as exc:
        if str(exc) == "ACCOUNT_BANNED":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ACCOUNT_BANNED",
                    "message_en": "Account has been permanently banned",
                    "message_ar": "تم حظر الحساب بشكل دائم",
                },
            )
        raise

    access_token, refresh_token, _jti = service.issue_tokens(user)
    await service.store_refresh_token(refresh_token, user.id, db)

    return schemas.AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=schemas.UserResponse.model_validate(user),
    )


# ── POST /auth/refresh — FR-AUTH-003 ──────────────────────────

@router.post(
    "/refresh",
    response_model=schemas.TokenResponse,
    responses={401: {"description": "Invalid refresh token"}},
)
async def refresh_token(
    body: schemas.RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """Silent token refresh — exchange refresh token for a new pair.

    FR-AUTH-003: No re-login required. Old refresh token invalidated
    (rotation) to prevent replay. DB-based refresh tokens.
    """
    user_id = await service.validate_refresh_token(body.refresh_token, db)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_REFRESH",
                "message_en": "Invalid or expired refresh token",
                "message_ar": "رمز التحديث غير صالح أو منتهي الصلاحية",
            },
        )

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "USER_NOT_FOUND",
                "message_en": "User account not found",
                "message_ar": "لم يتم العثور على حساب المستخدم",
            },
        )

    if user.is_banned or user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCOUNT_DISABLED",
                "message_en": "Account suspended or banned",
                "message_ar": "تم تعليق أو حظر الحساب",
            },
        )

    # Rotate: revoke old, issue new
    await service.revoke_refresh_token(body.refresh_token, db)
    access_token, new_refresh, _jti = service.issue_tokens(user)
    await service.store_refresh_token(new_refresh, user.id, db)

    return schemas.TokenResponse(access_token=access_token, refresh_token=new_refresh)


# ── POST /auth/logout — FR-AUTH-004 ────────────────────────────

@router.post(
    "/logout",
    response_model=schemas.LogoutResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"description": "Invalid token"}},
)
async def logout(
    body: schemas.LogoutRequest,
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Logout — blacklist access token JTI + revoke refresh token.

    FR-AUTH-004: JWT blacklist in Redis with TTL = remaining validity.
    Optional revoke_all=true revokes all sessions for the user.
    """
    # Blacklist the current access token's JTI with remaining TTL
    payload = user._token_payload  # type: ignore[attr-defined]
    now = datetime.now(timezone.utc)
    remaining_seconds = max(int((payload.exp - now).total_seconds()), 0)
    if remaining_seconds > 0:
        await service.blacklist_token(payload.jti, remaining_seconds, redis)

    if body.revoke_all:
        await service.revoke_all_user_tokens(user.id, db)
    else:
        await service.revoke_refresh_token(body.refresh_token, db)

    return schemas.LogoutResponse()


# ── GET /auth/me — current user profile ────────────────────────

@router.get(
    "/me",
    response_model=schemas.UserResponse,
)
async def get_me(
    user: User = Depends(get_current_user),
):
    """Return the authenticated user's profile."""
    return schemas.UserResponse.model_validate(user)


# ── PUT /auth/me — Update profile (FR-AUTH-009) ───────────────

@router.put(
    "/me",
    response_model=schemas.UpdateProfileResponse,
)
async def update_me(
    body: schemas.UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the authenticated user's profile.

    FR-AUTH-009: name, email, address, language preference.
    """
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.full_name_ar is not None:
        user.full_name_ar = body.full_name_ar
    if body.email is not None:
        user.email = body.email
    if body.preferred_language is not None:
        user.preferred_language = body.preferred_language
    if body.address_city is not None:
        user.address_city = body.address_city
    if body.address_country is not None:
        user.address_country = body.address_country

    await db.commit()
    await db.refresh(user)

    return schemas.UpdateProfileResponse(
        user=schemas.UserResponse.model_validate(user),
    )


# ── GET /auth/kyc/status ──────────────────────────────────────

@router.get(
    "/kyc/status",
    response_model=schemas.KYCStatusResponse,
)
async def kyc_status(
    user: User = Depends(get_current_user),
):
    """Return the user's current KYC verification status."""
    kyc = user.kyc_status.value if hasattr(user.kyc_status, "value") else user.kyc_status
    return schemas.KYCStatusResponse(
        kyc_status=kyc,
        kyc_submitted_at=(
            user.kyc_submitted_at.isoformat() if user.kyc_submitted_at else None
        ),
        kyc_reviewed_at=(
            user.kyc_reviewed_at.isoformat() if user.kyc_reviewed_at else None
        ),
        kyc_rejection_reason=user.kyc_rejection_reason,
    )


# ── POST /auth/kyc/initiate — FR-AUTH-005 ─────────────────────

@router.post(
    "/kyc/initiate",
    response_model=schemas.KYCInitiateResponse,
    responses={
        400: {"description": "Already verified or max attempts reached"},
    },
)
async def kyc_initiate(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Generate S3 presigned upload URLs for KYC documents.

    PM-02 Steps 3-5: ID front, ID back, selfie.
    SDD §6.2: SSE-S3, private ACL, 15-minute TTL.
    """
    eligible, error_code = await kyc_service.check_kyc_eligibility(user, redis)
    if not eligible:
        messages = {
            "ALREADY_VERIFIED": (
                "KYC already verified",
                "تم التحقق من الهوية مسبقاً",
            ),
            "PENDING_REVIEW": (
                "KYC is already under review",
                "الهوية قيد المراجعة حالياً",
            ),
            "MAX_ATTEMPTS_REACHED": (
                "Maximum KYC attempts reached. Contact support.",
                "تم الوصول للحد الأقصى من محاولات التحقق. تواصل مع الدعم.",
            ),
        }
        en, ar = messages.get(error_code, ("KYC not allowed", "غير مسموح"))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": error_code, "message_en": en, "message_ar": ar},
        )

    result = await kyc_service.generate_upload_urls(user.id)
    return schemas.KYCInitiateResponse(
        upload_urls=result["upload_urls"],
        s3_keys=result["s3_keys"],
    )


# ── POST /auth/kyc/submit — FR-AUTH-005 ──────────────────────

@router.post(
    "/kyc/submit",
    response_model=schemas.KYCSubmitResponse,
    responses={
        400: {"description": "Not eligible for KYC"},
    },
)
async def kyc_submit(
    body: schemas.KYCSubmitRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Submit KYC documents for verification.

    FR-AUTH-005: Rekognition CompareFaces(selfie, id_front).
    PM-02 Step 7-8: confidence thresholds → auto/manual/reject.
    """
    eligible, error_code = await kyc_service.check_kyc_eligibility(user, redis)
    if not eligible:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": error_code, "message_en": "KYC submission not allowed"},
        )

    result = await kyc_service.submit_kyc(
        user=user,
        id_front_key=body.id_front_key,
        id_back_key=body.id_back_key,
        selfie_key=body.selfie_key,
        db=db,
        redis=redis,
    )

    return schemas.KYCSubmitResponse(**result)


# ── POST /auth/device-token — FCM push token registration ─────

MAX_FCM_TOKENS = 5  # max tokens per user (across devices)


@router.post(
    "/device-token",
    response_model=schemas.RegisterDeviceTokenResponse,
)
async def register_device_token(
    body: schemas.RegisterDeviceTokenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register an FCM push notification token for the current device.

    Upserts into user.fcm_tokens (JSONB array). Deduplicates tokens and
    enforces a max of 5 tokens per user (FIFO eviction).
    """
    tokens: list[str] = list(user.fcm_tokens or [])

    # Deduplicate: if token already registered, move to end (most recent)
    if body.token in tokens:
        tokens.remove(body.token)
    tokens.append(body.token)

    # FIFO eviction if over limit
    if len(tokens) > MAX_FCM_TOKENS:
        tokens = tokens[-MAX_FCM_TOKENS:]

    user.fcm_tokens = tokens
    await db.commit()

    return schemas.RegisterDeviceTokenResponse()


@router.delete(
    "/device-token",
    response_model=schemas.RegisterDeviceTokenResponse,
)
async def remove_device_token(
    body: schemas.RegisterDeviceTokenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove an FCM token on logout (prevents stale push delivery)."""
    tokens: list[str] = list(user.fcm_tokens or [])
    if body.token in tokens:
        tokens.remove(body.token)
        user.fcm_tokens = tokens
        await db.commit()

    return schemas.RegisterDeviceTokenResponse()


# ── POST /auth/change-phone — FR-AUTH-010 ────────────────────

@router.post("/change-phone/request")
async def change_phone_request(
    body: schemas.ChangePhoneRequest,
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Step 1: Request phone number change — sends OTP to new number.

    Checks that the new number isn't already registered.
    OTP is stored with a special prefix to distinguish from login OTPs.
    """
    from sqlalchemy import select

    # Check new phone isn't already taken
    existing = await db.execute(
        select(User).where(User.phone == body.new_phone)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PHONE_ALREADY_REGISTERED",
                "message_en": "This phone number is already registered",
                "message_ar": "رقم الهاتف مسجل مسبقاً",
            },
        )

    # Send OTP to new phone (reuse existing OTP logic)
    success, _error_code, error_detail = await service.send_otp(
        body.new_phone, redis, purpose="change_phone"
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_detail,
        )

    return {
        "success": True,
        "message_en": "OTP sent to new phone number",
        "message_ar": "تم إرسال رمز التحقق إلى الرقم الجديد",
    }


@router.post("/change-phone/verify")
async def change_phone_verify(
    body: schemas.ChangePhoneVerifyRequest,
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Step 2: Verify OTP on new phone and update the user's phone number.

    After successful verification, all existing sessions are revoked
    and new tokens are issued.
    """
    valid, error_code, error_detail = await service.verify_otp(
        body.new_phone, body.otp, redis, purpose="change_phone"
    )
    if not valid:
        status_code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if error_code == "OTP_LOCKED_OUT"
            else status.HTTP_401_UNAUTHORIZED
        )
        raise HTTPException(status_code=status_code, detail=error_detail)

    # Update phone number
    old_phone = user.phone
    user.phone = body.new_phone
    await db.commit()
    await db.refresh(user)

    # Revoke all existing sessions (force re-login on other devices)
    await service.revoke_all_user_tokens(user.id, db)

    # Issue new tokens
    access_token, refresh_token, _jti = service.issue_tokens(user)
    await service.store_refresh_token(refresh_token, user.id, db)

    return schemas.AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=schemas.UserResponse.model_validate(user),
    )
