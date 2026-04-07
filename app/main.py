"""
MZADAK Backend — FastAPI application entry point.

Lifespan events handle Redis pool and DB engine startup/shutdown.
All service routers are wired via the v1 API router.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import router as api_v1_router
from app.core.config import settings
from app.core.redis import close_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — inject Redis factory into WebSocket server
    from app.services.auction.ws import set_redis_factory
    from app.core.redis import get_redis
    set_redis_factory(get_redis)
    yield
    # Shutdown
    await close_redis()


app = FastAPI(
    title="MZADAK API",
    version="0.1.0",
    description="Intelligent Auction Marketplace",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)

# ── WebSocket (Socket.IO) mount at /ws ──────────────────────────
from app.services.auction.ws import sio_app as _sio_app  # noqa: E402
app.mount("/ws", _sio_app)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "mzadak-backend"}
