"""
Snap-to-List pipeline — FR-LIST-002, PM-04.

Takes 1-10 S3 image keys, runs CLIP ViT-B/32 + GPT-4o OCR + GPT-4o listing
generation + Price Oracle to produce a bilingual listing draft.

Pipeline budget: < 8 s P90.

Phases:
1. Download images from S3 (concurrently, max 5)
2a. CLIP classification — primary image → category + condition guess
2b. OCR extraction — first 3 images → brand / model / storage / color
3. GPT-4o listing generation (needs CLIP + OCR output + primary image)
4. Price Oracle (non-blocking, 2 s timeout)

Fallbacks:
- CLIP confidence < 40 → category "Other", flag AI_LOW_CONF
- GPT-4o fails/timeout → return CLIP result with empty descriptions
- Total time > 8 s → return partial result with AI_TIMEOUT flag
- Price oracle timeout → result.price_estimate = None
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.services.ai.schemas import (
    CLIPResult,
    OCRResult,
    PriceEstimateSnap,
    SnapResult,
)

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────

PIPELINE_BUDGET_MS = 8000  # 8 s total budget

CATEGORY_LABELS: list[dict[str, Any]] = [
    {"id": 1, "en": "Electronics", "ar": "إلكترونيات", "clip": "a photo of electronics, gadgets, phones, laptops"},
    {"id": 2, "en": "Vehicles", "ar": "مركبات", "clip": "a photo of a car, truck, motorcycle, vehicle"},
    {"id": 3, "en": "Real Estate", "ar": "عقارات", "clip": "a photo of a house, apartment, building, real estate"},
    {"id": 4, "en": "Fashion", "ar": "أزياء", "clip": "a photo of clothing, shoes, fashion accessories"},
    {"id": 5, "en": "Home & Furniture", "ar": "أثاث ومنزل", "clip": "a photo of furniture, home decor, appliances"},
    {"id": 6, "en": "Sports", "ar": "رياضة", "clip": "a photo of sports equipment, fitness gear"},
    {"id": 7, "en": "Collectibles", "ar": "مقتنيات", "clip": "a photo of collectibles, antiques, rare items"},
    {"id": 8, "en": "Jewelry", "ar": "مجوهرات", "clip": "a photo of jewelry, watches, gems, rings"},
]

CATEGORY_OTHER = {"id": 99, "en": "Other", "ar": "أخرى"}

LISTING_SYSTEM_PROMPT = (
    "You are MZADAK's AI listing assistant for the Arab auction market.\n"
    "Generate concise, accurate bilingual auction listings.\n"
    "ALWAYS respond with valid JSON:\n"
    "{title_en, title_ar, description_en, description_ar, condition}\n"
    "Title max 80 chars. Description 200-400 words.\n"
    "Arabic must be Gulf/Jordanian dialect friendly.\n"
    "Be honest about condition. Never exaggerate."
)

# In-memory CLIP model cache (loaded once, reused)
_clip_model_cache: dict[str, Any] = {}


# ── Phase 1: S3 image download ─────────────────────────────────

async def _download_s3_image(key: str) -> bytes:
    """Download a single image from S3 (runs in thread pool)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _download_s3_sync, key)


def _download_s3_sync(key: str) -> bytes:
    import boto3

    s3 = boto3.client("s3", region_name=settings.AWS_REGION)
    obj = s3.get_object(Bucket=settings.S3_BUCKET_MEDIA, Key=key)
    return obj["Body"].read()


# ── Phase 2a: CLIP classification ──────────────────────────────

