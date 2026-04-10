"""
Custom exceptions and global FastAPI handlers — SDD §5.1.

Every HTTP response follows the envelope: ``{data, message, success}``.
Exception handlers catch known app errors and unexpected 500s,
returning consistent bilingual error payloads.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  Custom exception hierarchy
# ═══════════════════════════════════════════════════════════════════

class AppError(Exception):
    """Base application error with HTTP status and bilingual messages."""

    def __init__(
        self,
        *,
        code: str,
        message_en: str,
        message_ar: str = "",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        data: Any = None,
    ) -> None:
        self.code = code
        self.message_en = message_en
        self.message_ar = message_ar or message_en
        self.status_code = status_code
        self.data = data
        super().__init__(message_en)


class NotFoundError(AppError):
    """Resource not found (404)."""

    def __init__(
        self,
        *,
        code: str = "NOT_FOUND",
        message_en: str = "Resource not found",
        message_ar: str = "المورد غير موجود",
    ) -> None:
        super().__init__(
            code=code,
            message_en=message_en,
            message_ar=message_ar,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ForbiddenError(AppError):
    """Forbidden (403)."""

    def __init__(
        self,
        *,
        code: str = "FORBIDDEN",
        message_en: str = "You do not have permission",
        message_ar: str = "ليس لديك صلاحية",
    ) -> None:
        super().__init__(
            code=code,
            message_en=message_en,
            message_ar=message_ar,
            status_code=status.HTTP_403_FORBIDDEN,
        )


class RateLimitedError(AppError):
    """Too many requests (429)."""

    def __init__(
        self,
        *,
        code: str = "RATE_LIMITED",
        message_en: str = "Too many requests",
        message_ar: str = "طلبات كثيرة جداً",
    ) -> None:
        super().__init__(
            code=code,
            message_en=message_en,
            message_ar=message_ar,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )


class ConflictError(AppError):
    """Conflict (409)."""

    def __init__(
        self,
        *,
        code: str = "CONFLICT",
        message_en: str = "Conflict",
        message_ar: str = "تعارض",
    ) -> None:
        super().__init__(
            code=code,
            message_en=message_en,
            message_ar=message_ar,
            status_code=status.HTTP_409_CONFLICT,
        )


# ═══════════════════════════════════════════════════════════════════
#  Envelope helper
# ═══════════════════════════════════════════════════════════════════

def _envelope(
    *,
    data: Any = None,
    message: str,
    success: bool,
    code: str | None = None,
    message_ar: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"data": data, "message": message, "success": success}
    if code:
        body["code"] = code
    if message_ar:
        body["message_ar"] = message_ar
    return body


# ═══════════════════════════════════════════════════════════════════
#  Handler registration
# ═══════════════════════════════════════════════════════════════════

def register_exception_handlers(app: FastAPI) -> None:
    """Attach global exception handlers to the FastAPI app."""

    @app.exception_handler(AppError)
    async def app_error_handler(_req: Request, exc: AppError) -> ORJSONResponse:
        logger.warning(
            "app_error",
            code=exc.code,
            status=exc.status_code,
            message=exc.message_en,
        )
        return ORJSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                data=exc.data,
                message=exc.message_en,
                success=False,
                code=exc.code,
                message_ar=exc.message_ar,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_req: Request, exc: StarletteHTTPException) -> ORJSONResponse:
        if isinstance(exc.detail, dict):
            return ORJSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail, "success": False},
            )
        return ORJSONResponse(
            status_code=exc.status_code,
            content=_envelope(message=str(exc.detail), success=False),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_req: Request, exc: RequestValidationError) -> ORJSONResponse:
        errors = []
        for err in exc.errors():
            clean = {k: v for k, v in err.items() if k != "ctx"}
            errors.append(clean)
        return ORJSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_envelope(
                data=errors,
                message="Validation error",
                success=False,
                code="VALIDATION_ERROR",
                message_ar="خطأ في البيانات",
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_req: Request, exc: Exception) -> ORJSONResponse:
        logger.exception("unhandled_error", error=str(exc))
        return ORJSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                message="Internal server error",
                success=False,
                code="INTERNAL_ERROR",
                message_ar="خطأ داخلي في الخادم",
            ),
        )
