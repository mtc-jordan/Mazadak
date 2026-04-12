"""
Security middleware — rate limiting (sliding window) & security headers.

Rate limits (SDD §5.1):
  Authenticated:   1000 req/min  (keyed by user_id)
  Unauthenticated:  100 req/min  (keyed by client IP)
  WebSocket:          5 connections per user_id

Security headers (OWASP):
  Strict-Transport-Security, Content-Security-Policy, X-Frame-Options,
  X-Content-Type-Options, Referrer-Policy, Permissions-Policy.
"""

from __future__ import annotations

import logging
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  Rate Limiting Middleware (sliding window via Redis)
# ═══════════════════════════════════════════════════════════════════

# Paths exempt from rate limiting
_EXEMPT_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})

# Per-endpoint rate limits (requests per minute) — stricter than global
# Key: path prefix → (limit, window_seconds)
_ENDPOINT_LIMITS: dict[str, tuple[int, int]] = {
    "/api/v1/auth/register":             (10, 60),    # OTP send: 10/min per IP
    "/api/v1/auth/verify-otp":           (10, 60),    # OTP verify: 10/min per IP
    "/api/v1/auth/change-phone":         (5, 60),     # Phone change: 5/min per user
    "/api/v1/auctions/emergency-kill":   (2, 60),     # Kill switch: 2/min
    "/api/v1/auctions/emergency-resume": (2, 60),     # Resume: 2/min
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter using Redis INCR + EXPIRE.

    - Authenticated requests: keyed by ``user_id``, limit = RATE_LIMIT_AUTH/min
    - Unauthenticated requests: keyed by client IP, limit = RATE_LIMIT_UNAUTH/min
    - Returns 429 with ``Retry-After`` header when exceeded.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        path = request.url.path

        # Skip exempt paths and Socket.IO (has its own limiting)
        if path in _EXEMPT_PATHS or path.startswith("/socket.io"):
            return await call_next(request)

        # Get Redis — fail open if unavailable
        try:
            from app.core.redis import get_redis
            redis = await get_redis()
        except Exception:
            logger.warning("rate_limit_bypassed: Redis unavailable, all requests allowed")
            return await call_next(request)

        # Determine key and limit
        user_id = request.state.user_id if hasattr(request.state, "user_id") else None
        if user_id:
            key = f"rl:auth:{user_id}"
            limit = settings.RATE_LIMIT_AUTH
        else:
            client_ip = request.client.host if request.client else "unknown"
            key = f"rl:ip:{client_ip}"
            limit = settings.RATE_LIMIT_UNAUTH

        # Per-endpoint rate limit check (stricter, checked first)
        endpoint_limit = self._get_endpoint_limit(path)
        if endpoint_limit:
            ep_limit, ep_window = endpoint_limit
            ep_bucket = int(time.time()) // ep_window
            ep_key = f"rl:ep:{path}:{key}:{ep_bucket}"
            try:
                ep_count = await redis.incr(ep_key)
                if ep_count == 1:
                    await redis.expire(ep_key, ep_window * 2)
                if ep_count > ep_limit:
                    retry_after = ep_window - (int(time.time()) % ep_window)
                    return JSONResponse(
                        status_code=429,
                        content={
                            "success": False,
                            "message": "Rate limit exceeded for this endpoint.",
                            "data": None,
                        },
                        headers={"Retry-After": str(retry_after)},
                    )
            except Exception:
                pass

        # Global sliding window: minute bucket
        minute_bucket = int(time.time()) // 60
        bucket_key = f"{key}:{minute_bucket}"

        try:
            count = await redis.incr(bucket_key)
            if count == 1:
                await redis.expire(bucket_key, 120)  # 2 min TTL for safety

            if count > limit:
                retry_after = 60 - (int(time.time()) % 60)
                return JSONResponse(
                    status_code=429,
                    content={
                        "success": False,
                        "message": "Rate limit exceeded. Please try again later.",
                        "data": None,
                    },
                    headers={"Retry-After": str(retry_after)},
                )
        except Exception:
            # Fail open — don't block requests if Redis is down
            logger.warning("rate_limit_check_failed: Redis error during sliding window check")
            pass

        return await call_next(request)

    @staticmethod
    def _get_endpoint_limit(path: str) -> tuple[int, int] | None:
        """Match path against per-endpoint limits."""
        for prefix, limit_tuple in _ENDPOINT_LIMITS.items():
            if path.startswith(prefix):
                return limit_tuple
        return None


# ═══════════════════════════════════════════════════════════════════
#  Security Headers Middleware
# ═══════════════════════════════════════════════════════════════════

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject OWASP-recommended security headers on every response."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)

        # HSTS — 2 years, include subdomains, preload-eligible
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains; preload"
        )

        # CSP — API-only backend: deny everything
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'"
        )

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Referrer policy — send origin only on cross-origin
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Restrict browser features
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )

        # Remove server identification
        if "Server" in response.headers:
            del response.headers["Server"]

        return response


# ═══════════════════════════════════════════════════════════════════
#  Content-Type Enforcement Middleware
# ═══════════════════════════════════════════════════════════════════

class ContentTypeMiddleware(BaseHTTPMiddleware):
    """Reject non-JSON POST/PUT/PATCH requests (except multipart for uploads)."""

    _ENFORCED_METHODS = frozenset({"POST", "PUT", "PATCH"})
    _ALLOWED_CONTENT_TYPES = frozenset({
        "application/json",
        "multipart/form-data",
    })

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.method in self._ENFORCED_METHODS:
            path = request.url.path

            # Skip webhook endpoints (external providers send various formats)
            if "/webhooks" in path:
                return await call_next(request)

            content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()

            # Allow empty body (some POSTs have no body)
            content_length = request.headers.get("content-length", "0")
            if content_length != "0" and content_type not in self._ALLOWED_CONTENT_TYPES:
                return JSONResponse(
                    status_code=415,
                    content={
                        "success": False,
                        "message": f"Unsupported content type: {content_type}. Use application/json or multipart/form-data.",
                        "data": None,
                    },
                )

        return await call_next(request)


# ═══════════════════════════════════════════════════════════════════
#  WebSocket Connection Limiter (used inside ws.py, not as middleware)
# ═══════════════════════════════════════════════════════════════════

WS_MAX_CONNECTIONS_PER_USER = 5


async def check_ws_connection_limit(user_id: str, redis) -> bool:
    """Check if user has fewer than 5 active WS connections.

    Returns True if connection is allowed, False if limit exceeded.
    """
    key = f"ws:conn:{user_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 3600)  # auto-cleanup after 1 hour
    if count > WS_MAX_CONNECTIONS_PER_USER:
        await redis.decr(key)
        return False
    return True


async def release_ws_connection(user_id: str, redis) -> None:
    """Decrement WS connection counter on disconnect."""
    key = f"ws:conn:{user_id}"
    new_count = await redis.decr(key)
    if new_count <= 0:
        await redis.delete(key)
