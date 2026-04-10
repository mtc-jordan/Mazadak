"""
Auth dependencies — injectable via FastAPI Depends().

SDD §6: 6 auth layers. Layer 4 = role-based AC via dependency injection.
FR-AUTH-004: Session invalidation via JWT blacklist.
FR-AUTH-008: ATS-based access control.

Usage:
    @router.get("/protected")
    async def endpoint(user: User = Depends(get_current_user)): ...

    @router.post("/listings")
    async def create(user: User = Depends(require_kyc)): ...

    @router.post("/admin/ban")
    async def ban(user: User = Depends(require_role("admin", "superadmin"))): ...

    @router.post("/bid")
    async def bid(user: User = Depends(require_ats(200))): ...
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import TokenPayload, decode_access_token
from app.services.auth.models import User
from app.services.auth.service import is_token_blacklisted

bearer_scheme = HTTPBearer()


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Decode RS256 JWT, check Redis blacklist, load and return User.

    Caches user on request.state to avoid repeated DB hits
    when multiple dependencies call get_current_user.

    Raises 401 for invalid/expired/blacklisted tokens.
    Raises 403 for suspended or banned accounts.
    """
    # Return cached user if already resolved this request
    if hasattr(request.state, "current_user"):
        return request.state.current_user

    payload: TokenPayload | None = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_TOKEN",
                "message_en": "Invalid or expired token",
                "message_ar": "رمز المصادقة غير صالح أو منتهي الصلاحية",
            },
        )

    if await is_token_blacklisted(payload.jti, redis):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "TOKEN_REVOKED",
                "message_en": "Token has been revoked",
                "message_ar": "تم إلغاء رمز المصادقة",
            },
        )

    user = await db.get(User, payload.sub)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "USER_NOT_FOUND",
                "message_en": "User account not found",
                "message_ar": "لم يتم العثور على حساب المستخدم",
            },
        )

    if user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCOUNT_BANNED",
                "message_en": "Account has been permanently banned",
                "message_ar": "تم حظر الحساب بشكل دائم",
            },
        )

    if user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCOUNT_SUSPENDED",
                "message_en": "Account is suspended. Contact support to appeal.",
                "message_ar": "تم تعليق الحساب. تواصل مع الدعم للاستئناف.",
            },
        )

    # Stash payload on user for logout (need jti + exp)
    user._token_payload = payload  # type: ignore[attr-defined]

    # Cache on request state
    request.state.current_user = user

    return user


async def require_kyc(
    user: User = Depends(get_current_user),
) -> User:
    """Require KYC-verified user. Used for seller operations (SDD §6)."""
    kyc = user.kyc_status.value if hasattr(user.kyc_status, "value") else user.kyc_status
    if kyc != "verified":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "KYC_REQUIRED",
                "message_en": "KYC verification required for this action",
                "message_ar": "يلزم التحقق من الهوية لهذا الإجراء",
            },
        )
    return user


async def require_seller(
    user: User = Depends(require_kyc),
) -> User:
    """Require KYC-verified user with seller or higher role."""
    role = user.role.value if hasattr(user.role, "value") else user.role
    if role not in ("seller", "admin", "superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SELLER_REQUIRED",
                "message_en": "Seller account required for this action",
                "message_ar": "يلزم حساب بائع لهذا الإجراء",
            },
        )
    return user


def require_role(*roles: str) -> Callable:
    """Factory returning a dependency that checks user.role against allowed list.

    SDD §6 authorization matrix:
      buyer      → bid
      seller(KYC)→ bid + create listing
      admin      → admin panel
      superadmin → everything

    Usage: Depends(require_role("admin", "superadmin"))
    """

    async def _check_role(user: User = Depends(get_current_user)) -> User:
        user_role = user.role.value if hasattr(user.role, "value") else user.role
        if user_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INSUFFICIENT_ROLE",
                    "message_en": f"Required role: {', '.join(roles)}",
                    "message_ar": "صلاحيات غير كافية",
                },
            )
        return user

    return _check_role


def require_ats(min_score: int) -> Callable:
    """Factory returning a dependency that checks user.ats_score >= threshold.

    FR-AUTH-008: ATS < 200 → bidding restricted to items < 100 JOD.
                 ATS < 100 → account suspended pending review.

    Usage: Depends(require_ats(200))
    """

    async def _check_ats(user: User = Depends(get_current_user)) -> User:
        if user.ats_score < min_score:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ATS_TOO_LOW",
                    "message_en": (
                        f"Your trust score ({user.ats_score}) is below the "
                        f"required minimum ({min_score}) for this action"
                    ),
                    "message_ar": (
                        f"درجة الثقة الخاصة بك ({user.ats_score}) أقل من "
                        f"الحد الأدنى المطلوب ({min_score}) لهذا الإجراء"
                    ),
                },
            )
        return user

    return _check_ats
