"""
NLP intent extraction — FR-BOT-004.

Uses AraBERT-based zero-shot classification to detect user intent
from Arabic text.  Falls back to keyword matching when the model
is unavailable or confidence is below threshold.

Intents:
  bid   — user wants to place / raise a bid
  check — user wants auction status or current price
  help  — user needs assistance or instructions
  link  — user wants to link their WhatsApp to MZADAK account
"""

from __future__ import annotations

import logging
import re

from app.services.whatsapp_bot.arabic_numbers import extract_amount
from app.services.whatsapp_bot.schemas import ParsedIntent

logger = logging.getLogger(__name__)

# ── Lazy-loaded model singleton ──────────────────────────────────
_classifier = None
_MODEL_NAME = "aubmindlab/bert-base-arabertv02"

# Intent labels for zero-shot classification
_CANDIDATE_LABELS = [
    "مزايدة",   # bid
    "استفسار",   # check / status query
    "مساعدة",   # help
    "ربط حساب",  # link account
]

_LABEL_TO_INTENT = {
    "مزايدة": "bid",
    "استفسار": "check",
    "مساعدة": "help",
    "ربط حساب": "link",
}

# ── Keyword fallback patterns ────────────────────────────────────
_BID_PATTERNS = re.compile(
    r"(بزيد|ازيد|ابزيد|بدي ازيد|مزايد|ارفع|بدي ارفع|bid|مزايدة|أزيد)",
    re.IGNORECASE,
)
_CHECK_PATTERNS = re.compile(
    r"(كم وصل|شو السعر|سعر|وين وصل|حالة|status|price|check|وصلت كم|اخر سعر|آخر)",
    re.IGNORECASE,
)
_HELP_PATTERNS = re.compile(
    r"(مساعدة|شلون|كيف|help|ساعدني|وش اسوي|شو اعمل|إرشاد)",
    re.IGNORECASE,
)
_LINK_PATTERNS = re.compile(
    r"(ربط|اربط|حسابي|link|تسجيل|register)",
    re.IGNORECASE,
)


def _get_classifier():
    """Lazy-load the zero-shot classifier (heavy — first call only)."""
    global _classifier
    if _classifier is not None:
        return _classifier

    try:
        from transformers import pipeline
        _classifier = pipeline(
            "zero-shot-classification",
            model=_MODEL_NAME,
            device=-1,  # CPU — GPU not needed for single-sentence inference
        )
        logger.info("AraBERT zero-shot classifier loaded")
    except Exception as exc:
        logger.warning("Failed to load AraBERT classifier: %s — using keyword fallback", exc)
        _classifier = None
    return _classifier


def _keyword_fallback(text: str) -> tuple[str, float]:
    """Simple regex-based intent detection."""
    if _BID_PATTERNS.search(text):
        return "bid", 0.85
    if _CHECK_PATTERNS.search(text):
        return "check", 0.80
    if _LINK_PATTERNS.search(text):
        return "link", 0.80
    if _HELP_PATTERNS.search(text):
        return "help", 0.75
    return "unknown", 0.0


def _extract_keyword(text: str) -> str | None:
    """Extract auction keyword / product name from text.

    Strips known intent verbs and amounts, leaving the product reference.
    E.g. "بدي ازيد على الايفون 500" → "الايفون"
    """
    # Remove intent verbs
    cleaned = _BID_PATTERNS.sub("", text)
    cleaned = _CHECK_PATTERNS.sub("", cleaned)
    # Remove numbers (Arabic and Western)
    cleaned = re.sub(r"[\d٠-٩]+", "", cleaned)
    # Remove currency words
    cleaned = re.sub(r"(دينار|دنانير|JOD|jod)", "", cleaned)
    # Remove prepositions and conjunctions
    cleaned = re.sub(r"\b(على|عال|في|من|و|بـ|لل|ال)\b", "", cleaned)
    cleaned = cleaned.strip()

    # Return the remaining text if meaningful
    if len(cleaned) >= 2:
        return cleaned
    return None


async def extract_intent(text: str) -> ParsedIntent:
    """Extract user intent, keyword, and amount from Arabic text.

    Pipeline:
      1. Try AraBERT zero-shot classification
      2. Fall back to keyword regex if model unavailable or low confidence
      3. Extract auction keyword and bid amount from text
    """
    classifier = _get_classifier()
    intent = "unknown"
    confidence = 0.0

    if classifier is not None:
        try:
            result = classifier(text, _CANDIDATE_LABELS)
            top_label = result["labels"][0]
            top_score = result["scores"][0]

            if top_score >= 0.45:
                intent = _LABEL_TO_INTENT.get(top_label, "unknown")
                confidence = top_score
            else:
                # Low confidence — fall back to keywords
                intent, confidence = _keyword_fallback(text)
        except Exception as exc:
            logger.warning("AraBERT inference failed: %s", exc)
            intent, confidence = _keyword_fallback(text)
    else:
        intent, confidence = _keyword_fallback(text)

    keyword = _extract_keyword(text)
    amount = extract_amount(text)

    return ParsedIntent(
        intent=intent,
        keyword=keyword,
        amount=amount,
        confidence=confidence,
    )
