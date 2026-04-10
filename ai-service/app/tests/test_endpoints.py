"""
AI service endpoint tests — FR-AI-001 through FR-AI-004.

Covers:
  - Snap-to-List: success, too-few-images validation
  - Moderation: clean content auto-approved, prohibited content flagged
  - Price oracle: returns estimate for valid category
  - Fraud score: normal bid → low score, very high bid → high score
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


# ═══════════════════════════════════════════════════════════════════
#  Snap-to-List
# ═══════════════════════════════════════════════════════════════════


class TestSnapToList:
    @pytest.mark.asyncio
    async def test_snap_to_list_success(self):
        """POST /api/snap-to-list with 3 valid keys → SnapResult."""
        mock_clip_result = {
            "category_id": 1,
            "category_name_en": "Electronics",
            "category_name_ar": "إلكترونيات",
            "condition": "like_new",
            "brand": None,
            "confidence": 0.85,
        }
        mock_content = {
            "title_ar": "جهاز إلكتروني للمزاد",
            "title_en": "Electronic Device for Auction",
            "description_ar": "جهاز بحالة ممتازة",
            "description_en": "Excellent condition device",
        }

        with (
            patch(
                "app.api._download_image",
                new_callable=AsyncMock,
                return_value=b"fake_image_bytes",
            ),
            patch(
                "app.api.classify_image",
                new_callable=AsyncMock,
                return_value=mock_clip_result,
            ),
            patch(
                "app.api.generate_listing_content",
                new_callable=AsyncMock,
                return_value=mock_content,
            ),
            patch(
                "app.api.get_price_estimate",
                new_callable=AsyncMock,
            ) as mock_price,
        ):
            # Mock price oracle response object
            from app.models.schemas import PriceOracleResponse

            mock_price.return_value = PriceOracleResponse(
                price_low=5000,
                price_high=15000,
                price_mid=10000,
                suggested_start=4000,
                confidence="medium",
                comparable_count=0,
            )

            # Import app after patches are set up
            from app.main import app

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/snap-to-list",
                    json={"image_s3_keys": ["img1.jpg", "img2.jpg", "img3.jpg"]},
                )

            assert resp.status_code == 200
            data = resp.json()
            assert data["title_en"] == "Electronic Device for Auction"
            assert data["title_ar"] == "جهاز إلكتروني للمزاد"
            assert data["category_id"] == 1
            assert data["condition"] == "like_new"
            assert data["clip_confidence"] == 0.85
            assert data["price_estimate"] is not None
            assert data["price_estimate"]["price_low"] == 5000

    @pytest.mark.asyncio
    async def test_snap_to_list_too_few_images(self):
        """POST /api/snap-to-list with < 3 images → 422 validation error."""
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/snap-to-list",
                json={"image_s3_keys": ["img1.jpg", "img2.jpg"]},
            )

        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════
#  Moderation
# ═══════════════════════════════════════════════════════════════════


class TestModeration:
    @pytest.mark.asyncio
    async def test_moderate_clean_content(self):
        """Clean Arabic text → low score, auto_approve=True."""
        from app.services.moderation import moderate_content

        result = await moderate_content(
            listing_id="lst-001",
            title_ar="سيارة تويوتا كامري 2023",
            description_ar="سيارة بحالة ممتازة للبيع في عمان",
            image_urls=[],
        )
        assert result.score < 30
        assert result.auto_approve is True
        assert len(result.flags) == 0

    @pytest.mark.asyncio
    async def test_moderate_prohibited_content(self):
        """Text with weapon keywords → high score, not auto-approved."""
        from app.services.moderation import moderate_content

        result = await moderate_content(
            listing_id="lst-002",
            title_ar="مسدس للبيع",
            description_ar="سلاح ناري مع ذخيرة",
            image_urls=[],
        )
        assert result.score >= 40
        assert result.auto_approve is False
        assert any("weapons_keyword" in f for f in result.flags)

    @pytest.mark.asyncio
    async def test_moderate_drugs_content(self):
        """Text with drug keywords → high score."""
        from app.services.moderation import moderate_content

        result = await moderate_content(
            listing_id="lst-003",
            title_ar="حبوب مخدرة",
            description_ar="كبتاغون للبيع",
            image_urls=[],
        )
        assert result.score >= 50
        assert result.auto_approve is False
        assert any("drugs_keyword" in f for f in result.flags)

    @pytest.mark.asyncio
    async def test_moderate_contact_info(self):
        """Text with phone number → flagged."""
        from app.services.moderation import moderate_content

        result = await moderate_content(
            listing_id="lst-004",
            title_ar="جهاز للبيع",
            description_ar="تواصل معي على 0791234567",
            image_urls=[],
        )
        assert any("contact_info:phone_number" in f for f in result.flags)


# ═══════════════════════════════════════════════════════════════════
#  Price Oracle
# ═══════════════════════════════════════════════════════════════════


class TestPriceOracle:
    @pytest.mark.asyncio
    async def test_price_oracle_returns_estimate(self):
        """Valid category → returns price range with correct structure."""
        from app.services.price_oracle import _compute_estimate

        result = _compute_estimate(
            category_id=1,
            condition="like_new",
            brand=None,
        )
        assert result.price_low > 0
        assert result.price_high > result.price_low
        assert result.price_mid == (result.price_low + result.price_high) // 2
        assert result.suggested_start == int(result.price_low * 0.8)
        assert result.confidence == "low"  # No brand → low
        assert result.comparable_count == 0

    @pytest.mark.asyncio
    async def test_price_oracle_with_brand(self):
        """Known brand → medium confidence."""
        from app.services.price_oracle import _compute_estimate

        result = _compute_estimate(
            category_id=1,
            condition="brand_new",
            brand="Apple",
        )
        assert result.confidence == "medium"
        assert result.price_high > result.price_low

    @pytest.mark.asyncio
    async def test_price_oracle_unknown_category(self):
        """Unknown category ID → falls back to 'Other' (category 9)."""
        from app.services.price_oracle import _compute_estimate

        result = _compute_estimate(
            category_id=999,
            condition="good",
            brand=None,
        )
        # Should use category 9 (Other) range
        result_other = _compute_estimate(
            category_id=9,
            condition="good",
            brand=None,
        )
        assert result.price_low == result_other.price_low
        assert result.price_high == result_other.price_high

    @pytest.mark.asyncio
    async def test_price_oracle_endpoint(self):
        """POST /api/price-oracle returns valid response."""
        # Mock Redis to avoid connection
        with patch(
            "app.services.price_oracle._get_redis",
            new_callable=AsyncMock,
        ) as mock_redis:
            redis_mock = AsyncMock()
            redis_mock.get = AsyncMock(return_value=None)
            redis_mock.set = AsyncMock()
            mock_redis.return_value = redis_mock

            from app.main import app

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/price-oracle",
                    json={
                        "category_id": 1,
                        "condition": "like_new",
                    },
                )

            assert resp.status_code == 200
            data = resp.json()
            assert "price_low" in data
            assert "price_high" in data
            assert "confidence" in data


# ═══════════════════════════════════════════════════════════════════
#  Fraud Score
# ═══════════════════════════════════════════════════════════════════


class TestFraudScore:
    @pytest.mark.asyncio
    async def test_fraud_score_normal_bid(self):
        """Normal bid amount → low score, no risk factors."""
        from app.services.fraud import score_fraud

        result = await score_fraud(
            user_id="user-001",
            auction_id="auc-001",
            bid_amount=50_000,  # 500 JOD — normal
        )
        assert result.score < 20
        assert "very_high_bid_amount" not in str(result.risk_factors)

    @pytest.mark.asyncio
    async def test_fraud_score_very_high_bid(self):
        """50K+ JOD bid (5M+ cents) → high score."""
        from app.services.fraud import score_fraud

        result = await score_fraud(
            user_id="user-001",
            auction_id="auc-001",
            bid_amount=5_100_000,  # 51,000 JOD — very high
        )
        assert result.score >= 40
        assert any("very_high_bid_amount" in f for f in result.risk_factors)

    @pytest.mark.asyncio
    async def test_fraud_score_high_bid(self):
        """10K+ JOD bid → moderate score."""
        from app.services.fraud import score_fraud

        result = await score_fraud(
            user_id="user-001",
            auction_id="auc-001",
            bid_amount=1_500_000,  # 15,000 JOD — high but not very high
        )
        assert result.score >= 20
        assert any("high_bid_amount" in f for f in result.risk_factors)

    @pytest.mark.asyncio
    async def test_fraud_score_negative_bid(self):
        """Negative bid amount → high score."""
        from app.services.fraud import score_fraud

        result = await score_fraud(
            user_id="user-001",
            auction_id="auc-001",
            bid_amount=-100,
        )
        assert result.score >= 50
        assert any("non_positive" in f for f in result.risk_factors)

    @pytest.mark.asyncio
    async def test_fraud_score_round_number(self):
        """Round-number bid → small bump."""
        from app.services.fraud import score_fraud

        result = await score_fraud(
            user_id="user-001",
            auction_id="auc-001",
            bid_amount=10_000,  # Exactly 100 JOD
        )
        assert any("round_number_bid" in f for f in result.risk_factors)

    @pytest.mark.asyncio
    async def test_fraud_score_endpoint(self):
        """POST /api/fraud-score returns valid response."""
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/fraud-score",
                json={
                    "user_id": "user-001",
                    "auction_id": "auc-001",
                    "bid_amount": 50_000,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data
        assert "risk_factors" in data
