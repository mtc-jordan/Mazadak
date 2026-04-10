"""
WhatsApp bid bot NLP — Arabic number normalization & regex intent extraction.

Lightweight regex-based approach (no ML models).
Handles Jordanian dialect Arabic numbers and bid/check/help intents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# ── Arabic word-to-number mapping (Jordanian dialect) ────────────

_ARABIC_NUMBERS: dict[str, int] = {
    # Units
    "صفر": 0,
    "واحد": 1, "وحدة": 1,
    "اثنين": 2, "اثنان": 2, "ثنين": 2,
    "ثلاث": 3, "ثلاثة": 3, "تلات": 3,
    "اربع": 4, "أربع": 4, "اربعة": 4, "أربعة": 4,
    "خمس": 5, "خمسة": 5,
    "ست": 6, "ستة": 6,
    "سبع": 7, "سبعة": 7,
    "ثمان": 8, "ثمانية": 8, "تمان": 8,
    "تسع": 9, "تسعة": 9,
    "عشر": 10, "عشرة": 10,
    # Tens
    "عشرين": 20, "عشرون": 20,
    "ثلاثين": 30, "ثلاثون": 30, "تلاتين": 30,
    "اربعين": 40, "أربعين": 40, "اربعون": 40,
    "خمسين": 50, "خمسون": 50,
    "ستين": 60, "ستون": 60,
    "سبعين": 70, "سبعون": 70,
    "ثمانين": 80, "ثمانون": 80, "تمانين": 80,
    "تسعين": 90, "تسعون": 90,
    # Hundreds
    "مية": 100, "مئة": 100, "ميه": 100, "ميّة": 100,
    "ميتين": 200, "مئتين": 200, "مئتان": 200,
    "تلتمية": 300, "ثلاثمية": 300, "ثلاثمئة": 300,
    "اربعمية": 400, "أربعمية": 400, "أربعمئة": 400,
    "خمسمية": 500, "خمسمئة": 500, "خمسميه": 500,
    "ستمية": 600, "ستمئة": 600,
    "سبعمية": 700, "سبعمئة": 700,
    "تمنمية": 800, "ثمانمية": 800, "ثمانمئة": 800,
    "تسعمية": 900, "تسعمئة": 900,
    # Thousands
    "الف": 1000, "ألف": 1000,
    "الفين": 2000, "ألفين": 2000,
    # Common shorthand
    "نص": 0.5,
}

# Eastern Arabic digits → Western
_EASTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_arabic_numbers(text: str) -> str:
    """Replace Arabic number words and Eastern digits with Western numerals.

    Examples:
        "خمسمية" → "500"
        "ألف" → "1000"
        "٥٠٠" → "500"
        "خمسمية وخمسين" → "550"
    """
    # Step 1: Eastern Arabic digits → Western
    text = text.translate(_EASTERN_DIGITS)

    # Step 2: Handle compound expressions like "خمسمية وخمسين" → "550"
    # Sort by length descending so longer matches take priority
    sorted_words = sorted(_ARABIC_NUMBERS.keys(), key=len, reverse=True)

    # Find all Arabic number words in order
    pattern = "|".join(re.escape(w) for w in sorted_words)
    matches = list(re.finditer(pattern, text))

    if not matches:
        return text

    # Group consecutive number words (connected by و or whitespace)
    groups: list[list[re.Match]] = []
    current_group: list[re.Match] = [matches[0]]

    for i in range(1, len(matches)):
        prev_end = current_group[-1].end()
        curr_start = matches[i].start()
        between = text[prev_end:curr_start].strip()

        # Connected if only و or whitespace between them
        if between in ("", "و", "و "):
            current_group.append(matches[i])
        else:
            groups.append(current_group)
            current_group = [matches[i]]

    groups.append(current_group)

    # Replace groups from right to left to preserve indices
    for group in reversed(groups):
        total = sum(_ARABIC_NUMBERS[m.group()] for m in group)
        start = group[0].start()
        end = group[-1].end()
        replacement = str(int(total)) if total == int(total) else str(total)
        text = text[:start] + replacement + text[end:]

    return text


# ── Intent extraction ────────────────────────────────────────────

@dataclass
class BotIntent:
    """Parsed intent from a WhatsApp message."""
    type: str  # "bid" | "check" | "help" | "unknown"
    amount: Optional[int] = None
    auction_ref: Optional[str] = None
    original_text: str = ""


# Bid patterns — spec-aligned regex set
_BID_PATTERNS = [
    # Arabic: زايدوا/زايد على/بـ + amount
    re.compile(r"زايد[وا]?\s+(?:على|ب|بـ)?\s*(\d+(?:\.\d+)?)", re.UNICODE),
    # Arabic: بزيد/ازيد/مزايدة + amount
    re.compile(r"(?:بزيد|ازيد|أزيد|مزايدة|زيد|بدي ازيد|بدي أزيد)\s+(\d+(?:\.\d+)?)", re.UNICODE),
    # Arabic: عطي/أعطي/عطه/ادفع + amount
    re.compile(r"(?:عطي|أعطي|عطه|ادفع)\s+(\d+(?:\.\d+)?)", re.UNICODE),
    # Arabic: amount + دينار/JOD/دنانير
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:دينار|دنانير|JOD|jod)", re.UNICODE),
    # English: bid + amount
    re.compile(r"(?:bid|place bid|my bid)\s+(\d+(?:\.\d+)?)", re.IGNORECASE),
    # Just a number (bare amount — treated as bid if in bid context)
    re.compile(r"^(\d+(?:\.\d+)?)$"),
]

# Check patterns — includes وين/فين from spec
_CHECK_PATTERNS = [
    re.compile(r"(?:كم|شو|ايش|إيش)\s*(?:السعر|سعر|الحالي|صار)", re.UNICODE),
    re.compile(r"(?:وين|فين)\s+", re.UNICODE),
    re.compile(r"(?:check|status|price|current)", re.IGNORECASE),
    re.compile(r"(?:تحقق|استعلام|استفسار)", re.UNICODE),
]

# Help patterns — includes 'how' from spec
_HELP_PATTERNS = [
    re.compile(r"(?:مساعدة|ساعدني|كيف|شلون)", re.UNICODE),
    re.compile(r"(?:help|menu|start|commands|how)", re.IGNORECASE),
]

# Auction reference patterns
_UUID_PARTIAL_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}", re.IGNORECASE)
_HASH_REF_PATTERN = re.compile(r"(?:#|مزاد\s*)([A-Za-z0-9-]+)", re.UNICODE)


def extract_intent(text: str) -> BotIntent:
    """Extract intent, amount, and auction reference from message text.

    Pipeline:
      1. Normalize Arabic numbers to digits
      2. Try bid patterns → extract amount
      3. Try check patterns
      4. Try help patterns
      5. Fallback to unknown
    """
    raw = text.strip()
    normalized = normalize_arabic_numbers(raw)

    # Extract auction reference
    auction_ref = extract_auction_reference(normalized)

    # Try bid patterns
    for pattern in _BID_PATTERNS:
        match = pattern.search(normalized)
        if match:
            try:
                amount = int(float(match.group(1)))
            except (ValueError, IndexError):
                continue
            return BotIntent(
                type="bid",
                amount=amount,
                auction_ref=auction_ref,
                original_text=raw,
            )

    # Try check patterns
    for pattern in _CHECK_PATTERNS:
        if pattern.search(normalized):
            return BotIntent(
                type="check",
                auction_ref=auction_ref,
                original_text=raw,
            )

    # Try help patterns
    for pattern in _HELP_PATTERNS:
        if pattern.search(normalized):
            return BotIntent(
                type="help",
                original_text=raw,
            )

    return BotIntent(type="unknown", original_text=raw)


def extract_auction_reference(text: str) -> Optional[str]:
    """Extract auction ID from text.

    Tries in order:
      1. UUID partial match (8-4 hex format)
      2. #REF or مزاد REF hash/name reference
      3. Keyword fallback — strips numbers/bid words, returns remaining text
    """
    # Try UUID partial match
    uuid_match = _UUID_PARTIAL_PATTERN.search(text)
    if uuid_match:
        return uuid_match.group()

    # Try #REF or مزاد REF
    hash_match = _HASH_REF_PATTERN.search(text)
    if hash_match:
        return hash_match.group(1)

    # Keyword fallback — remove bid/check words and numbers
    keywords = re.sub(
        r"\d+|زايد[وا]?|بزيد|ازيد|أزيد|مزايدة|bid|على|ب|بـ|عطي|أعطي|ادفع|كم|السعر|check|price",
        "", text, flags=re.IGNORECASE | re.UNICODE,
    ).strip()
    return keywords if keywords else None
