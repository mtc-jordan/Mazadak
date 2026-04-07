"""
Snap-to-List tests — FR-LIST-002, PM-04.

Covers: full pipeline happy path, CLIP low confidence, GPT-4o failure,
timeout handling, S3 download failure, Price Oracle unavailable,
input validation (3-20 images), endpoint integration tests.

All external services (CLIP, GPT-4o, S3, Price Oracle) are mocked.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.schemas import SnapToListRequest, SnapToListResponse
from app.services.ai.snap_to_list import (
    CATEGORY_MAP,
    run_snap_to_list_pipeline,
    _build_fallback_response,
    _build_clip_only_response,
    _clip_fallback,
)


# ── Test helpers ──────────────────────────────────────────────

MOCK_IMAGE_BYTES = [b"fake_jpg_1", b"fake_jpg_2", b"fake_jpg_3"]

MOCK_CLIP_HIGH_CONF = {
    "categories": [
        {"name": "electronics", "category_id": 1, "confidence": 85.5},
        {"name": "collectibles", "category_id": 7, "confidence": 8.2},
        {"name": "toys", "category_id": 11, "confidence": 3.1},
    ],
    "brand": "Samsung",
    "condition": "like_new",
    "clip_confidence": 85.5,
}

MOCK_CLIP_LOW_CONF = {
    "categories": [
        {"name": "electronics", "category_id": 1, "confidence": 25.0},
        {"name": "other", "category_id": 99, "confidence": 20.0},
        {"name": "toys", "category_id": 11, "confidence": 15.0},
    ],
    "brand": None,
    "condition": "good",
    "clip_confidence": 25.0,
}

MOCK_GPT_RESULT = {
    "title_ar": "هاتف سامسونج جالاكسي S24 الترا",
    "title_en": "Samsung Galaxy S24 Ultra",
    "description_ar": "هاتف سامسونج جالاكسي S24 الترا بحالة ممتازة " * 10,
    "description_en": "Samsung Galaxy S24 Ultra in excellent condition " * 10,
}

MOCK_PRICE_RESULT = {
    "price_low": 200.0,
    "price_high": 500.0,
    "median": 350.0,
    "suggested_start": 300.0,
    "confidence": "high",
    "comparable_count": 25,
}


def _make_request(n_keys: int = 3) -> SnapToListRequest:
    return SnapToListRequest(
        image_s3_keys=[f"listings/test/img_{i}.jpg" for i in range(n_keys)]
    )


# ── Input validation ──────────────────────────────────────────

class TestSnapToListValidation:

    def test_min_3_images_required(self):
        with pytest.raises(Exception):
            SnapToListRequest(image_s3_keys=["a.jpg", "b.jpg"])

    def test_max_20_images(self):
        with pytest.raises(Exception):
            SnapToListRequest(
                image_s3_keys=[f"img_{i}.jpg" for i in range(21)]
            )

    def test_exactly_3_images_valid(self):
        req = SnapToListRequest(image_s3_keys=["a.jpg", "b.jpg", "c.jpg"])
        assert len(req.image_s3_keys) == 3

    def test_exactly_20_images_valid(self):
        req = SnapToListRequest(
            image_s3_keys=[f"img_{i}.jpg" for i in range(20)]
        )
        assert len(req.image_s3_keys) == 20


# ── CLIP fallback ─────────────────────────────────────────────

class TestClipFallback:

    def test_clip_fallback_returns_other(self):
        result = _clip_fallback()
        assert result["categories"][0]["name"] == "other"
        assert result["categories"][0]["category_id"] == 99
        assert result["clip_confidence"] == 0.0

    def test_category_map_has_other(self):
        assert "other" in CATEGORY_MAP
        assert CATEGORY_MAP["other"] == 99


# ── Pipeline: Happy path ─────────────────────────────────────

class TestPipelineHappyPath:

    @pytest.mark.asyncio
    async def test_full_pipeline_success(self, fake_redis):
        """All stages succeed → complete response with prices."""
        request = _make_request()

        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=MOCK_IMAGE_BYTES,
        ), patch(
            "app.services.ai.snap_to_list.run_clip_classification",
            new_callable=AsyncMock,
            return_value=MOCK_CLIP_HIGH_CONF,
        ), patch(
            "app.services.ai.snap_to_list.generate_descriptions",
            new_callable=AsyncMock,
            return_value=MOCK_GPT_RESULT,
        ), patch(
            "app.services.ai.snap_to_list.get_price_estimate",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_RESULT,
        ):
            result = await run_snap_to_list_pipeline(request, "user-1", fake_redis)

        assert isinstance(result, SnapToListResponse)
        assert result.title_ar == MOCK_GPT_RESULT["title_ar"]
        assert result.title_en == MOCK_GPT_RESULT["title_en"]
        assert result.description_ar != ""
        assert result.description_en != ""
        assert result.category == "electronics"
        assert result.category_id == 1
        assert len(result.category_candidates) == 3
        assert result.condition == "like_new"
        assert result.brand == "Samsung"
        assert result.price_low == 200.0
        assert result.price_high == 500.0
        assert result.suggested_start == 300.0
        assert result.confidence == 85.5
        assert result.partial is False
        assert len(result.warnings) == 0

    @pytest.mark.asyncio
    async def test_top3_category_candidates_returned(self, fake_redis):
        """CLIP returns top-3 categories with confidence scores."""
        request = _make_request()

        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=MOCK_IMAGE_BYTES,
        ), patch(
            "app.services.ai.snap_to_list.run_clip_classification",
            new_callable=AsyncMock,
            return_value=MOCK_CLIP_HIGH_CONF,
        ), patch(
            "app.services.ai.snap_to_list.generate_descriptions",
            new_callable=AsyncMock,
            return_value=MOCK_GPT_RESULT,
        ), patch(
            "app.services.ai.snap_to_list.get_price_estimate",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_RESULT,
        ):
            result = await run_snap_to_list_pipeline(request, "user-1", fake_redis)

        assert result.category_candidates[0].name == "electronics"
        assert result.category_candidates[0].confidence == 85.5
        assert result.category_candidates[1].name == "collectibles"
        assert result.category_candidates[2].name == "toys"


# ── Pipeline: CLIP low confidence ────────────────────────────

class TestClipLowConfidence:

    @pytest.mark.asyncio
    async def test_low_confidence_sets_category_other(self, fake_redis):
        """CLIP confidence < 40% → category becomes 'Other', AI-LOWCONF warning."""
        request = _make_request()

        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=MOCK_IMAGE_BYTES,
        ), patch(
            "app.services.ai.snap_to_list.run_clip_classification",
            new_callable=AsyncMock,
            return_value=MOCK_CLIP_LOW_CONF,
        ), patch(
            "app.services.ai.snap_to_list.generate_descriptions",
            new_callable=AsyncMock,
            return_value=MOCK_GPT_RESULT,
        ), patch(
            "app.services.ai.snap_to_list.get_price_estimate",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_RESULT,
        ):
            result = await run_snap_to_list_pipeline(request, "user-1", fake_redis)

        assert result.category == "other"
        assert result.category_id == 99
        assert "AI-LOWCONF" in result.warnings
        assert result.confidence == 25.0

    @pytest.mark.asyncio
    async def test_exactly_40_percent_not_low_conf(self, fake_redis):
        """Exactly 40% confidence is NOT low — threshold is strictly < 40."""
        clip_40 = {
            "categories": [
                {"name": "electronics", "category_id": 1, "confidence": 40.0},
            ],
            "brand": None,
            "condition": "good",
            "clip_confidence": 40.0,
        }
        request = _make_request()

        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=MOCK_IMAGE_BYTES,
        ), patch(
            "app.services.ai.snap_to_list.run_clip_classification",
            new_callable=AsyncMock,
            return_value=clip_40,
        ), patch(
            "app.services.ai.snap_to_list.generate_descriptions",
            new_callable=AsyncMock,
            return_value=MOCK_GPT_RESULT,
        ), patch(
            "app.services.ai.snap_to_list.get_price_estimate",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_RESULT,
        ):
            result = await run_snap_to_list_pipeline(request, "user-1", fake_redis)

        assert result.category == "electronics"
        assert result.category_id == 1
        assert "AI-LOWCONF" not in result.warnings


# ── Pipeline: GPT-4o failure ─────────────────────────────────

class TestGpt4oFailure:

    @pytest.mark.asyncio
    async def test_gpt4o_failure_returns_clip_only(self, fake_redis):
        """GPT-4o fails → CLIP result with blank descriptions."""
        request = _make_request()

        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=MOCK_IMAGE_BYTES,
        ), patch(
            "app.services.ai.snap_to_list.run_clip_classification",
            new_callable=AsyncMock,
            return_value=MOCK_CLIP_HIGH_CONF,
        ), patch(
            "app.services.ai.snap_to_list.generate_descriptions",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await run_snap_to_list_pipeline(request, "user-1", fake_redis)

        assert result.title_ar == ""
        assert result.title_en == ""
        assert result.description_ar == ""
        assert result.description_en == ""
        assert result.category == "electronics"
        assert result.category_id == 1
        assert result.brand == "Samsung"
        assert result.partial is True
        assert "GPT4O_FAILED" in result.warnings

    @pytest.mark.asyncio
    async def test_gpt4o_timeout_returns_clip_only(self, fake_redis):
        """GPT-4o times out → same as failure, blank descriptions."""
        request = _make_request()

        async def slow_gpt(*args, **kwargs):
            await asyncio.sleep(10)  # exceed timeout
            return MOCK_GPT_RESULT

        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=MOCK_IMAGE_BYTES,
        ), patch(
            "app.services.ai.snap_to_list.run_clip_classification",
            new_callable=AsyncMock,
            return_value=MOCK_CLIP_HIGH_CONF,
        ), patch(
            "app.services.ai.snap_to_list.generate_descriptions",
            side_effect=slow_gpt,
        ), patch(
            "app.services.ai.snap_to_list.settings"
        ) as mock_settings:
            mock_settings.SNAP_TO_LIST_TIMEOUT = 0.5
            mock_settings.SNAP_TO_LIST_CLIP_MIN_CONFIDENCE = 40.0
            result = await run_snap_to_list_pipeline(request, "user-1", fake_redis)

        assert result.partial is True
        assert result.title_ar == ""
        assert "AI-TIMEOUT" in result.warnings or "GPT4O_FAILED" in result.warnings


# ── Pipeline: S3 download failure ────────────────────────────

class TestS3DownloadFailure:

    @pytest.mark.asyncio
    async def test_s3_failure_returns_fallback(self, fake_redis):
        """S3 download fails → minimal fallback response."""
        request = _make_request()

        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await run_snap_to_list_pipeline(request, "user-1", fake_redis)

        assert result.category == "other"
        assert result.category_id == 99
        assert result.confidence == 0.0
        assert result.partial is True
        assert "S3_DOWNLOAD_FAILED" in result.warnings
        assert "NO_IMAGES" in result.warnings

    @pytest.mark.asyncio
    async def test_s3_timeout_returns_fallback(self, fake_redis):
        """S3 download times out → fallback."""
        request = _make_request()

        async def slow_s3(keys):
            await asyncio.sleep(10)
            return MOCK_IMAGE_BYTES

        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            side_effect=slow_s3,
        ), patch(
            "app.services.ai.snap_to_list.settings"
        ) as mock_settings:
            mock_settings.SNAP_TO_LIST_TIMEOUT = 0.2
            mock_settings.SNAP_TO_LIST_CLIP_MIN_CONFIDENCE = 40.0
            mock_settings.AWS_REGION = "me-south-1"
            mock_settings.S3_BUCKET_MEDIA = "test"
            result = await run_snap_to_list_pipeline(request, "user-1", fake_redis)

        assert result.partial is True
        assert "NO_IMAGES" in result.warnings or "S3_DOWNLOAD_FAILED" in result.warnings


# ── Pipeline: Price Oracle unavailable ───────────────────────

class TestPriceOracleUnavailable:

    @pytest.mark.asyncio
    async def test_price_oracle_failure_returns_null_prices(self, fake_redis):
        """Price Oracle fails → null prices but rest of response intact."""
        request = _make_request()

        async def failing_price(*args, **kwargs):
            raise Exception("ClickHouse down")

        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=MOCK_IMAGE_BYTES,
        ), patch(
            "app.services.ai.snap_to_list.run_clip_classification",
            new_callable=AsyncMock,
            return_value=MOCK_CLIP_HIGH_CONF,
        ), patch(
            "app.services.ai.snap_to_list.generate_descriptions",
            new_callable=AsyncMock,
            return_value=MOCK_GPT_RESULT,
        ), patch(
            "app.services.ai.snap_to_list.get_price_estimate",
            side_effect=failing_price,
        ):
            result = await run_snap_to_list_pipeline(request, "user-1", fake_redis)

        assert result.title_ar == MOCK_GPT_RESULT["title_ar"]
        assert result.category == "electronics"
        assert result.price_low is None
        assert result.price_high is None
        assert result.suggested_start is None
        assert "PRICE_ORACLE_UNAVAILABLE" in result.warnings

    @pytest.mark.asyncio
    async def test_price_oracle_no_comparables(self, fake_redis):
        """Price Oracle returns no comparables → null prices."""
        request = _make_request()
        no_data = {
            "price_low": None,
            "price_high": None,
            "suggested_start": None,
            "confidence": "none",
            "comparable_count": 0,
        }

        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=MOCK_IMAGE_BYTES,
        ), patch(
            "app.services.ai.snap_to_list.run_clip_classification",
            new_callable=AsyncMock,
            return_value=MOCK_CLIP_HIGH_CONF,
        ), patch(
            "app.services.ai.snap_to_list.generate_descriptions",
            new_callable=AsyncMock,
            return_value=MOCK_GPT_RESULT,
        ), patch(
            "app.services.ai.snap_to_list.get_price_estimate",
            new_callable=AsyncMock,
            return_value=no_data,
        ):
            result = await run_snap_to_list_pipeline(request, "user-1", fake_redis)

        assert result.price_low is None
        assert result.price_high is None
        assert result.partial is False  # pipeline still complete


# ── Pipeline: Timeout ─────────────────────────────────────────

class TestPipelineTimeout:

    @pytest.mark.asyncio
    async def test_overall_timeout_returns_partial(self, fake_redis):
        """Pipeline exceeding 8s returns partial result with AI-TIMEOUT."""
        request = _make_request()

        async def slow_clip(images):
            await asyncio.sleep(10)  # Exceed budget
            return MOCK_CLIP_HIGH_CONF

        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=MOCK_IMAGE_BYTES,
        ), patch(
            "app.services.ai.snap_to_list.run_clip_classification",
            side_effect=slow_clip,
        ), patch(
            "app.services.ai.snap_to_list.settings"
        ) as mock_settings:
            mock_settings.SNAP_TO_LIST_TIMEOUT = 0.3
            mock_settings.SNAP_TO_LIST_CLIP_MIN_CONFIDENCE = 40.0
            result = await run_snap_to_list_pipeline(request, "user-1", fake_redis)

        assert result.partial is True
        assert "AI-TIMEOUT" in result.warnings


# ── Fallback builders ─────────────────────────────────────────

class TestFallbackBuilders:

    def test_build_fallback_response(self):
        result = _build_fallback_response(warnings=["TEST_WARNING"])
        assert result.category == "other"
        assert result.category_id == 99
        assert result.confidence == 0.0
        assert result.partial is True
        assert "TEST_WARNING" in result.warnings

    def test_build_clip_only_response(self):
        from app.services.ai.schemas import CategoryCandidate
        result = _build_clip_only_response(
            top_category={"name": "electronics", "category_id": 1, "confidence": 60.0},
            category_candidates=[
                CategoryCandidate(name="electronics", category_id=1, confidence=60.0),
            ],
            brand="Sony",
            condition="good",
            clip_confidence=60.0,
            warnings=["GPT4O_FAILED"],
        )
        assert result.category == "electronics"
        assert result.category_id == 1
        assert result.brand == "Sony"
        assert result.title_ar == ""
        assert result.description_ar == ""
        assert result.partial is True
        assert "GPT4O_FAILED" in result.warnings


# ── Endpoint integration ──────────────────────────────────────

class TestSnapToListEndpoint:

    @pytest.mark.asyncio
    async def test_happy_path(self, client, verified_auth_headers, fake_redis):
        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=MOCK_IMAGE_BYTES,
        ), patch(
            "app.services.ai.snap_to_list.run_clip_classification",
            new_callable=AsyncMock,
            return_value=MOCK_CLIP_HIGH_CONF,
        ), patch(
            "app.services.ai.snap_to_list.generate_descriptions",
            new_callable=AsyncMock,
            return_value=MOCK_GPT_RESULT,
        ), patch(
            "app.services.ai.snap_to_list.get_price_estimate",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_RESULT,
        ):
            resp = await client.post(
                "/api/v1/ai/snap-to-list",
                json={"image_s3_keys": ["a.jpg", "b.jpg", "c.jpg"]},
                headers=verified_auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["title_ar"] == MOCK_GPT_RESULT["title_ar"]
        assert data["category"] == "electronics"
        assert data["category_id"] == 1
        assert len(data["category_candidates"]) == 3
        assert data["brand"] == "Samsung"
        assert data["price_low"] == 200.0
        assert data["confidence"] == 85.5
        assert data["partial"] is False

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        resp = await client.post(
            "/api/v1/ai/snap-to-list",
            json={"image_s3_keys": ["a.jpg", "b.jpg", "c.jpg"]},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_too_few_images_returns_422(self, client, verified_auth_headers):
        resp = await client.post(
            "/api/v1/ai/snap-to-list",
            json={"image_s3_keys": ["a.jpg"]},
            headers=verified_auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_too_many_images_returns_422(self, client, verified_auth_headers):
        resp = await client.post(
            "/api/v1/ai/snap-to-list",
            json={"image_s3_keys": [f"img_{i}.jpg" for i in range(21)]},
            headers=verified_auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_gpt4o_failure_returns_partial(self, client, verified_auth_headers, fake_redis):
        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=MOCK_IMAGE_BYTES,
        ), patch(
            "app.services.ai.snap_to_list.run_clip_classification",
            new_callable=AsyncMock,
            return_value=MOCK_CLIP_HIGH_CONF,
        ), patch(
            "app.services.ai.snap_to_list.generate_descriptions",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(
                "/api/v1/ai/snap-to-list",
                json={"image_s3_keys": ["a.jpg", "b.jpg", "c.jpg"]},
                headers=verified_auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["partial"] is True
        assert data["title_ar"] == ""
        assert data["category"] == "electronics"
        assert "GPT4O_FAILED" in data["warnings"]

    @pytest.mark.asyncio
    async def test_low_confidence_endpoint(self, client, verified_auth_headers, fake_redis):
        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=MOCK_IMAGE_BYTES,
        ), patch(
            "app.services.ai.snap_to_list.run_clip_classification",
            new_callable=AsyncMock,
            return_value=MOCK_CLIP_LOW_CONF,
        ), patch(
            "app.services.ai.snap_to_list.generate_descriptions",
            new_callable=AsyncMock,
            return_value=MOCK_GPT_RESULT,
        ), patch(
            "app.services.ai.snap_to_list.get_price_estimate",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_RESULT,
        ):
            resp = await client.post(
                "/api/v1/ai/snap-to-list",
                json={"image_s3_keys": ["a.jpg", "b.jpg", "c.jpg"]},
                headers=verified_auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "other"
        assert data["category_id"] == 99
        assert "AI-LOWCONF" in data["warnings"]

    @pytest.mark.asyncio
    async def test_s3_failure_endpoint(self, client, verified_auth_headers, fake_redis):
        with patch(
            "app.services.ai.snap_to_list.download_images_from_s3",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.post(
                "/api/v1/ai/snap-to-list",
                json={"image_s3_keys": ["a.jpg", "b.jpg", "c.jpg"]},
                headers=verified_auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["partial"] is True
        assert data["category"] == "other"
        assert "S3_DOWNLOAD_FAILED" in data["warnings"]
