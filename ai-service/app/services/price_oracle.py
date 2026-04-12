"""Price oracle service — MVP with hardcoded ranges per category.

All prices are in integer cents (100 = 1 JOD).
Attempts ClickHouse query for real comparables first, falls back to
hardcoded base ranges when ClickHouse is unavailable.
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
    1: {"low": 5_000, "high": 150_000, "label": "Electronics"},           # 50-1500 JOD
    2: {"low": 200_000, "high": 5_000_000, "label": "Vehicles"},          # 2000-50000 JOD
    3: {"low": 1_000_000, "high": 20_000_000, "label": "Real Estate"},    # 10000-200000 JOD
    4: {"low": 10_000, "high": 500_000, "label": "Jewelry & Watches"},    # 100-5000 JOD
    5: {"low": 1_000, "high": 30_000, "label": "Fashion"},               # 10-300 JOD
    6: {"low": 5_000, "high": 200_000, "label": "Art & Collectibles"},    # 50-2000 JOD
    7: {"low": 3_000, "high": 100_000, "label": "Home & Garden"},         # 30-1000 JOD
    8: {"low": 2_000, "high": 50_000, "label": "Sports & Outdoors"},      # 20-500 JOD
    9: {"low": 1_000, "high": 50_000, "label": "Other"},                  # 10-500 JOD
    10: {"low": 10_000, "high": 300_000, "label": "Antiques"},            # 100-3000 JOD
    11: {"low": 500, "high": 10_000, "label": "Books & Media"},           # 5-100 JOD
    12: {"low": 50_000, "high": 1_000_000, "label": "Industrial Equipment"},  # 500-10000 JOD
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

    # Try ClickHouse for real comparables, fall back to hardcoded ranges
    result = await _try_clickhouse_estimate(category_id, condition, brand)
    if result is None:
        result = _compute_estimate(category_id, condition, brand)

    # Cache result
    try:
        r = await _get_redis()
        await r.set(cache_key, result.model_dump_json(), ex=3600)
    except Exception:
        logger.debug("Failed to cache price estimate")

    return result


async def _try_clickhouse_estimate(
    category_id: int,
    condition: str,
    brand: str | None,
) -> PriceOracleResponse | None:
    """Query ClickHouse auction_results_mv for real comparable sales.

    Returns None if ClickHouse is not configured or the query fails.
    """
    if not settings.CLICKHOUSE_URL:
        return None

    try:
        import httpx

        # Query completed auctions from the last 90 days
        brand_clause = ""
        if brand:
            brand_clause = f"AND lower(brand) = lower('{brand}')"

        query = f"""
            SELECT
                count() AS cnt,
                quantile(0.25)(final_price) AS p25,
                quantile(0.50)(final_price) AS p50,
                quantile(0.75)(final_price) AS p75,
                min(completed_at) AS earliest,
                max(completed_at) AS latest
            FROM auction_results_mv
            WHERE category_id = {category_id}
              AND condition = '{condition}'
              {brand_clause}
              AND completed_at >= now() - INTERVAL 90 DAY
        """

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                settings.CLICKHOUSE_URL,
                params={"query": query, "default_format": "JSONEachRow"},
            )
            resp.raise_for_status()
            rows = resp.json() if isinstance(resp.json(), list) else [resp.json()]

        if not rows or rows[0].get("cnt", 0) == 0:
            return None

        row = rows[0]
        comparable_count = int(row["cnt"])
        p25 = int(row["p25"])
        p50 = int(row["p50"])
        p75 = int(row["p75"])

        # Determine date range
        # Parse earliest/latest to compute days
        from datetime import datetime
        earliest = datetime.fromisoformat(str(row["earliest"]))
        latest = datetime.fromisoformat(str(row["latest"]))
        date_range_days = max(1, (latest - earliest).days)

        # Confidence: high (>=20 comparables, <=30d), medium (>=5, <=90d),
        # low (<5), none (0)
        confidence = _compute_confidence(comparable_count, date_range_days)

        suggested_start = int(p25 * 0.8) if p25 > 0 else None

        return PriceOracleResponse(
            price_low=p25,
            price_high=p75,
            price_mid=p50,
            suggested_start=suggested_start,
            confidence=confidence,
            comparable_count=comparable_count,
            date_range_days=date_range_days,
        )

    except Exception:
        logger.debug("ClickHouse query failed — falling back to hardcoded ranges")
        return None


def _compute_confidence(comparable_count: int, date_range_days: int | None) -> str:
    """Determine confidence level based on comparable count and date range.

    - high:   >= 20 comparables within <= 30 days
    - medium: >= 5 comparables within <= 90 days
    - low:    < 5 comparables (but > 0)
    - none:   0 comparables
    """
    if comparable_count == 0:
        return "none"
    if comparable_count >= 20 and (date_range_days is None or date_range_days <= 30):
        return "high"
    if comparable_count >= 5 and (date_range_days is None or date_range_days <= 90):
        return "medium"
    return "low"


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

    # No real comparables in fallback mode — confidence is low/medium based on brand
    has_brand = brand is not None and brand.strip() != ""
    confidence = "medium" if has_brand else "low"

    return PriceOracleResponse(
        price_low=price_low,
        price_high=price_high,
        price_mid=price_mid,
        suggested_start=suggested_start,
        confidence=confidence,
        comparable_count=0,  # No real comparables in fallback
        date_range_days=None,
    )
