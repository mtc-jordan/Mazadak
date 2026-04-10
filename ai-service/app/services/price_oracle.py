"""Price oracle service — MVP with hardcoded ranges per category.

All prices are in integer cents (100 = 1 JOD).
"""

from __future__ import annotations

import json
import logging

import redis.asyncio as redis

from app.core.config import settings
from app.models.schemas import PriceOracleResponse

logger = logging.getLogger(__name__)

# ---- Hardcoded base price ranges (JOD cents) per category -----------------
# These represent realistic mid-market ranges for each MZADAK category.

BASE_RANGES: dict[int, dict] = {
    1: {"low": 5_000, "high": 150_000, "label": "Electronics"},         # 50-1500 JOD
    2: {"low": 200_000, "high": 5_000_000, "label": "Vehicles"},        # 2000-50000 JOD
    3: {"low": 1_000_000, "high": 20_000_000, "label": "Real Estate"},   # 10000-200000 JOD
    4: {"low": 10_000, "high": 500_000, "label": "Jewelry & Watches"},   # 100-5000 JOD
    5: {"low": 1_000, "high": 30_000, "label": "Fashion"},              # 10-300 JOD
    6: {"low": 5_000, "high": 200_000, "label": "Art & Collectibles"},   # 50-2000 JOD
    7: {"low": 3_000, "high": 100_000, "label": "Home & Garden"},        # 30-1000 JOD
    8: {"low": 2_000, "high": 50_000, "label": "Sports & Outdoors"},     # 20-500 JOD
    9: {"low": 1_000, "high": 50_000, "label": "Other"},                # 10-500 JOD
}

CONDITION_MULTIPLIERS: dict[str, float] = {
    "brand_new": 1.0,
    "like_new": 0.85,
    "very_good": 0.70,
    "good": 0.55,
    "acceptable": 0.40,
}

_redis_pool: redis.Redis | None = None


async def _get_redis() -> redis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_pool


async def get_price_estimate(
    category_id: int,
    condition: str,
    brand: str | None = None,
) -> PriceOracleResponse:
    """Return a price estimate for the given category/condition/brand."""
    cache_key = f"price:{category_id}:{condition}:{brand or 'none'}"

    # Check cache
    try:
        r = await _get_redis()
        cached = await r.get(cache_key)
        if cached:
            return PriceOracleResponse(**json.loads(cached))
    except Exception:
        logger.debug("Redis cache miss or unavailable for %s", cache_key)

    result = _compute_estimate(category_id, condition, brand)

    # Cache result
    try:
        r = await _get_redis()
        await r.set(cache_key, result.model_dump_json(), ex=3600)
    except Exception:
        logger.debug("Failed to cache price estimate")

    return result


def _compute_estimate(
    category_id: int,
    condition: str,
    brand: str | None,
) -> PriceOracleResponse:
    """Compute price estimate from hardcoded ranges."""
    base = BASE_RANGES.get(category_id, BASE_RANGES[9])
    mult = CONDITION_MULTIPLIERS.get(condition, 0.55)

    price_low = int(base["low"] * mult)
    price_high = int(base["high"] * mult)
    price_mid = (price_low + price_high) // 2
    suggested_start = int(price_low * 0.8)  # Suggest starting 20% below low estimate

    # Brand premium: if brand is known, bump confidence to medium
    has_brand = brand is not None and brand.strip() != ""
    confidence = "medium" if has_brand else "low"

    return PriceOracleResponse(
        price_low=price_low,
        price_high=price_high,
        price_mid=price_mid,
        suggested_start=suggested_start,
        confidence=confidence,
        comparable_count=0,  # MVP: no real comparables
        date_range_days=None,
    )
