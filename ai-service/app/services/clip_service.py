"""CLIP-based image classification service.

Lazy-loads openai/clip-vit-base-patch32, classifies images into MZADAK
categories, and caches results in Redis.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from typing import Any

import numpy as np
import redis.asyncio as redis
import torch
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---- MZADAK category definitions -----------------------------------------

CATEGORIES: list[dict[str, Any]] = [
    {"id": 1, "en": "Electronics", "ar": "إلكترونيات"},
    {"id": 2, "en": "Vehicles", "ar": "مركبات"},
    {"id": 3, "en": "Real Estate", "ar": "عقارات"},
    {"id": 4, "en": "Jewelry & Watches", "ar": "مجوهرات وساعات"},
    {"id": 5, "en": "Fashion", "ar": "أزياء"},
    {"id": 6, "en": "Art & Collectibles", "ar": "فن ومقتنيات"},
    {"id": 7, "en": "Home & Garden", "ar": "منزل وحديقة"},
    {"id": 8, "en": "Sports & Outdoors", "ar": "رياضة ونشاطات خارجية"},
    {"id": 9, "en": "Other", "ar": "أخرى"},
    {"id": 10, "en": "Antiques", "ar": "تحف وآثار"},
    {"id": 11, "en": "Books & Media", "ar": "كتب ووسائط"},
    {"id": 12, "en": "Industrial Equipment", "ar": "معدات صناعية"},
]

CATEGORY_LABELS = [c["en"] for c in CATEGORIES]

CONDITION_LABELS = ["brand new", "like new", "very good", "good", "acceptable"]
CONDITION_MAP = {
    "brand new": "brand_new",
    "like new": "like_new",
    "very good": "very_good",
    "good": "good",
    "acceptable": "acceptable",
}

# ---- Singleton model holder -----------------------------------------------

_clip_model = None
_clip_processor = None
_text_features: torch.Tensor | None = None
_condition_features: torch.Tensor | None = None
_device: str = "cpu"
_redis_pool: redis.Redis | None = None


async def _get_redis() -> redis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_pool


def _get_device() -> str:
    if settings.GPU_ENABLED and torch.cuda.is_available():
        return "cuda"
    return "cpu"


async def warm_model() -> None:
    """Pre-load CLIP model and compute category text embeddings."""
    global _clip_model, _clip_processor, _text_features, _condition_features, _device

    if _clip_model is not None:
        return

    try:
        from transformers import CLIPModel, CLIPProcessor

        _device = _get_device()
        logger.info("Loading CLIP model on %s …", _device)

        _clip_processor = CLIPProcessor.from_pretrained(
            "openai/clip-vit-base-patch32",
            cache_dir=settings.MODEL_CACHE_DIR,
        )
        _clip_model = CLIPModel.from_pretrained(
            "openai/clip-vit-base-patch32",
            cache_dir=settings.MODEL_CACHE_DIR,
        ).to(_device)
        _clip_model.eval()

        # Pre-compute category text embeddings
        cat_prompts = [f"a photo of {label}" for label in CATEGORY_LABELS]
        cat_inputs = _clip_processor(text=cat_prompts, return_tensors="pt", padding=True).to(_device)
        with torch.no_grad():
            _text_features = _clip_model.get_text_features(**cat_inputs)
            _text_features = _text_features / _text_features.norm(dim=-1, keepdim=True)

        # Pre-compute condition text embeddings
        cond_prompts = [f"a {c} item" for c in CONDITION_LABELS]
        cond_inputs = _clip_processor(text=cond_prompts, return_tensors="pt", padding=True).to(_device)
        with torch.no_grad():
            _condition_features = _clip_model.get_text_features(**cond_inputs)
            _condition_features = _condition_features / _condition_features.norm(dim=-1, keepdim=True)

        logger.info("CLIP model warmed successfully on %s", _device)
    except Exception:
        logger.exception("Failed to load CLIP model — classify_image will use fallback")


def _image_hash(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


async def classify_image(image_bytes: bytes) -> dict[str, Any]:
    """Classify a single image and return structured result.

    Returns dict with keys: category_id, category_name_en, category_name_ar,
    condition, brand, confidence.
    """
    img_hash = _image_hash(image_bytes)

    # Check Redis cache
    try:
        r = await _get_redis()
        cached = await r.get(f"clip:{img_hash}")
        if cached:
            return json.loads(cached)
    except Exception:
        logger.debug("Redis cache miss or unavailable for clip:%s", img_hash[:12])

    result = await _classify_image_impl(image_bytes)

    # Cache result
    try:
        r = await _get_redis()
        await r.set(f"clip:{img_hash}", json.dumps(result), ex=3600)
    except Exception:
        logger.debug("Failed to cache CLIP result")

    return result


async def _classify_image_impl(image_bytes: bytes) -> dict[str, Any]:
    """Run CLIP inference or return fallback."""
    if _clip_model is None or _clip_processor is None or _text_features is None:
        logger.warning("CLIP model not loaded — returning fallback classification")
        return _fallback_result()

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inputs = _clip_processor(images=image, return_tensors="pt").to(_device)

        with torch.no_grad():
            image_features = _clip_model.get_image_features(**inputs)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)

            # Category classification
            cat_sims = (image_features @ _text_features.T).squeeze(0)
            cat_probs = cat_sims.softmax(dim=-1).cpu().numpy()
            cat_idx = int(np.argmax(cat_probs))
            cat = CATEGORIES[cat_idx]

            # Condition classification
            cond_sims = (image_features @ _condition_features.T).squeeze(0)
            cond_probs = cond_sims.softmax(dim=-1).cpu().numpy()
            cond_idx = int(np.argmax(cond_probs))

        return {
            "category_id": cat["id"],
            "category_name_en": cat["en"],
            "category_name_ar": cat["ar"],
            "condition": CONDITION_MAP[CONDITION_LABELS[cond_idx]],
            "brand": None,  # Brand detection requires fine-tuning — MVP returns None
            "confidence": round(float(cat_probs[cat_idx]), 4),
        }
    except Exception:
        logger.exception("CLIP inference failed")
        return _fallback_result()


def _fallback_result() -> dict[str, Any]:
    return {
        "category_id": 9,
        "category_name_en": "Other",
        "category_name_ar": "أخرى",
        "condition": "good",
        "brand": None,
        "confidence": 0.0,
    }
