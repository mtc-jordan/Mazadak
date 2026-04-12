"""Content moderation service.

Arabic keyword blocklist + pattern matching for prohibited content.
Returns a score 0-100 where lower is safer.
Flag descriptions are bilingual (Arabic and English).
"""

from __future__ import annotations

import logging
import re

from app.models.schemas import ModerationResponse

logger = logging.getLogger(__name__)

# ---- Blocklists ----------------------------------------------------------

# Weapons-related terms
WEAPONS_AR = [
    "سلاح", "مسدس", "بندقية", "رصاص", "ذخيرة", "قنبلة", "متفجرات",
    "سكين حربي", "خنجر", "كاتم صوت",
]

# Drugs-related terms
DRUGS_AR = [
    "مخدرات", "حشيش", "كوكايين", "هيروين", "أفيون", "ترامادول",
    "كبتاغون", "ماريجوانا", "حبوب مخدرة",
]

# Counterfeit / fraud terms
COUNTERFEIT_AR = [
    "تقليد", "مقلد", "مزيف", "مزور", "نسخة طبق الأصل", "ريبليكا",
    "درجة أولى", "كوبي", "هاي كوبي",
]

# Prohibited items
PROHIBITED_AR = [
    "عاج", "جلد نمر", "حيوانات مهددة", "أعضاء بشرية",
]

# Contact info patterns (users trying to bypass platform)
PHONE_PATTERN = re.compile(r"(?:07[789]\d{7}|\+9627[789]\d{7}|\d{10,})")
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
SOCIAL_PATTERNS = re.compile(
    r"(?:واتس|واتساب|whatsapp|تلغرام|telegram|انستا|instagram|فيس|facebook|سناب|snapchat)",
    re.IGNORECASE,
)

# Score weights
WEIGHT_WEAPONS = 40
WEIGHT_DRUGS = 50
WEIGHT_COUNTERFEIT = 25
WEIGHT_PROHIBITED = 35
WEIGHT_CONTACT = 15
WEIGHT_SOCIAL = 10

# Bilingual flag descriptions
FLAG_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "weapons": {
        "en": "Weapons or weapon-related items are prohibited",
        "ar": "الأسلحة أو المواد المتعلقة بالأسلحة محظورة",
    },
    "drugs": {
        "en": "Drugs or controlled substances are prohibited",
        "ar": "المخدرات أو المواد الخاضعة للرقابة محظورة",
    },
    "counterfeit": {
        "en": "Counterfeit or replica items are not allowed",
        "ar": "المنتجات المقلدة أو المزيفة غير مسموح بها",
    },
    "prohibited": {
        "en": "This item falls under prohibited goods",
        "ar": "هذا المنتج يندرج ضمن السلع المحظورة",
    },
    "phone_number": {
        "en": "Sharing contact phone numbers is not allowed",
        "ar": "مشاركة أرقام الهاتف غير مسموح بها",
    },
    "email": {
        "en": "Sharing email addresses is not allowed",
        "ar": "مشاركة عناوين البريد الإلكتروني غير مسموح بها",
    },
    "social_media": {
        "en": "Sharing social media accounts is not allowed",
        "ar": "مشاركة حسابات التواصل الاجتماعي غير مسموح بها",
    },
}


def _bilingual_flag(category: str, keyword: str | None = None) -> str:
    """Build a bilingual flag string like 'weapons_keyword:سلاح | Weapons ... | الأسلحة ...'"""
    desc = FLAG_DESCRIPTIONS.get(category, {"en": category, "ar": category})
    prefix = f"{category}_keyword:{keyword}" if keyword else f"contact_info:{category}"
    return f"{prefix} | {desc['en']} | {desc['ar']}"


async def moderate_content(
    listing_id: str,
    title_ar: str,
    description_ar: str,
    image_urls: list[str],
) -> ModerationResponse:
    """Moderate listing text content and return a risk score.

    Score 0-100: lower is safer. Auto-approve if score < 30.
    """
    text = f"{title_ar} {description_ar}".lower()
    flags: list[str] = []
    score = 0.0

    # Check weapons
    for term in WEAPONS_AR:
        if term in text:
            flags.append(_bilingual_flag("weapons", term))
            score += WEIGHT_WEAPONS
            break  # One hit per category is enough

    # Check drugs
    for term in DRUGS_AR:
        if term in text:
            flags.append(_bilingual_flag("drugs", term))
            score += WEIGHT_DRUGS
            break

    # Check counterfeit
    for term in COUNTERFEIT_AR:
        if term in text:
            flags.append(_bilingual_flag("counterfeit", term))
            score += WEIGHT_COUNTERFEIT
            break

    # Check prohibited
    for term in PROHIBITED_AR:
        if term in text:
            flags.append(_bilingual_flag("prohibited", term))
            score += WEIGHT_PROHIBITED
            break

    # Check contact info
    if PHONE_PATTERN.search(text):
        flags.append(_bilingual_flag("phone_number"))
        score += WEIGHT_CONTACT

    if EMAIL_PATTERN.search(text):
        flags.append(_bilingual_flag("email"))
        score += WEIGHT_CONTACT

    if SOCIAL_PATTERNS.search(text):
        flags.append(_bilingual_flag("social_media"))
        score += WEIGHT_SOCIAL

    # Clamp to 0-100
    score = min(100.0, max(0.0, score))

    logger.info(
        "Moderation for listing %s: score=%.1f flags=%s",
        listing_id,
        score,
        flags,
    )

    return ModerationResponse(
        score=score,
        flags=flags,
        auto_approve=score < 30,
    )
