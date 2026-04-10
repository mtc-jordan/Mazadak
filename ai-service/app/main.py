import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router as api_router
from app.core.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: warm CLIP model. Shutdown: no-op."""
    from app.services.clip_service import warm_model

    logger.info("Warming CLIP model …")
    await warm_model()
    logger.info("CLIP model ready.")
    yield


app = FastAPI(
    title="MZADAK AI Service",
    version="0.1.0",
    docs_url="/docs" if settings.DEBUG else None,
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "mzadak-ai-service", "gpu": settings.GPU_ENABLED}
