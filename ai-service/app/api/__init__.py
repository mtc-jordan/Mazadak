"""AI service API endpoints."""

from __future__ import annotations

import io
import logging

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.models.schemas import (
    FraudScoreRequest,
    FraudScoreResponse,
    ModerationRequest,
    ModerationResponse,
    PriceEstimateSnap,
    PriceOracleRequest,
    PriceOracleResponse,
    SnapResult,
    SnapToListRequest,
)
from app.services.clip_service import classify_image
from app.services.content_generator import generate_listing_content
from app.services.fraud import score_fraud
from app.services.moderation import moderate_content
from app.services.price_oracle import get_price_estimate

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def root():
    return {"message": "MZADAK AI Service"}


@router.post("/snap-to-list", response_model=SnapResult)
async def snap_to_list(req: SnapToListRequest):
    """Snap-to-List: classify images, generate content, estimate price."""
    flags: list[str] = []
    partial = False

    # ---- Download first image from S3 (or use placeholder) ----------------
    image_bytes = await _download_image(req.image_s3_keys[0])
    if image_bytes is None:
        flags.append("image_download_failed")
        partial = True

    # ---- CLIP classification ----------------------------------------------
    if image_bytes:
        clip_result = await classify_image(image_bytes)
    else:
        clip_result = {
            "category_id": 9,
            "category_name_en": "Other",
            "category_name_ar": "أخرى",
            "condition": "good",
            "brand": None,
            "confidence": 0.0,
        }

    # ---- Content generation -----------------------------------------------
    content = await generate_listing_content(clip_result, len(req.image_s3_keys))

    # ---- Price estimate ---------------------------------------------------
    price_resp = await get_price_estimate(
        category_id=clip_result["category_id"],
        condition=clip_result["condition"],
        brand=clip_result.get("brand"),
    )
    price_estimate = PriceEstimateSnap(
        price_low=price_resp.price_low,
        price_high=price_resp.price_high,
        price_mid=price_resp.price_mid,
        suggested_start=price_resp.suggested_start,
        confidence=price_resp.confidence,
    )

    return SnapResult(
        title_ar=content["title_ar"],
        title_en=content["title_en"],
        description_ar=content["description_ar"],
        description_en=content["description_en"],
        category_id=clip_result["category_id"],
        category_name_en=clip_result["category_name_en"],
        category_name_ar=clip_result["category_name_ar"],
        condition=clip_result["condition"],
        brand=clip_result.get("brand"),
        model=clip_result.get("model"),
        clip_confidence=clip_result["confidence"],
        price_estimate=price_estimate,
        flags=flags,
        partial=partial,
    )


@router.post("/moderate", response_model=ModerationResponse)
async def moderate(req: ModerationRequest):
    """Moderate listing content for prohibited material."""
    return await moderate_content(
        listing_id=req.listing_id,
        title_ar=req.title_ar,
        description_ar=req.description_ar,
        image_urls=req.image_urls,
    )


@router.post("/price-oracle", response_model=PriceOracleResponse)
async def price_oracle(req: PriceOracleRequest):
    """Get price estimate for a category/condition/brand combination."""
    return await get_price_estimate(
        category_id=req.category_id,
        condition=req.condition,
        brand=req.brand,
    )


@router.post("/fraud-score", response_model=FraudScoreResponse)
async def fraud_score(req: FraudScoreRequest):
    """Score a bid for fraud risk."""
    return await score_fraud(
        user_id=req.user_id,
        auction_id=req.auction_id,
        bid_amount=req.bid_amount,
    )


# ---- Helpers --------------------------------------------------------------

async def _download_image(s3_key: str) -> bytes | None:
    """Download an image from S3. Returns None on failure."""
    if not settings.AWS_ACCESS_KEY_ID:
        logger.info("No AWS credentials — using placeholder image for %s", s3_key)
        return _placeholder_image()

    try:
        import boto3

        s3 = boto3.client(
            "s3",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
        response = s3.get_object(Bucket=settings.S3_BUCKET, Key=s3_key)
        return response["Body"].read()
    except Exception:
        logger.exception("Failed to download s3://%s/%s", settings.S3_BUCKET, s3_key)
        return None


def _placeholder_image() -> bytes:
    """Generate a small placeholder image for testing without S3."""
    from PIL import Image

    img = Image.new("RGB", (224, 224), color=(128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()
