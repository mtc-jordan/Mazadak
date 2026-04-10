"""AI proxy endpoints — SDD §3.4 & §5."""

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.services.auth.dependencies import get_current_user, require_kyc
from app.services.auth.models import User
from app.services.ai import schemas, service

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/snap-to-list", response_model=schemas.SnapToListResponse)
async def snap_to_list(
    body: schemas.SnapToListRequest,
    user: User = Depends(require_kyc),
    redis: Redis = Depends(get_redis),
):
    """Image → listing draft (CLIP + GPT-4o + Price Oracle). <8s P90.

    FR-LIST-002, PM-04: Accepts 3-20 S3 image keys, returns a
    complete listing draft with bilingual title/description,
    category prediction, price range, and confidence level.

    Auth: require_kyc.
    """
    from app.services.ai.snap_to_list import run_snap_to_list_pipeline

    result = await run_snap_to_list_pipeline(body, user.id, redis)
    return result


@router.get("/price-oracle", response_model=schemas.PriceOracleResponse)
async def price_oracle(
    category_id: int = Query(..., ge=1),
    condition: str = Query(
        ...,
        pattern=r"^(brand_new|like_new|very_good|good|acceptable)$",
    ),
    brand: str | None = Query(default=None),
    user: User = Depends(require_kyc),
    redis: Redis = Depends(get_redis),
):
    """Fair value estimate from comparable completed auctions.

    FR-AI-001: Queries ClickHouse auction_results_mv for comparables
    (same category, similar condition, sold in last 90 days).
    Returns price range (integer cents), suggested start, confidence.

    Auth: require_kyc.
    Rate limit: 20 requests per minute per user (Redis sliding window).
    Cached in Redis for 1 hour per (category, condition, brand).
    """
    from app.services.ai.price_oracle import get_price_estimate, check_rate_limit

    # Rate limit: 20/min per user
    allowed = await check_rate_limit(user.id, redis, max_per_minute=20)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "RATE_LIMIT_EXCEEDED",
                "message_en": "Price oracle rate limit exceeded (20/min)",
                "message_ar": "تم تجاوز حد الطلبات لتقدير السعر",
            },
        )

    result = await get_price_estimate(category_id, condition, brand, redis)
    return schemas.PriceOracleResponse(**result)


@router.post("/moderate", response_model=schemas.ModerationResponse)
async def moderate_listing(
    body: schemas.ModerationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Content moderation scoring — auto-approve if score < 30."""
    return await service.moderate_listing(body, db)


@router.post("/fraud-score", response_model=schemas.FraudScoreResponse)
async def fraud_score(
    body: schemas.FraudScoreRequest,
    db: AsyncSession = Depends(get_db),
):
    """Bid fraud pattern analysis."""
    return await service.score_fraud(body, db)
