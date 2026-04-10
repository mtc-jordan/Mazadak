"""
Snap-to-List pipeline tests — FR-LIST-002, PM-04.

Covers: full pipeline success, CLIP low confidence fallback,
GPT-4o timeout partial result, timing under 8s, price oracle
timeout non-blocking.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

import pytest

from app.services.ai.schemas import CLIPResult, OCRResult, PriceEstimateSnap, SnapResult
from app.services.ai.snap_pipeline import (
    run_snap_pipeline,
    run_clip_classification,
    run_ocr_extraction,
    run_gpt_listing,
    _assemble_draft,
    CATEGORY_OTHER,
)


# ── Helpers ──────────────────────────────────────────────────────

FAKE_IMAGE = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # minimal fake image bytes
FAKE_USER_ID = uuid4()


def _make_clip_result(**overrides) -> CLIPResult:
    defaults = {
        "category_id": 1,
        "category_name_en": "Electronics",
        "category_name_ar": "إلكترونيات",
        "confidence": 85.0,
        "condition_guess": "like_new",
        "brand_guess": None,
    }
    defaults.update(overrides)
    return CLIPResult(**defaults)


def _make_ocr_result(**overrides) -> OCRResult:
    defaults = {"brand": "Apple", "model": "iPhone 15 Pro", "storage": "256GB", "color": "Black"}
    defaults.update(overrides)
    return OCRResult(**defaults)


def _make_gpt_result(**overrides) -> dict:
    defaults = {
        "title_en": "Apple iPhone 15 Pro 256GB Black",
        "title_ar": "ابل ايفون 15 برو 256 جيجا اسود",
        "description_en": "Excellent condition iPhone 15 Pro with original accessories.",
        "description_ar": "ايفون 15 برو بحالة ممتازة مع جميع الملحقات الأصلية.",
        "condition": "like_new",
    }
    defaults.update(overrides)
    return defaults


# ── Test: full pipeline success ──────────────────────────────────

class TestFullPipelineSuccess:

    @pytest.mark.asyncio
    async def test_full_pipeline_success(self, fake_redis):
        """All phases succeed — result has title, description, category, price."""
        clip = _make_clip_result()
        ocr = _make_ocr_result()
        gpt = _make_gpt_result()
        price_data = {
            "price_low": 8000,
            "price_high": 12000,
            "price_mid": 10000,
            "suggested_start": 6800,
            "confidence": "high",
            "comparable_count": 25,
            "date_range_days": 20,
        }

        async def _fake_download(key):
            return FAKE_IMAGE

        async def _fake_clip(image_data):
            return clip

        async def _fake_ocr(images):
            return ocr

        async def _fake_gpt(clip_r, ocr_r, primary):
            return gpt

        async def _fake_price(cat, cond, brand, redis):
            return price_data

        with patch(
            "app.services.ai.snap_pipeline._download_s3_image", side_effect=_fake_download,
        ), patch(
            "app.services.ai.snap_pipeline.run_clip_classification", side_effect=_fake_clip,
        ), patch(
            "app.services.ai.snap_pipeline.run_ocr_extraction", side_effect=_fake_ocr,
        ), patch(
            "app.services.ai.snap_pipeline.run_gpt_listing", side_effect=_fake_gpt,
        ), patch(
            "app.services.ai.price_oracle.get_price_estimate", side_effect=_fake_price,
        ):
            result = await run_snap_pipeline(
                s3_keys=["media/1/img_a.jpg", "media/1/img_b.jpg"],
                user_id=FAKE_USER_ID,
                redis=fake_redis,
            )

        assert isinstance(result, SnapResult)
        assert result.title_en == "Apple iPhone 15 Pro 256GB Black"
        assert result.title_ar == "ابل ايفون 15 برو 256 جيجا اسود"
        assert result.description_en != ""
        assert result.description_ar != ""
        assert result.category_id == 1
        assert result.category_name_en == "Electronics"
        assert result.condition == "like_new"
        assert result.brand == "Apple"
        assert result.model == "iPhone 15 Pro"
        assert result.clip_confidence == 85.0
        assert result.price_estimate is not None
        assert result.price_estimate.price_low == 8000
        assert result.price_estimate.price_high == 12000
        assert result.price_estimate.confidence == "high"
        assert result.partial is False
        assert "AI_TIMEOUT" not in result.flags


# ── Test: CLIP low confidence fallback ───────────────────────────

class TestCLIPLowConfidence:

    @pytest.mark.asyncio
    async def test_clip_low_confidence_fallback(self, fake_redis):
        """CLIP confidence < 40 → category defaults to 'Other', AI_LOW_CONF flag."""
        low_clip = _make_clip_result(confidence=25.0, category_id=4, category_name_en="Fashion")
        ocr = _make_ocr_result(brand=None, model=None, storage=None, color=None)
        gpt = _make_gpt_result()

        async def _fake_download(key):
            return FAKE_IMAGE

        async def _fake_clip(image_data):
            return low_clip

        async def _fake_ocr(images):
            return ocr

        async def _fake_gpt(clip_r, ocr_r, primary):
            return gpt

        with patch(
            "app.services.ai.snap_pipeline._download_s3_image", side_effect=_fake_download,
        ), patch(
            "app.services.ai.snap_pipeline.run_clip_classification", side_effect=_fake_clip,
        ), patch(
            "app.services.ai.snap_pipeline.run_ocr_extraction", side_effect=_fake_ocr,
        ), patch(
            "app.services.ai.snap_pipeline.run_gpt_listing", side_effect=_fake_gpt,
        ):
            result = await run_snap_pipeline(
                s3_keys=["media/1/img_a.jpg"],
                user_id=FAKE_USER_ID,
                redis=None,
            )

        # Category should be overridden to "Other"
        assert result.category_id == CATEGORY_OTHER["id"]
        assert result.category_name_en == "Other"
        assert "AI_LOW_CONF" in result.flags
        # GPT still ran, so titles should exist
        assert result.title_en != ""


# ── Test: GPT-4o timeout returns partial ─────────────────────────

class TestGPTTimeout:

    @pytest.mark.asyncio
    async def test_gpt_timeout_returns_partial(self, fake_redis):
        """GPT-4o times out → result has CLIP data but empty descriptions."""
        clip = _make_clip_result()
        ocr = _make_ocr_result()

        async def _fake_download(key):
            return FAKE_IMAGE

        async def _fake_clip(image_data):
            return clip

        async def _fake_ocr(images):
            return ocr

        async def _fake_gpt_slow(clip_r, ocr_r, primary):
            # Simulate GPT-4o taking too long — will be cancelled by wait_for
            await asyncio.sleep(20)
            return _make_gpt_result()

        with patch(
            "app.services.ai.snap_pipeline._download_s3_image", side_effect=_fake_download,
        ), patch(
            "app.services.ai.snap_pipeline.run_clip_classification", side_effect=_fake_clip,
        ), patch(
            "app.services.ai.snap_pipeline.run_ocr_extraction", side_effect=_fake_ocr,
        ), patch(
            "app.services.ai.snap_pipeline.run_gpt_listing", side_effect=_fake_gpt_slow,
        ):
            result = await run_snap_pipeline(
                s3_keys=["media/1/img_a.jpg"],
                user_id=FAKE_USER_ID,
                redis=None,
            )

        # GPT timed out → descriptions are empty
        assert result.title_en == ""
        assert result.title_ar == ""
        assert result.description_en == ""
        assert result.description_ar == ""
        # CLIP data is still present
        assert result.category_id == 1
        assert result.clip_confidence == 85.0
        assert result.brand == "Apple"  # from OCR
        assert "AI_TIMEOUT" in result.flags
        assert "AI_PARTIAL" in result.flags


# ── Test: pipeline under 8 seconds ──────────────────────────────

class TestPipelineTiming:

    @pytest.mark.asyncio
    async def test_pipeline_under_8_seconds(self, fake_redis):
        """With instant mocked responses, pipeline completes well under 8s."""
        clip = _make_clip_result()
        ocr = _make_ocr_result()
        gpt = _make_gpt_result()

        async def _instant_download(key):
            return FAKE_IMAGE

        async def _instant_clip(image_data):
            return clip

        async def _instant_ocr(images):
            return ocr

        async def _instant_gpt(clip_r, ocr_r, primary):
            return gpt

        async def _instant_price(cat, cond, brand, redis):
            return {"price_low": 5000, "price_high": 8000, "price_mid": 6500,
                    "suggested_start": 4250, "confidence": "medium",
                    "comparable_count": 10, "date_range_days": 40}

        start = time.monotonic()

        with patch(
            "app.services.ai.snap_pipeline._download_s3_image", side_effect=_instant_download,
        ), patch(
            "app.services.ai.snap_pipeline.run_clip_classification", side_effect=_instant_clip,
        ), patch(
            "app.services.ai.snap_pipeline.run_ocr_extraction", side_effect=_instant_ocr,
        ), patch(
            "app.services.ai.snap_pipeline.run_gpt_listing", side_effect=_instant_gpt,
        ), patch(
            "app.services.ai.price_oracle.get_price_estimate", side_effect=_instant_price,
        ):
            result = await run_snap_pipeline(
                s3_keys=["media/1/img_a.jpg", "media/1/img_b.jpg", "media/1/img_c.jpg"],
                user_id=FAKE_USER_ID,
                redis=fake_redis,
            )

        elapsed = time.monotonic() - start

        assert elapsed < 8.0, f"Pipeline took {elapsed:.2f}s, must be < 8s"
        # With instant mocks it should be well under 1 second
        assert elapsed < 1.0, f"Pipeline took {elapsed:.2f}s with instant mocks"
        assert result.partial is False
        assert result.title_en != ""
        assert result.price_estimate is not None


# ── Test: price oracle timeout does not block result ─────────────

class TestPriceOracleTimeout:

    @pytest.mark.asyncio
    async def test_price_oracle_timeout_does_not_block_result(self, fake_redis):
        """Price oracle taking > 2s should not block the overall result."""
        clip = _make_clip_result()
        ocr = _make_ocr_result()
        gpt = _make_gpt_result()

        async def _fake_download(key):
            return FAKE_IMAGE

        async def _fake_clip(image_data):
            return clip

        async def _fake_ocr(images):
            return ocr

        async def _fake_gpt(clip_r, ocr_r, primary):
            return gpt

        async def _slow_price(cat, cond, brand, redis):
            await asyncio.sleep(10)  # way over 2s budget
            return {"price_low": 5000, "price_high": 8000, "price_mid": 6500,
                    "suggested_start": 4250, "confidence": "medium"}

        start = time.monotonic()

        with patch(
            "app.services.ai.snap_pipeline._download_s3_image", side_effect=_fake_download,
        ), patch(
            "app.services.ai.snap_pipeline.run_clip_classification", side_effect=_fake_clip,
        ), patch(
            "app.services.ai.snap_pipeline.run_ocr_extraction", side_effect=_fake_ocr,
        ), patch(
            "app.services.ai.snap_pipeline.run_gpt_listing", side_effect=_fake_gpt,
        ), patch(
            "app.services.ai.price_oracle.get_price_estimate", side_effect=_slow_price,
        ):
            result = await run_snap_pipeline(
                s3_keys=["media/1/img_a.jpg"],
                user_id=FAKE_USER_ID,
                redis=fake_redis,
            )

        elapsed = time.monotonic() - start

        # Pipeline should not wait more than ~2s for price oracle
        assert elapsed < 4.0, f"Pipeline took {elapsed:.2f}s — price oracle should not block"
        # Result should be complete except for price
        assert result.title_en != ""
        assert result.category_id == 1
        assert result.price_estimate is None  # timed out
        # But the rest of the draft is fine — not flagged as partial due to price timeout
        assert result.description_en != ""


# ── Test: assemble_draft helper ──────────────────────────────────

class TestAssembleDraft:

    def test_assemble_with_gpt(self):
        clip = _make_clip_result()
        ocr = _make_ocr_result()
        gpt = _make_gpt_result()

        result = _assemble_draft(clip, ocr, gpt)

        assert result.title_en == gpt["title_en"]
        assert result.title_ar == gpt["title_ar"]
        assert result.brand == "Apple"
        assert result.model == "iPhone 15 Pro"
        assert result.condition == "like_new"
        assert result.category_id == 1

    def test_assemble_without_gpt(self):
        clip = _make_clip_result()
        ocr = _make_ocr_result()

        result = _assemble_draft(clip, ocr, None)

        assert result.title_en == ""
        assert result.title_ar == ""
        assert result.condition == "like_new"  # from CLIP
        assert result.brand == "Apple"  # from OCR

    def test_assemble_no_ocr_brand_uses_clip(self):
        clip = _make_clip_result(brand_guess="Samsung")
        ocr = OCRResult()  # empty
        gpt = _make_gpt_result()

        result = _assemble_draft(clip, ocr, gpt)

        assert result.brand == "Samsung"  # falls back to clip brand_guess
