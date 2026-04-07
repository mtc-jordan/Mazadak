"""
AI service proxy — SDD §3.4.

Proxies requests to the GPU ai-service container. All AI outputs
are advisory — no irreversible platform action is taken solely
based on AI output. Every feature has a non-AI fallback.
"""

import time

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.ai.models import AIRequest
from app.services.ai.schemas import (
    FraudScoreRequest,
    FraudScoreResponse,
    ModerationRequest,
    ModerationResponse,
    PriceOracleRequest,
    PriceOracleResponse,
    SnapToListRequest,
    SnapToListResponse,
)

AI_SERVICE_BASE = "http://ai-service:8001/api"


async def _call_ai_service(
    path: str,
    payload: dict,
    request_type: str,
    user_id: str | None,
    listing_id: str | None,
    db: AsyncSession,
) -> dict:
    """Call the GPU ai-service and log the request."""
    ai_req = AIRequest(
        request_type=request_type,
        user_id=user_id,
        listing_id=listing_id,
        input_payload=payload,
        status="pending",
    )
    db.add(ai_req)
    await db.flush()

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{AI_SERVICE_BASE}{path}", json=payload)
            resp.raise_for_status()
            result = resp.json()

        ai_req.output_payload = result
        ai_req.latency_ms = (time.monotonic() - start) * 1000
        ai_req.status = "completed"
        ai_req.confidence = result.get("confidence")
    except Exception:
        ai_req.status = "failed"
        ai_req.latency_ms = (time.monotonic() - start) * 1000
        result = {}

    await db.commit()
    return result


async def snap_to_list(
    data: SnapToListRequest,
    user_id: str,
    db: AsyncSession,
) -> SnapToListResponse | None:
    """Image → listing draft via CLIP + GPT-4o + XGBoost pipeline."""
    result = await _call_ai_service(
        "/snap-to-list", data.model_dump(), "snap_to_list", user_id, None, db,
    )
    if not result:
        return None
    return SnapToListResponse(**result)


async def get_price_oracle(
    data: PriceOracleRequest,
    db: AsyncSession,
) -> PriceOracleResponse | None:
    """Fair value estimate via ClickHouse comparables + XGBoost."""
    result = await _call_ai_service(
        "/price-oracle", data.model_dump(), "price_oracle", None, None, db,
    )
    if not result:
        return None
    return PriceOracleResponse(**result)


async def moderate_listing(
    data: ModerationRequest,
    db: AsyncSession,
) -> ModerationResponse:
    """Content moderation — returns risk score 0-100."""
    result = await _call_ai_service(
        "/moderate", data.model_dump(), "moderate", None, data.listing_id, db,
    )
    if not result:
        # Fallback: route to manual moderation
        return ModerationResponse(score=50.0, flags=["ai_unavailable"], auto_approve=False)
    return ModerationResponse(**result)


async def score_fraud(
    data: FraudScoreRequest,
    db: AsyncSession,
) -> FraudScoreResponse:
    """Bid fraud pattern analysis."""
    result = await _call_ai_service(
        "/fraud-score", data.model_dump(), "fraud_score", data.user_id, None, db,
    )
    if not result:
        return FraudScoreResponse(score=0.0, risk_factors=[])
    return FraudScoreResponse(**result)
