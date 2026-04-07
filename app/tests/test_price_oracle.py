"""
Price Oracle tests — FR-AI-001.

Covers: ClickHouse comparable queries, statistics computation,
confidence levels, Redis caching, ML model loading/prediction,
GET endpoint with query params, no-comparables case, model training.
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from app.services.ai.price_oracle import (
    CONDITION_MAP,
    _compute_statistics,
    _determine_confidence,
    _cache_key,
    get_price_estimate,
    train_price_model,
)


# ── Unit: Condition encoding ──────────────────────────────────

class TestConditionEncoding:
    def test_all_conditions_mapped(self):
        expected = {"new": 5, "like_new": 4, "good": 3, "fair": 2, "for_parts": 1}
        assert CONDITION_MAP == expected

    def test_unknown_condition_defaults_to_3(self):
        """Service code uses .get(condition, 3) for unknown conditions."""
        assert CONDITION_MAP.get("unknown", 3) == 3


# ── Unit: Confidence levels ───────────────────────────────────

class TestConfidenceLevels:
    def test_high_confidence(self):
        assert _determine_confidence(20) == "high"
        assert _determine_confidence(100) == "high"

    def test_medium_confidence(self):
        assert _determine_confidence(10) == "medium"
        assert _determine_confidence(19) == "medium"

    def test_low_confidence(self):
        assert _determine_confidence(3) == "low"
        assert _determine_confidence(9) == "low"

    def test_none_confidence(self):
        assert _determine_confidence(0) == "none"
        assert _determine_confidence(2) == "none"

    def test_boundary_at_min_comparables(self):
        """Exactly at PRICE_ORACLE_MIN_COMPARABLES (3) → low."""
        assert _determine_confidence(3) == "low"


# ── Unit: Statistics computation ──────────────────────────────

class TestComputeStatistics:
    def test_basic_stats(self):
        comparables = [
            {"final_price": 100.0},
            {"final_price": 200.0},
            {"final_price": 300.0},
            {"final_price": 400.0},
            {"final_price": 500.0},
        ]
        stats = _compute_statistics(comparables)
        assert stats["median"] == 300.0
        assert stats["mean"] == 300.0
        assert stats["min"] == 100.0
        assert stats["max"] == 500.0
        assert stats["p10"] > 0
        assert stats["p90"] > 0
        assert stats["p10"] < stats["p90"]

    def test_single_comparable(self):
        comparables = [{"final_price": 150.0}]
        stats = _compute_statistics(comparables)
        assert stats["median"] == 150.0
        assert stats["p10"] == 150.0
        assert stats["p90"] == 150.0

    def test_two_comparables(self):
        comparables = [{"final_price": 100.0}, {"final_price": 200.0}]
        stats = _compute_statistics(comparables)
        assert stats["median"] == 150.0


# ── Unit: Cache key ───────────────────────────────────────────

class TestCacheKey:
    def test_with_brand(self):
        key = _cache_key(1, "new", "Toyota")
        assert key == "price_oracle:1:new:Toyota"

    def test_without_brand(self):
        key = _cache_key(1, "new", None)
        assert key == "price_oracle:1:new:_"

    def test_different_params_different_keys(self):
        k1 = _cache_key(1, "new", "Toyota")
        k2 = _cache_key(1, "good", "Toyota")
        k3 = _cache_key(2, "new", "Toyota")
        assert k1 != k2 != k3


# ── Integration: get_price_estimate ───────────────────────────

class TestGetPriceEstimate:
    """Core Price Oracle flow with mocked ClickHouse."""

    def _make_comparables(self, count: int, base_price: float = 100.0) -> list[dict]:
        """Generate mock comparables with varying prices."""
        return [
            {
                "final_price": base_price + i * 10.0,
                "condition": "good",
                "brand_id": 1,
                "days_since_sold": i + 1,
            }
            for i in range(count)
        ]

    @pytest.mark.asyncio
    async def test_happy_path_with_comparables(self, fake_redis):
        """20+ comparables → high confidence with price range."""
        comparables = self._make_comparables(25, base_price=100.0)

        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=comparables,
        ), patch(
            "app.services.ai.price_oracle._load_model",
            return_value=None,
        ):
            result = await get_price_estimate(1, "good", None, fake_redis)

        assert result["confidence"] == "high"
        assert result["comparable_count"] == 25
        assert result["price_low"] is not None
        assert result["price_high"] is not None
        assert result["median"] is not None
        assert result["suggested_start"] is not None
        assert result["price_low"] <= result["median"] <= result["price_high"]

    @pytest.mark.asyncio
    async def test_medium_confidence(self, fake_redis):
        """10-19 comparables → medium confidence."""
        comparables = self._make_comparables(12)

        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=comparables,
        ), patch(
            "app.services.ai.price_oracle._load_model",
            return_value=None,
        ):
            result = await get_price_estimate(1, "new", None, fake_redis)

        assert result["confidence"] == "medium"
        assert result["comparable_count"] == 12

    @pytest.mark.asyncio
    async def test_low_confidence(self, fake_redis):
        """3-9 comparables → low confidence."""
        comparables = self._make_comparables(5)

        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=comparables,
        ), patch(
            "app.services.ai.price_oracle._load_model",
            return_value=None,
        ):
            result = await get_price_estimate(2, "fair", None, fake_redis)

        assert result["confidence"] == "low"
        assert result["comparable_count"] == 5
        assert result["price_low"] is not None

    @pytest.mark.asyncio
    async def test_no_comparables_returns_none(self, fake_redis):
        """0 comparables → confidence=none, null prices."""
        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=[],
        ):
            result = await get_price_estimate(99, "new", "UnknownBrand", fake_redis)

        assert result["confidence"] == "none"
        assert result["comparable_count"] == 0
        assert result["price_low"] is None
        assert result["price_high"] is None
        assert result["median"] is None
        assert result["suggested_start"] is None

    @pytest.mark.asyncio
    async def test_below_min_comparables_returns_none(self, fake_redis):
        """2 comparables (below min 3) → confidence=none."""
        comparables = self._make_comparables(2)

        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=comparables,
        ):
            result = await get_price_estimate(1, "new", None, fake_redis)

        assert result["confidence"] == "none"
        assert result["price_low"] is None

    @pytest.mark.asyncio
    async def test_redis_cache_hit(self, fake_redis):
        """Second call returns cached result without querying ClickHouse."""
        comparables = self._make_comparables(15)

        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=comparables,
        ) as mock_ch, patch(
            "app.services.ai.price_oracle._load_model",
            return_value=None,
        ):
            result1 = await get_price_estimate(1, "good", None, fake_redis)
            result2 = await get_price_estimate(1, "good", None, fake_redis)

        # ClickHouse only called once — second call hit cache
        assert mock_ch.call_count == 1
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_cache_key_varies_by_brand(self, fake_redis):
        """Different brand → different cache key → separate queries."""
        comparables = self._make_comparables(10)

        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=comparables,
        ) as mock_ch, patch(
            "app.services.ai.price_oracle._load_model",
            return_value=None,
        ):
            await get_price_estimate(1, "good", "Toyota", fake_redis)
            await get_price_estimate(1, "good", "Honda", fake_redis)

        assert mock_ch.call_count == 2

    @pytest.mark.asyncio
    async def test_cache_ttl_set_to_1_hour(self, fake_redis):
        """Cached result has 3600s TTL."""
        comparables = self._make_comparables(10)

        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=comparables,
        ), patch(
            "app.services.ai.price_oracle._load_model",
            return_value=None,
        ):
            await get_price_estimate(1, "good", None, fake_redis)

        key = "price_oracle:1:good:_"
        assert key in fake_redis._store
        assert fake_redis._ttls.get(key) == 3600

    @pytest.mark.asyncio
    async def test_with_ml_model(self, fake_redis):
        """When model is available, suggested_start uses ML prediction."""
        comparables = self._make_comparables(20, base_price=100.0)

        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([250.0])

        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=comparables,
        ), patch(
            "app.services.ai.price_oracle._load_model",
            return_value=mock_model,
        ):
            result = await get_price_estimate(1, "good", None, fake_redis)

        assert result["suggested_start"] is not None
        # ML prediction is clamped to [price_low, price_high]
        assert result["price_low"] <= result["suggested_start"] <= result["price_high"]

    @pytest.mark.asyncio
    async def test_ml_prediction_clamped_to_range(self, fake_redis):
        """ML prediction outside price range is clamped."""
        comparables = self._make_comparables(20, base_price=100.0)

        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([9999.0])  # way above range

        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=comparables,
        ), patch(
            "app.services.ai.price_oracle._load_model",
            return_value=mock_model,
        ):
            result = await get_price_estimate(1, "good", None, fake_redis)

        # Should be clamped to price_high
        assert result["suggested_start"] == result["price_high"]

    @pytest.mark.asyncio
    async def test_clickhouse_unavailable_returns_none(self, fake_redis):
        """ClickHouse down → empty comparables → confidence=none."""
        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=[],
        ):
            result = await get_price_estimate(1, "new", None, fake_redis)

        assert result["confidence"] == "none"
        assert result["comparable_count"] == 0

    @pytest.mark.asyncio
    async def test_brand_filter_passed_to_query(self, fake_redis):
        """Brand parameter is forwarded to ClickHouse query."""
        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=[],
        ) as mock_query:
            await get_price_estimate(1, "new", "Samsung", fake_redis)

        mock_query.assert_called_once_with(1, "new", "Samsung")


# ── Endpoint: GET /api/v1/ai/price-oracle ─────────────────────

class TestPriceOracleEndpoint:

    @pytest.mark.asyncio
    async def test_happy_path(self, client, fake_redis):
        comparables = [
            {"final_price": 100.0 + i * 10, "condition": "good",
             "brand_id": 1, "days_since_sold": i}
            for i in range(20)
        ]
        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=comparables,
        ), patch(
            "app.services.ai.price_oracle._load_model",
            return_value=None,
        ):
            resp = await client.get(
                "/api/v1/ai/price-oracle",
                params={"category_id": 1, "condition": "good"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["confidence"] == "high"
        assert data["comparable_count"] == 20
        assert data["price_low"] is not None
        assert data["price_high"] is not None
        assert data["suggested_start"] is not None

    @pytest.mark.asyncio
    async def test_with_brand_param(self, client, fake_redis):
        comparables = [
            {"final_price": 500.0, "condition": "new",
             "brand_id": 42, "days_since_sold": 5}
            for _ in range(10)
        ]
        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=comparables,
        ), patch(
            "app.services.ai.price_oracle._load_model",
            return_value=None,
        ):
            resp = await client.get(
                "/api/v1/ai/price-oracle",
                params={"category_id": 1, "condition": "new", "brand": "Toyota"},
            )

        assert resp.status_code == 200
        assert resp.json()["confidence"] == "medium"

    @pytest.mark.asyncio
    async def test_no_comparables(self, client, fake_redis):
        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=[],
        ):
            resp = await client.get(
                "/api/v1/ai/price-oracle",
                params={"category_id": 999, "condition": "for_parts"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["confidence"] == "none"
        assert data["comparable_count"] == 0
        assert data["price_low"] is None
        assert data["price_high"] is None

    @pytest.mark.asyncio
    async def test_missing_category_id(self, client):
        resp = await client.get(
            "/api/v1/ai/price-oracle",
            params={"condition": "new"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_condition(self, client):
        resp = await client.get(
            "/api/v1/ai/price-oracle",
            params={"category_id": 1},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_condition(self, client):
        resp = await client.get(
            "/api/v1/ai/price-oracle",
            params={"category_id": 1, "condition": "destroyed"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_category_id(self, client):
        resp = await client.get(
            "/api/v1/ai/price-oracle",
            params={"category_id": 0, "condition": "new"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_cached_response(self, client, fake_redis):
        """Second request hits cache — no ClickHouse query."""
        comparables = [
            {"final_price": 100.0 + i * 5, "condition": "good",
             "brand_id": 1, "days_since_sold": i}
            for i in range(15)
        ]
        with patch(
            "app.services.ai.price_oracle._query_comparables",
            return_value=comparables,
        ) as mock_ch, patch(
            "app.services.ai.price_oracle._load_model",
            return_value=None,
        ):
            resp1 = await client.get(
                "/api/v1/ai/price-oracle",
                params={"category_id": 5, "condition": "good"},
            )
            resp2 = await client.get(
                "/api/v1/ai/price-oracle",
                params={"category_id": 5, "condition": "good"},
            )

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json() == resp2.json()
        assert mock_ch.call_count == 1


# ── Model training ────────────────────────────────────────────

class TestModelTraining:

    def test_insufficient_data_skips(self):
        """Less than 50 rows → training skipped."""
        with patch(
            "app.core.clickhouse.query_rows",
            return_value=[{"category_id": 1, "condition_rank": 3,
                           "brand_id": 0, "days_since_sold": 5,
                           "final_price": 100.0}] * 10,
        ):
            result = train_price_model()

        assert result["status"] == "skipped"
        assert result["reason"] == "insufficient_data"

    def test_successful_training(self, tmp_path):
        """With enough data, model trains and saves."""
        rows = [
            {
                "category_id": (i % 5) + 1,
                "condition_rank": (i % 5) + 1,
                "brand_id": i % 10,
                "days_since_sold": i % 90,
                "final_price": 100.0 + (i % 5) * 50 + (i % 10) * 10,
            }
            for i in range(200)
        ]

        model_path = str(tmp_path / "test_model.joblib")

        with patch(
            "app.core.clickhouse.query_rows",
            return_value=rows,
        ), patch(
            "app.services.ai.price_oracle.settings"
        ) as mock_settings:
            mock_settings.PRICE_ORACLE_MODEL_PATH = model_path
            result = train_price_model()

        assert result["status"] == "trained"
        assert result["training_rows"] == 200
        assert result["mae"] >= 0
        assert result["r2"] is not None
        assert result["model_path"] == model_path

        # Verify model file was actually saved
        import os
        assert os.path.exists(model_path)

        # Verify model can be loaded and used
        import joblib
        model = joblib.load(model_path)
        pred = model.predict(np.array([[1, 3, 0, 30]]))
        assert len(pred) == 1
        assert pred[0] > 0
