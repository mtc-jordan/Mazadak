"""
MZADAK Backend — FastAPI application factory.

``create_app()`` is the single entry point used by uvicorn, tests, and
the Docker CMD.  It wires routers, middleware, exception handlers,
and lifespan events (startup / shutdown).
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  Lifespan — startup / shutdown
# ═══════════════════════════════════════════════════════════════════

@asynccontextmanager
async def _lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────
    logger.info("startup", environment=settings.ENVIRONMENT)

    # Inject Redis factory into WebSocket server
    from app.services.auction.ws import set_redis_factory
    from app.core.redis import get_redis
    set_redis_factory(get_redis)

    # Warm Lua scripts (EVALSHA needs SHA pre-loaded)
    try:
        from app.services.auction.lua_scripts import BidLuaScripts
        redis = await get_redis()
        await BidLuaScripts.load(redis)
        logger.info("lua_scripts_warmed")
    except Exception as exc:
        logger.warning("lua_warmup_skipped", error=str(exc))

    # Initialize Meilisearch indexes
    try:
        from app.services.search.indexer import ensure_indexes
        await ensure_indexes()
        logger.info("meilisearch_indexes_ready")
    except Exception as exc:
        logger.warning("meilisearch_init_skipped", error=str(exc))

    # Start Redis keyspace expiry listener for auction end detection
    try:
        from app.core.redis import start_keyspace_listener
        await start_keyspace_listener()
        logger.info("keyspace_listener_started")
    except Exception as exc:
        logger.warning("keyspace_listener_skipped", error=str(exc))

    yield

    # ── Shutdown ─────────────────────────────────────────────────
    from app.core.redis import close_redis
    from app.core.database import engine

    await close_redis()
    await engine.dispose()
    logger.info("shutdown_complete")


# ═══════════════════════════════════════════════════════════════════
#  App factory
# ═══════════════════════════════════════════════════════════════════

def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""

    setup_logging()

    app = FastAPI(
        title="MZADAK API",
        version="0.1.0",
        description="Intelligent Auction Marketplace",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        default_response_class=ORJSONResponse,
        lifespan=_lifespan,
    )

    # ── Exception handlers (envelope: {data, message, success}) ──
    register_exception_handlers(app)

    # ── Security middleware (outermost → innermost) ─────────────
    from app.core.middleware import (
        ContentTypeMiddleware,
        RateLimitMiddleware,
        SecurityHeadersMiddleware,
    )

    # Security headers on every response
    app.add_middleware(SecurityHeadersMiddleware)

    # Rate limiting (sliding window via Redis)
    app.add_middleware(RateLimitMiddleware)

    # Content-type enforcement for mutations
    app.add_middleware(ContentTypeMiddleware)

    # ── CORS (hardened) ───────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
        max_age=600,
    )

    # ── Request logging middleware ────────────────────────────────
    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round(elapsed_ms, 1),
        )
        return response

    # ── Routers ──────────────────────────────────────────────────
    from app.api.v1 import router as api_v1_router
    app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)

    # ── WebSocket (Socket.IO) ────────────────────────────────────
    # Socket.IO wraps FastAPI as other_asgi_app — see socket_app below

    # ── Health check ─────────────────────────────────────────────
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": "mzadak-backend"}

    return app


# Module-level instance for ``uvicorn app.main:app``
_fastapi_app = create_app()

# Socket.IO wraps FastAPI — uvicorn serves socket_app as root ASGI app.
# This lets Socket.IO handle /socket.io/* and pass everything else to FastAPI.
import socketio as _socketio
from app.services.auction.ws import sio as _sio

app = _socketio.ASGIApp(_sio, other_asgi_app=_fastapi_app)
