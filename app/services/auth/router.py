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
    Postcondition: User in PENDING_KYC state, JWT pair issued.
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

    user, _is_new = await service.get_or_create_user(body.phone, db)
    access_token, refresh_token, _jti = service.issue_tokens(user)
    await service.store_refresh_token(refresh_token, user.id, redis)

    return schemas.AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=schemas.UserOut.model_validate(user),
    )


# ── POST /auth/login ───────────────────────────────────────────

@router.post(
    "/login",
    response_model=schemas.OTPSentResponse,
    status_code=status.HTTP_200_OK,
    responses={429: {"description": "Rate limited or locked out"}},
)
async def login(
    body: schemas.LoginRequest,
    redis: Redis = Depends(get_redis),
):
    """Login — sends OTP to existing phone."""
    success, _error_code, error_detail = await service.send_otp(body.phone, redis)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_detail,
        )
    return schemas.OTPSentResponse()


# ── POST /auth/refresh — FR-AUTH-003 ──────────────────────────

@router.post(
    "/refresh",
    response_model=schemas.TokenResponse,
    responses={401: {"description": "Invalid refresh token"}},
)
async def refresh_token(
    body: schemas.RefreshRequest,
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Silent token refresh — exchange refresh token for a new pair.

    FR-AUTH-003: No re-login required. Old refresh token invalidated
    (rotation) to prevent replay.
    """
    user_id = await service.validate_refresh_token(body.refresh_token, redis)
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

    # Invalidate old refresh token (rotation — prevents replay)
    await service.revoke_refresh_token(body.refresh_token, redis)

    # Issue new pair
    access_token, new_refresh, _jti = service.issue_tokens(user)
    await service.store_refresh_token(new_refresh, user.id, redis)

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
):
    """Logout — blacklist access token JTI + revoke refresh token.

    FR-AUTH-004: JWT blacklist in Redis with TTL = remaining validity.
    SDD §5.2: POST /auth/logout takes {refresh_token}, returns {success: true}.
    """
    # Blacklist the current access token's JTI with remaining TTL
    payload = user._token_payload  # type: ignore[attr-defined]
    now = datetime.now(timezone.utc)
    remaining_seconds = max(int((payload.exp - now).total_seconds()), 0)
    if remaining_seconds > 0:
        await service.blacklist_token(payload.jti, remaining_seconds, redis)

    # Revoke the refresh token
    await service.revoke_refresh_token(body.refresh_token, redis)

    return schemas.LogoutResponse()


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
):
    """Generate S3 presigned upload URLs for KYC documents.

    PM-02 Steps 3-5: ID front, ID back, selfie.
    SDD §6.2: SSE-S3, private ACL, 5-minute TTL.
    """
    eligible, error_code = await kyc_service.check_kyc_eligibility(user)
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
):
    """Submit KYC documents for verification.

    FR-AUTH-005: Rekognition CompareFaces(selfie, id_front).
    PM-02 Step 7-8: confidence thresholds → auto/manual/reject.
    SDD §5.2: POST /auth/kyc/submit → {status: 'verified'|'pending'}.
    """
    eligible, error_code = await kyc_service.check_kyc_eligibility(user)
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
    )

    return schemas.KYCSubmitResponse(**result)
