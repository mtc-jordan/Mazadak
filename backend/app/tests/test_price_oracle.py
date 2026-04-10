"""
Price Oracle tests — FR-AI-001.

Covers: Redis cache hit/miss, confidence levels, search widening,
no-data handling, rate limiting.
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest

from app.services.ai.price_oracle import (
    get_price_estimate,
    check_rate_limit,
    _compute_statistics,
    _determine_confidence,
    _cache_key,
    _brand_slug,
    CONDITION_MAP,
)


# ── Helpers ──────────────────────────────────────────────────

def _make_comparable(
    final_price: int = 10000,
    condition: str = "like_new",
    days_since_end: int = 10,
    bid_count: int = 5,
    is_certified: bool = False,
) -> dict:
    return {
        "final_price": final_price,
        "condition": condition,
        "days_since_end": days_since_end,
        "bid_count": bid_count,
        "is_certified": is_certified,
    }


def _make_comparables(count: int, base_price: int = 10000, **kwargs) -> list[dict]:
    """Generate N comparable records with slightly varying prices."""
    return [
        _make_comparable(
            final_price=base_price + (i * 100),
            days_since_end=kwargs.get("days_since_end", i + 1),
            bid_count=kwargs.get("bid_count", 3 + i),
            **{k: v for k, v in kwargs.items() if k not in ("days_since_end", "bid_count")},
        )
        for i in range(count)
    ]


# ── Unit: helpers ────────────────────────────────────────────

class TestHelpers:

    def test_condition_map_has_all_values(self):
        assert set(CONDITION_MAP.keys()) == {
            "brand_new", "like_new", "very_good", "good", "acceptable",
        }
        assert CONDITION_MAP["brand_new"] == 5
        assert CONDITION_MAP["acceptable"] == 1

    def test_brand_slug_normalization(self):
        assert _brand_slug("Apple") == "apple"
        assert _brand_slug("Sam-Sung") == "samsung"
        assert _brand_slug(None) == "_"
        assert _brand_slug("") == "_"

    def test_cache_key_format(self):
        key = _cache_key(1, "like_new", "Apple")
        assert key == "price_oracle:1:like_new:apple"
        key_no_brand = _cache_key(1, "good", None)
        assert key_no_brand == "price_oracle:1:good:_"


# ── Unit: confidence ─────────────────────────────────────────

class TestConfidence:

    def test_high_confidence(self):
        assert _determine_confidence(25, 20) == "high"

    def test_high_needs_short_date_range(self):
        """20+ comparables but > 30 days -> medium, not high."""
        assert _determine_confidence(25, 45) == "medium"

    def test_medium_confidence(self):
        assert _determine_confidence(10, 60) == "medium"

    def test_low_confidence(self):
        assert _determine_confidence(3, 80) == "low"

    def test_none_confidence(self):
        assert _determine_confidence(0, 0) == "none"

    def test_boundary_high(self):
        assert _determine_confidence(20, 30) == "high"

    def test_boundary_medium(self):
        assert _determine_confidence(5, 90) == "medium"


# ── Unit: statistics ─────────────────────────────────────────

class TestStatistics:

    def test_compute_statistics(self):
        comparables = _make_comparables(20, base_price=10000)
        stats = _compute_statistics(comparables)
        assert stats["p10"] > 0
        assert stats["p50"] > 0
        assert stats["p90"] > stats["p10"]
        assert stats["date_range_days"] >= 0

    def test_statistics_all_same_price(self):
        comparables = [_make_comparable(final_price=5000) for _ in range(10)]
        stats = _compute_statistics(comparables)
        assert stats["p10"] == 5000
        assert stats["p50"] == 5000
        assert stats["p90"] == 5000


# ── Integration: cache hit ───────────────────────────────────

class TestCacheHit:

    @pytest.mark.asyncio
    async def test_oracle_cache_hit_no_clickhouse_query(self, fake_redis):
        """When Redis has cached result, ClickHouse is NOT queried."""
        cached_data = {
            "price_low": 8000,
            "price_high": 15000,
            "price_mid": 11000,
            "suggested_start": 6800,
            "confidence": "high",
            "comparable_count": 30,
            "date_range_days": 25,
        }
        cache_key = "price_oracle:1:like_new:apple"
        await fake_redis.set(cache_key, json.dumps(cached_data))

        with patch(
            "app.services.ai.price_oracle._query_with_widening"
        ) as mock_query:
            result = await get_price_estimate(1, "like_new", "Apple", fake_redis)

        # ClickHouse should NOT have been called
        mock_query.assert_not_called()

        # Result matches cached data
        assert result["price_low"] == 8000
        assert result["price_high"] == 15000
        assert result["confidence"] == "high"
        assert result["comparable_count"] == 30


# ── Integration: high confidence ─────────────────────────────

class TestHighConfidence:

    @pytest.mark.asyncio
    async def test_oracle_high_confidence_30_comparables(self, fake_redis):
        """30 comparables within 20 days -> high confidence."""
        comparables = _make_comparables(
            30, base_price=10000, days_since_end=10,
        )

        with patch(
            "app.services.ai.price_oracle._query_with_widening",
            return_value=(comparables, "exact"),
        ), patch(
            "app.services.ai.price_oracle._load_model",
            return_value=None,
        ):
            result = await get_price_estimate(1, "like_new", "Apple", fake_redis)

        assert result["confidence"] == "high"
        assert result["comparable_count"] == 30
        assert result["price_low"] is not None
        assert result["price_high"] is not None
        assert result["price_mid"] is not None
        assert result["suggested_start"] is not None
        # suggested_start should be ~85% of price_low
        assert result["suggested_start"] <= result["price_low"]
        assert result["price_low"] <= result["price_mid"] <= result["price_high"]


# ── Integration: search widening ─────────────────────────────

class TestSearchWidening:

    @pytest.mark.asyncio
    async def test_oracle_widens_search_when_few_results(self, fake_redis):
        """When exact search returns < 5, widens to no_brand/no_condition."""
        # Only 3 results from widened search (no_condition level)
        comparables = _make_comparables(3, base_price=8000)

        with patch(
            "app.services.ai.price_oracle._query_with_widening",
            return_value=(comparables, "no_condition"),
        ), patch(
            "app.services.ai.price_oracle._load_model",
            return_value=None,
        ):
            result = await get_price_estimate(1, "brand_new", "RareBrand", fake_redis)

        # Widened search caps confidence at "low"
        assert result["confidence"] == "low"
        assert result["comparable_count"] == 3
        assert result["price_low"] is not None


# ── Integration: no data ─────────────────────────────────────

class TestNoData:

    @pytest.mark.asyncio
    async def test_oracle_returns_none_confidence_when_no_data(self, fake_redis):
        """Empty ClickHouse result -> none confidence, null prices."""
        with patch(
            "app.services.ai.price_oracle._query_with_widening",
            return_value=([], "no_condition"),
        ):
            result = await get_price_estimate(99, "acceptable", None, fake_redis)

        assert result["confidence"] == "none"
        assert result["comparable_count"] == 0
        assert result["price_low"] is None
        assert result["price_high"] is None
        assert result["price_mid"] is None
        assert result["suggested_start"] is None
        assert result["date_range_days"] is None


# ── Rate limiting ────────────────────────────────────────────

class TestRateLimit:

    @pytest.mark.asyncio
    async def test_rate_limit_allows_under_threshold(self, fake_redis):
        user_id = str(uuid4())
        for _ in range(19):
            allowed = await check_rate_limit(user_id, fake_redis, max_per_minute=20)
            assert allowed is True

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_at_threshold(self, fake_redis):
        user_id = str(uuid4())
        for _ in range(20):
            await check_rate_limit(user_id, fake_redis, max_per_minute=20)

        blocked = await check_rate_limit(user_id, fake_redis, max_per_minute=20)
        assert blocked is False
