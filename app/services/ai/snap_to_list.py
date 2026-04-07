"""
Snap-to-List pipeline — FR-LIST-002, PM-04.

Takes 3-20 images, runs CLIP + GPT-4o + Price Oracle to produce
a complete listing draft. Must complete within 8s P90.

Pipeline stages:
1. Download images from S3
2. CLIP ViT-B/32: category prediction (top-3), brand/model OCR attempt
3. GPT-4o: bilingual title + description generation
4. Price Oracle: price range from comparable sales
5. Assemble full draft response

Fallbacks:
- CLIP confidence < 40%: category="Other", log AI-LOWCONF
- GPT-4o fails: return CLIP result with blank descriptions
- Total time > 8s: return partial result, log AI-TIMEOUT
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import Any

from app.core.config import settings
from app.services.ai.schemas import (
    CategoryCandidate,
    SnapToListRequest,
    SnapToListResponse,
)

logger = logging.getLogger(__name__)

# ── Category mapping (CLIP label → category_id) ──────────────

CATEGORY_MAP: dict[str, int] = {
    "electronics": 1,
    "vehicles": 2,
    "real_estate": 3,
    "fashion": 4,
    "home_furniture": 5,
    "sports": 6,
    "collectibles": 7,
    "jewelry": 8,
    "art": 9,
    "books": 10,
    "toys": 11,
    "music": 12,
    "tools": 13,
    "pets": 14,
    "other": 99,
}

CLIP_LABELS = list(CATEGORY_MAP.keys())

# ── Condition estimation heuristic ────────────────────────────

CONDITION_DEFAULT = "good"


# ── Stage 1: S3 image download ────────────────────────────────

async def download_images_from_s3(s3_keys: list[str]) -> list[bytes]:
    """Download images from S3. Returns list of image bytes.
    Non-blocking via run_in_executor for boto3 sync calls."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download_sync, s3_keys)


def _download_sync(s3_keys: list[str]) -> list[bytes]:
    """Sync S3 download — runs in thread pool."""
    try:
        import boto3
        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        bucket = settings.S3_BUCKET_MEDIA
        images = []
        for key in s3_keys:
            obj = s3.get_object(Bucket=bucket, Key=key)
            images.append(obj["Body"].read())
        return images
    except Exception as exc:
        logger.warning("S3 download failed: %s", exc)
        return []


# ── Stage 2: CLIP classification ──────────────────────────────