async def run_clip_classification(image_data: bytes) -> CLIPResult:
    """CLIP ViT-B/32 inference on primary image.

    Returns category prediction with confidence, optional condition guess
    and brand guess.  Model is cached in memory after first load.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _clip_sync, image_data)


def _clip_sync(image_data: bytes) -> CLIPResult:
    try:
        import torch
        import clip
        from PIL import Image

        # Load model (cached)
        if "model" not in _clip_model_cache:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model, preprocess = clip.load("ViT-B/32", device=device)
            _clip_model_cache["model"] = model
            _clip_model_cache["preprocess"] = preprocess
            _clip_model_cache["device"] = device

            # Pre-compute category text embeddings
            texts = clip.tokenize([c["clip"] for c in CATEGORY_LABELS]).to(device)
            with torch.no_grad():
                text_features = model.encode_text(texts)
                text_features /= text_features.norm(dim=-1, keepdim=True)
            _clip_model_cache["text_features"] = text_features

        model = _clip_model_cache["model"]
        preprocess = _clip_model_cache["preprocess"]
        device = _clip_model_cache["device"]
        text_features = _clip_model_cache["text_features"]

        img = Image.open(io.BytesIO(image_data)).convert("RGB")
        image_input = preprocess(img).unsqueeze(0).to(device)

        with torch.no_grad():
            image_features = model.encode_image(image_input)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            similarity = (image_features @ text_features.T).softmax(dim=-1)
            probs = similarity[0].cpu().numpy()

        best_idx = int(probs.argmax())
        confidence = round(float(probs[best_idx]) * 100, 2)
        cat = CATEGORY_LABELS[best_idx]

        # Simple condition heuristic from CLIP (pristine-looking → like_new)
        condition_guess = None
        cond_texts = clip.tokenize([
            "a brand new item in original packaging",
            "a used item in good condition",
            "a worn or damaged item",
        ]).to(device)
        with torch.no_grad():
            cond_features = model.encode_text(cond_texts)
            cond_features /= cond_features.norm(dim=-1, keepdim=True)
            cond_sim = (image_features @ cond_features.T).softmax(dim=-1)[0].cpu().numpy()

        cond_idx = int(cond_sim.argmax())
        condition_guess = ["like_new", "good", "acceptable"][cond_idx]

        return CLIPResult(
            category_id=cat["id"],
            category_name_en=cat["en"],
            category_name_ar=cat["ar"],
            confidence=confidence,
            condition_guess=condition_guess,
            brand_guess=None,
        )

    except Exception as exc:
        logger.warning("CLIP classification failed: %s", exc)
        return CLIPResult(
            category_id=CATEGORY_OTHER["id"],
            category_name_en=CATEGORY_OTHER["en"],
            category_name_ar=CATEGORY_OTHER["ar"],
            confidence=0.0,
            condition_guess="good",
            brand_guess=None,
        )


# ── Phase 2b: OCR extraction via GPT-4o vision ────────────────

async def run_ocr_extraction(images: list[bytes]) -> OCRResult:
    """Send first 3 images to GPT-4o vision to extract brand/model/storage/color."""
    if not settings.OPENAI_API_KEY:
        return OCRResult()

    try:
        import httpx

        # Build image content blocks (max 3 images)
        image_contents: list[dict] = []
        for img_bytes in images[:3]:
            b64 = base64.b64encode(img_bytes).decode()
            image_contents.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"},
            })

        image_contents.append({
            "type": "text",
            "text": (
                "Extract only: brand name, model name/number, storage capacity, color.\n"
                'Return JSON only: {"brand", "model", "storage", "color"}.\n'
                "If not visible, return null for that field."
            ),
        })

        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.OPENAI_MODEL,
                    "messages": [{"role": "user", "content": image_contents}],
                    "max_tokens": 200,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            return OCRResult(
                brand=data.get("brand"),
                model=data.get("model"),
                storage=data.get("storage"),
                color=data.get("color"),
            )
    except Exception as exc:
        logger.warning("OCR extraction failed: %s", exc)
        return OCRResult()


# ── Phase 3: GPT-4o listing generation ─────────────────────────

async def run_gpt_listing(
    clip_result: CLIPResult,
    ocr_result: OCRResult,
    primary_image: bytes,
) -> dict[str, str] | None:
    """Call GPT-4o with image + context to generate bilingual listing draft.

    Returns dict with title_en, title_ar, description_en, description_ar, condition
    or None on failure.
    """
    if not settings.OPENAI_API_KEY:
        return None

    try:
        import httpx

        # Build user prompt with context from CLIP + OCR
        parts: list[str] = [f"Category: {clip_result.category_name_en}"]
        if clip_result.condition_guess:
            parts.append(f"Condition estimate: {clip_result.condition_guess}")
        if ocr_result.brand:
            parts.append(f"Brand: {ocr_result.brand}")
        if ocr_result.model:
            parts.append(f"Model: {ocr_result.model}")
        if ocr_result.storage:
            parts.append(f"Storage: {ocr_result.storage}")
        if ocr_result.color:
            parts.append(f"Color: {ocr_result.color}")

        user_prompt = (
            "Based on this image and details, generate an auction listing.\n"
            + "\n".join(parts)
        )

        b64_image = base64.b64encode(primary_image).decode()

        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.OPENAI_MODEL,
                    "messages": [
                        {"role": "system", "content": LISTING_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{b64_image}",
                                        "detail": "low",
                                    },
                                },
                                {"type": "text", "text": user_prompt},
                            ],
                        },
                    ],
                    "max_tokens": 600,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)

            # Validate required keys
            for key in ("title_en", "title_ar", "description_en", "description_ar"):
                if key not in data:
                    raise ValueError(f"Missing key: {key}")

            # Enforce title length
            data["title_en"] = data["title_en"][:80]
            data["title_ar"] = data["title_ar"][:80]

            return data

    except Exception as exc:
        logger.warning("GPT-4o listing generation failed: %s", exc)
        return None


# ── Phase logging ──────────────────────────────────────────────

def _log_phase(
    phase: str,
    duration_ms: float,
    success: bool,
    user_id: UUID | str,
    **extra: Any,
) -> None:
    """Log pipeline phase metrics.  Writes to structured logger for
    ClickHouse ingestion via Fluent Bit / Vector."""
    logger.info(
        "snap_pipeline_phase",
        extra={
            "phase": phase,
            "duration_ms": round(duration_ms, 1),
            "success": success,
            "user_id": str(user_id),
            **extra,
        },
    )


# ── Assemble draft ─────────────────────────────────────────────

def _assemble_draft(
    clip_result: CLIPResult,
    ocr_result: OCRResult,
    gpt_result: dict[str, str] | None,
) -> SnapResult:
    """Combine outputs from all phases into a SnapResult."""
    if gpt_result:
        title_en = gpt_result.get("title_en", "")
        title_ar = gpt_result.get("title_ar", "")
        desc_en = gpt_result.get("description_en", "")
        desc_ar = gpt_result.get("description_ar", "")
        condition = gpt_result.get("condition", clip_result.condition_guess or "good")
    else:
        title_en = ""
        title_ar = ""
        desc_en = ""
        desc_ar = ""
        condition = clip_result.condition_guess or "good"

    brand = ocr_result.brand or clip_result.brand_guess

    return SnapResult(
        title_en=title_en,
        title_ar=title_ar,
        description_en=desc_en,
        description_ar=desc_ar,
        category_id=clip_result.category_id,
        category_name_en=clip_result.category_name_en,
        category_name_ar=clip_result.category_name_ar,
        condition=condition,
        brand=brand,
        model=ocr_result.model,
        clip_confidence=clip_result.confidence,
        price_estimate=None,
        flags=[],
        partial=False,
    )


# ── Main pipeline entry point ──────────────────────────────────

async def run_snap_pipeline(
    s3_keys: list[str],
    user_id: UUID,
    redis=None,
) -> SnapResult:
    """Execute the full Snap-to-List pipeline.

    Budget: 8 000 ms.  Uses asyncio.gather for parallelism wherever
    possible.  Returns partial results if the budget is exceeded.
    """
    start = time.monotonic()
    flags: list[str] = []

    def _elapsed_ms() -> float:
        return (time.monotonic() - start) * 1000

    def _remaining_ms() -> float:
        return PIPELINE_BUDGET_MS - _elapsed_ms()

    # ── Phase 1: Download images concurrently (max 5) ──────────
    t0 = time.monotonic()
    try:
        images: list[bytes] = await asyncio.wait_for(
            asyncio.gather(*[_download_s3_image(key) for key in s3_keys[:5]]),
            timeout=3.0,
        )
        # Filter out empty results
        images = [img for img in images if img]
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("S3 download failed/timed out: %s", exc)
        images = []

    _log_phase("download", _elapsed_ms(), bool(images), user_id)

    if not images:
        flags.append("AI_DOWNLOAD_FAILED")
        return SnapResult(
            title_en="", title_ar="",
            description_en="", description_ar="",
            category_id=CATEGORY_OTHER["id"],
            category_name_en=CATEGORY_OTHER["en"],
            category_name_ar=CATEGORY_OTHER["ar"],
            condition="good",
            clip_confidence=0.0,
            flags=flags + ["AI_PARTIAL"],
            partial=True,
        )

    # ── Phase 2: CLIP + OCR in parallel ────────────────────────
    if _remaining_ms() < 1000:
        flags.extend(["AI_TIMEOUT", "AI_PARTIAL"])
        return SnapResult(
            title_en="", title_ar="",
            description_en="", description_ar="",
            category_id=CATEGORY_OTHER["id"],
            category_name_en=CATEGORY_OTHER["en"],
            category_name_ar=CATEGORY_OTHER["ar"],
            condition="good",
            clip_confidence=0.0,
            flags=flags,
            partial=True,
        )

    t1 = time.monotonic()
    try:
        clip_result, ocr_result = await asyncio.wait_for(
            asyncio.gather(
                run_clip_classification(images[0]),  # primary image only
                run_ocr_extraction(images),
            ),
            timeout=min(4.0, _remaining_ms() / 1000),
        )
    except asyncio.TimeoutError:
        clip_result = CLIPResult(
            category_id=CATEGORY_OTHER["id"],
            category_name_en=CATEGORY_OTHER["en"],
            category_name_ar=CATEGORY_OTHER["ar"],
            confidence=0.0,
            condition_guess="good",
        )
        ocr_result = OCRResult()
        flags.append("AI_TIMEOUT")

    phase2_ms = (time.monotonic() - t1) * 1000
    _log_phase("clip", phase2_ms, clip_result.confidence > 0, user_id)
    _log_phase("ocr", phase2_ms, ocr_result.brand is not None, user_id)

    # Low confidence → default to "Other"
    if clip_result.confidence < 40:
        _log_phase("low_conf", 0, False, user_id, original_confidence=clip_result.confidence)
        flags.append("AI_LOW_CONF")
        clip_result = CLIPResult(
            category_id=CATEGORY_OTHER["id"],
            category_name_en=CATEGORY_OTHER["en"],
            category_name_ar=CATEGORY_OTHER["ar"],
            confidence=clip_result.confidence,
            condition_guess=clip_result.condition_guess,
            brand_guess=clip_result.brand_guess,
        )

    # ── Phase 3: GPT-4o listing generation ─────────────────────
    if _remaining_ms() < 1000:
        flags.extend(["AI_TIMEOUT", "AI_PARTIAL"])
        result = _assemble_draft(clip_result, ocr_result, None)
        result.flags = flags
        result.partial = True
        return result

    t2 = time.monotonic()
    try:
        gpt_result = await asyncio.wait_for(
            run_gpt_listing(clip_result, ocr_result, images[0]),
            timeout=min(5.0, _remaining_ms() / 1000),
        )
    except asyncio.TimeoutError:
        gpt_result = None
        flags.append("AI_TIMEOUT")

    gpt_ms = (time.monotonic() - t2) * 1000
    _log_phase("gpt_listing", gpt_ms, gpt_result is not None, user_id)

    if gpt_result is None:
        flags.append("AI_PARTIAL")

    # ── Phase 4: Price Oracle (non-blocking, 2 s max) ──────────
    result = _assemble_draft(clip_result, ocr_result, gpt_result)

    if redis is not None:
        price_task = asyncio.create_task(
            _get_price_safe(
                result.category_id,
                result.condition,
                result.brand,
                redis,
            )
        )

        try:
            price = await asyncio.wait_for(price_task, timeout=2.0)
            if price:
                result.price_estimate = PriceEstimateSnap(
                    price_low=price.get("price_low"),
                    price_high=price.get("price_high"),
                    price_mid=price.get("price_mid"),
                    suggested_start=price.get("suggested_start"),
                    confidence=price.get("confidence", "none"),
                )
        except asyncio.TimeoutError:
            _log_phase("price_oracle", 2000, False, user_id)
            # Price oracle timed out — result.price_estimate stays None

    # ── Finalize ───────────────────────────────────────────────
    total_ms = _elapsed_ms()
    _log_phase("total", total_ms, True, user_id)

    if total_ms > PIPELINE_BUDGET_MS:
        if "AI_TIMEOUT" not in flags:
            flags.append("AI_TIMEOUT")
        if "AI_PARTIAL" not in flags:
            flags.append("AI_PARTIAL")

    result.flags = flags
    result.partial = bool(flags)
    return result


async def _get_price_safe(
    category_id: int,
    condition: str,
    brand: str | None,
    redis,
) -> dict | None:
    """Wrapper around price oracle that never raises."""
    try:
        from app.services.ai.price_oracle import get_price_estimate
        return await get_price_estimate(category_id, condition, brand, redis)
    except Exception as exc:
        logger.warning("Price oracle failed in snap pipeline: %s", exc)
        return None
