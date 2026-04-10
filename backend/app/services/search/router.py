"""Search endpoints — Meilisearch powered full-text search (FR-SRCH-001 → FR-SRCH-012)."""

from fastapi import APIRouter, Depends, Query

from app.core.redis import get_redis
from app.services.search import schemas, service

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/listings", response_model=schemas.SearchResponse)
async def search_listings(body: schemas.SearchRequest):
    """Full-text search across listings with faceted filtering (Arabic + English)."""
    return await service.search_listings(body)


@router.get("/suggest", response_model=schemas.SuggestResponse)
async def suggest(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=5, ge=1, le=20),
    redis=Depends(get_redis),
):
    """Autocomplete suggestions — target <50ms response time."""
    return await service.suggest_listings(q, limit, redis=redis)