async def run_clip_classification(
    image_bytes_list: list[bytes],
) -> dict[str, Any]:
    """Run CLIP ViT-B/32 on images for category prediction and brand OCR.

    Returns:
        {
            "categories": [{"name": str, "category_id": int, "confidence": float}, ...],
            "brand": str | None,
            "condition": str,
            "clip_confidence": float,
        }
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _clip_classify_sync, image_bytes_list,
    )


def _clip_classify_sync(image_bytes_list: list[bytes]) -> dict[str, Any]:
    """Sync CLIP classification — runs in thread pool.

    Uses CLIP ViT-B/32 to classify the primary image against
    category labels. Falls back gracefully if CLIP is unavailable.
    """
    try:
        import torch
        import clip
        from PIL import Image

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model, preprocess = clip.load("ViT-B/32", device=device)

        # Use primary image (first)
        img = Image.open(io.BytesIO(image_bytes_list[0]))
        image_input = preprocess(img).unsqueeze(0).to(device)

        # Classify against category labels
        text_inputs = clip.tokenize(
            [f"a photo of {label}" for label in CLIP_LABELS]
        ).to(device)

        with torch.no_grad():
            image_features = model.encode_image(image_input)
            text_features = model.encode_text(text_inputs)
            similarity = (image_features @ text_features.T).softmax(dim=-1)
            probs = similarity[0].cpu().numpy()

        # Top-3 categories
        top_indices = probs.argsort()[-3:][::-1]
        categories = []
        for idx in top_indices:
            label = CLIP_LABELS[idx]
            categories.append({
                "name": label,
                "category_id": CATEGORY_MAP[label],
                "confidence": round(float(probs[idx]) * 100, 2),
            })

        # Brand OCR attempt — simplified via CLIP text similarity
        brand = None  # Full OCR is Phase 2

        return {
            "categories": categories,
            "brand": brand,
            "condition": CONDITION_DEFAULT,
            "clip_confidence": categories[0]["confidence"] if categories else 0.0,
        }

    except Exception as exc:
        logger.warning("CLIP classification failed: %s", exc)
        return _clip_fallback()


def _clip_fallback() -> dict[str, Any]:
    """Fallback when CLIP is unavailable."""
    return {
        "categories": [
            {"name": "other", "category_id": 99, "confidence": 0.0},
        ],
        "brand": None,
        "condition": CONDITION_DEFAULT,
        "clip_confidence": 0.0,
    }


# ── Stage 3: GPT-4o description generation ───────────────────

async def generate_descriptions(
    category: str,
    brand: str | None,
    condition: str,
) -> dict[str, str] | None:
    """Call GPT-4o to generate bilingual title + description.

    Returns dict with title_ar, title_en, description_ar, description_en
    or None if GPT-4o is unavailable.
    """
    if not settings.OPENAI_API_KEY:
        logger.warning("OpenAI API key not configured")
        return None

    try:
        import httpx

        brand_text = f" ({brand})" if brand else ""
        prompt = (
            f"You are a bilingual Arabic/English auction listing writer for MZADAK marketplace.\n"
            f"Generate a listing for an item in the '{category}' category{brand_text}, "
            f"condition: {condition}.\n\n"
            f"Return ONLY valid JSON with these exact keys:\n"
            f"- title_ar: Arabic title (max 80 characters)\n"
            f"- title_en: English title (max 80 characters)\n"
            f"- description_ar: Arabic description (200-500 words, detailed)\n"
            f"- description_en: English description (200-500 words, detailed)\n\n"
            f"Make the descriptions compelling for auction buyers. "
            f"Include condition details, potential uses, and value proposition."
        )

        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.OPENAI_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            import json
            result = json.loads(content)

            # Validate required keys exist
            for key in ("title_ar", "title_en", "description_ar", "description_en"):
                if key not in result:
                    raise ValueError(f"Missing key: {key}")

            # Enforce title length
            result["title_ar"] = result["title_ar"][:80]
            result["title_en"] = result["title_en"][:80]

            return result

    except Exception as exc:
        logger.warning("GPT-4o generation failed: %s", exc)
        return None


# ── Stage 4: Price Oracle ─────────────────────────────────────

async def get_price_estimate(
    category_id: int,
    condition: str,
    brand: str | None,
    redis,
) -> dict[str, Any]:
    """Reuse existing Price Oracle for price range."""
    try:
        from app.services.ai.price_oracle import get_price_estimate as _get_price
        return await _get_price(category_id, condition, brand, redis)
    except Exception:
        logger.warning("Price Oracle unavailable for snap-to-list")
        return {
            "price_low": None,
            "price_high": None,
            "suggested_start": None,
            "confidence": "none",
            "comparable_count": 0,
        }


# ── Main pipeline ─────────────────────────────────────────────

async def run_snap_to_list_pipeline(
    request: SnapToListRequest,
    user_id: str,
    redis,
) -> SnapToListResponse:
    """Execute the full Snap-to-List pipeline with 8s timeout.

    Stages:
    1. Download images from S3
    2. CLIP classification (category, brand, condition)
    3. GPT-4o description generation
    4. Price Oracle lookup
    5. Assemble response

    Falls back gracefully at each stage.
    """
    start = time.monotonic()
    timeout = settings.SNAP_TO_LIST_TIMEOUT
    warnings: list[str] = []
    partial = False

    # ── Stage 1: Download images ──────────────────────────────
    try:
        image_bytes = await asyncio.wait_for(
            download_images_from_s3(request.image_s3_keys),
            timeout=max(0.1, timeout - (time.monotonic() - start)),
        )
    except (asyncio.TimeoutError, Exception):
        image_bytes = []

    if not image_bytes:
        warnings.append("S3_DOWNLOAD_FAILED")
        logger.warning("S3 download failed for user=%s", user_id)
        # Return minimal fallback
        return _build_fallback_response(warnings=warnings + ["NO_IMAGES"])

    # ── Stage 2: CLIP classification ──────────────────────────
    elapsed = time.monotonic() - start
    remaining = timeout - elapsed

    try:
        clip_result = await asyncio.wait_for(
            run_clip_classification(image_bytes),
            timeout=max(0.1, remaining),
        )
    except asyncio.TimeoutError:
        clip_result = _clip_fallback()
        warnings.append("AI-TIMEOUT")
        partial = True

    categories = clip_result["categories"]
    top_category = categories[0] if categories else {"name": "other", "category_id": 99, "confidence": 0.0}
    clip_confidence = clip_result["clip_confidence"]
    brand = clip_result["brand"]
    condition = clip_result["condition"]

    # Low confidence check
    if clip_confidence < settings.SNAP_TO_LIST_CLIP_MIN_CONFIDENCE:
        top_category = {"name": "other", "category_id": 99, "confidence": clip_confidence}
        warnings.append("AI-LOWCONF")
        logger.info(
            "CLIP low confidence %.1f%% for user=%s, defaulting to Other",
            clip_confidence, user_id,
        )

    category_candidates = [
        CategoryCandidate(**c) for c in categories
    ]

    # Check timeout before GPT-4o
    elapsed = time.monotonic() - start
    remaining = timeout - elapsed

    if remaining < 1.0:
        # Not enough time for GPT-4o — return CLIP-only result
        warnings.append("AI-TIMEOUT")
        partial = True
        return _build_clip_only_response(
            top_category=top_category,
            category_candidates=category_candidates,
            brand=brand,
            condition=condition,
            clip_confidence=clip_confidence,
            warnings=warnings,
        )

    # ── Stage 3: GPT-4o descriptions ─────────────────────────
    try:
        gpt_result = await asyncio.wait_for(
            generate_descriptions(top_category["name"], brand, condition),
            timeout=max(0.5, remaining - 0.5),  # reserve 0.5s for price oracle
        )
    except asyncio.TimeoutError:
        gpt_result = None
        warnings.append("AI-TIMEOUT")
        partial = True

    if gpt_result is None:
        warnings.append("GPT4O_FAILED")
        return _build_clip_only_response(
            top_category=top_category,
            category_candidates=category_candidates,
            brand=brand,
            condition=condition,
            clip_confidence=clip_confidence,
            warnings=warnings,
        )

    # ── Stage 4: Price Oracle ─────────────────────────────────
    elapsed = time.monotonic() - start
    remaining = timeout - elapsed

    price_result = {"price_low": None, "price_high": None, "suggested_start": None}

    if remaining > 0.2:
        try:
            price_data = await asyncio.wait_for(
                get_price_estimate(
                    top_category["category_id"], condition, brand, redis,
                ),
                timeout=max(0.1, remaining),
            )
            price_result = {
                "price_low": price_data.get("price_low"),
                "price_high": price_data.get("price_high"),
                "suggested_start": price_data.get("suggested_start"),
            }
        except (asyncio.TimeoutError, Exception):
            warnings.append("PRICE_ORACLE_UNAVAILABLE")
    else:
        warnings.append("AI-TIMEOUT")
        partial = True

    # Check final timeout
    total_elapsed = time.monotonic() - start
    if total_elapsed > timeout:
        if "AI-TIMEOUT" not in warnings:
            warnings.append("AI-TIMEOUT")
        partial = True
        logger.warning(
            "Snap-to-list exceeded timeout: %.2fs for user=%s",
            total_elapsed, user_id,
        )

    return SnapToListResponse(
        title_ar=gpt_result["title_ar"],
        title_en=gpt_result["title_en"],
        description_ar=gpt_result["description_ar"],
        description_en=gpt_result["description_en"],
        category=top_category["name"],
        category_id=top_category["category_id"],
        category_candidates=category_candidates,
        condition=condition,
        brand=brand,
        price_low=price_result["price_low"],
        price_high=price_result["price_high"],
        suggested_start=price_result["suggested_start"],
        confidence=clip_confidence,
        partial=partial,
        warnings=warnings,
    )


# ── Fallback builders ─────────────────────────────────────────

def _build_fallback_response(
    warnings: list[str] | None = None,
) -> SnapToListResponse:
    """Minimal fallback when nothing works."""
    return SnapToListResponse(
        title_ar="",
        title_en="",
        description_ar="",
        description_en="",
        category="other",
        category_id=99,
        category_candidates=[],
        condition="good",
        brand=None,
        price_low=None,
        price_high=None,
        suggested_start=None,
        confidence=0.0,
        partial=True,
        warnings=warnings or ["PIPELINE_FAILED"],
    )


def _build_clip_only_response(
    top_category: dict,
    category_candidates: list[CategoryCandidate],
    brand: str | None,
    condition: str,
    clip_confidence: float,
    warnings: list[str],
) -> SnapToListResponse:
    """Fallback response with CLIP results only (no GPT-4o descriptions)."""
    return SnapToListResponse(
        title_ar="",
        title_en="",
        description_ar="",
        description_en="",
        category=top_category["name"],
        category_id=top_category["category_id"],
        category_candidates=category_candidates,
        condition=condition,
        brand=brand,
        price_low=None,
        price_high=None,
        suggested_start=None,
        confidence=clip_confidence,
        partial=True,
        warnings=warnings,
    )
