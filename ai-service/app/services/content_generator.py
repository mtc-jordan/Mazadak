"""Listing content generation using OpenAI GPT-4o.

Generates bilingual (Arabic/English) auction listing titles and descriptions
from CLIP classification results.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert Arabic auction listing copywriter for MZADAK, a premium \
auction marketplace in Jordan. Given a classified item, generate compelling \
bilingual listing content.

Rules:
- Arabic text must be natural, fluent Modern Standard Arabic suitable for \
  Jordanian/GCC audiences
- English text should be concise and professional
- Titles: max 80 characters, highlight key features
- Descriptions: 2-3 sentences, mention condition, appeal to bidders
- Return ONLY valid JSON, no markdown fences

Output JSON schema:
{
  "title_ar": "string",
  "title_en": "string",
  "description_ar": "string",
  "description_en": "string"
}
"""


async def generate_listing_content(
    clip_result: dict[str, Any],
    image_count: int,
) -> dict[str, str]:
    """Generate bilingual listing content from CLIP classification.

    Returns dict with title_ar, title_en, description_ar, description_en.
    Falls back to template-based content if OpenAI is unavailable.
    """
    if not settings.OPENAI_API_KEY:
        logger.info("No OpenAI API key configured — using template fallback")
        return _template_fallback(clip_result, image_count)

    try:
        return await _call_openai(clip_result, image_count)
    except Exception:
        logger.exception("OpenAI content generation failed — using fallback")
        return _template_fallback(clip_result, image_count)


async def _call_openai(
    clip_result: dict[str, Any],
    image_count: int,
) -> dict[str, str]:
    """Call OpenAI GPT-4o to generate listing content."""
    import openai

    client = openai.AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=15.0,
    )

    user_msg = (
        f"Category: {clip_result['category_name_en']} ({clip_result['category_name_ar']})\n"
        f"Condition: {clip_result['condition']}\n"
        f"Brand: {clip_result.get('brand') or 'Unknown'}\n"
        f"Number of photos: {image_count}\n"
        f"Confidence: {clip_result['confidence']}"
    )

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.7,
        max_tokens=500,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)

    return {
        "title_ar": data.get("title_ar", ""),
        "title_en": data.get("title_en", ""),
        "description_ar": data.get("description_ar", ""),
        "description_en": data.get("description_en", ""),
    }


def _template_fallback(
    clip_result: dict[str, Any],
    image_count: int,
) -> dict[str, str]:
    """Generate simple template-based content when OpenAI is unavailable."""
    cat_en = clip_result.get("category_name_en", "Item")
    cat_ar = clip_result.get("category_name_ar", "منتج")
    condition = clip_result.get("condition", "good")
    brand = clip_result.get("brand")

    condition_ar_map = {
        "brand_new": "جديد",
        "like_new": "شبه جديد",
        "very_good": "جيد جداً",
        "good": "جيد",
        "acceptable": "مقبول",
    }
    cond_ar = condition_ar_map.get(condition, "جيد")
    cond_en = condition.replace("_", " ").title()

    brand_part_en = f" {brand}" if brand else ""
    brand_part_ar = f" {brand}" if brand else ""

    title_en = f"{cond_en}{brand_part_en} {cat_en} for Auction"
    title_ar = f"{cat_ar}{brand_part_ar} بحالة {cond_ar} للمزاد"

    desc_en = (
        f"{cond_en}{brand_part_en} {cat_en.lower()} available for auction. "
        f"Includes {image_count} photos. Don't miss this opportunity!"
    )
    desc_ar = (
        f"{cat_ar}{brand_part_ar} بحالة {cond_ar} متاح للمزاد. "
        f"يتضمن {image_count} صور. لا تفوت الفرصة!"
    )

    return {
        "title_ar": title_ar,
        "title_en": title_en,
        "description_ar": desc_ar,
        "description_en": desc_en,
    }
