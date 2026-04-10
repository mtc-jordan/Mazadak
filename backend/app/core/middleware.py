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

import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.core.config import settings


# ═══════════════════════════════════════════════════════════════════
#  Rate Limiting Middleware (sliding window via Redis)
# ═══════════════════════════════════════════════════════════════════

# Paths exempt from rate limiting
_EXEMPT_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})


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

        # Sliding window: minute bucket
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
            pass

        return await call_next(request)


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
