from fastapi import FastAPI

from app.api import router as api_router
from app.core.config import settings

app = FastAPI(
    title="MZADAK AI Service",
    version="0.1.0",
    docs_url="/docs" if settings.DEBUG else None,
)

app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "mzadak-ai-service", "gpu": settings.GPU_ENABLED}
