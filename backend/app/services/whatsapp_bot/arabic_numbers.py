"""
Arabic word-to-number conversion — FR-BOT-005.

Handles Jordanian dialect numerals, e.g.:
  خمسمية → 500,  ميتين → 200,  ألف → 1000,  خمسة وعشرين → 25

Also normalises Eastern Arabic digits (٠-٩) to Western (0-9).
"""

from __future__ import annotations

import re

# ── Eastern Arabic digit mapping ─────────────────────────────────
_EASTERN = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# ── Cardinal words (Jordanian / Modern Standard) ─────────────────
_UNITS: dict[str, int] = {
    "صفر": 0,
    "واحد": 1, "وحدة": 1,
    "اثنين": 2, "اثنتين": 2, "ثنتين": 2,
    "ثلاث": 3, "ثلاثة": 3, "تلات": 3, "تلاتة": 3,
    "اربع": 4, "اربعة": 4, "أربع": 4, "أربعة": 4,
    "خمس": 5, "خمسة": 5,
    "ست": 6, "ستة": 6,
    "سبع": 7, "سبعة": 7,
    "ثمان": 8, "ثمانية": 8, "تمان": 8, "تمانية": 8,
    "تسع": 9, "تسعة": 9,
    "عشر": 10, "عشرة": 10,
    "احدعش": 11, "احدعشر": 11,
    "اثنعش": 12, "اثنعشر": 12, "اطنعش": 12,
    "ثلطعش": 13, "ثلاثطعش": 13, "تلتطعش": 13,
    "اربعطعش": 14, "أربعطعش": 14,
    "خمسطعش": 15,
    "ستطعش": 16,
    "سبعطعش": 17,
    "ثمنطعش": 18, "تمنطعش": 18,
    "تسعطعش": 19,
}

_TENS: dict[str, int] = {
    "عشرين": 20, "عشرون": 20,
    "ثلاثين": 30, "ثلاثون": 30, "تلاتين": 30,
    "اربعين": 40, "اربعون": 40, "أربعين": 40,
    "خمسين": 50, "خمسون": 50,
    "ستين": 60, "ستون": 60,
    "سبعين": 70, "سبعون": 70,
    "ثمانين": 80, "ثمانون": 80, "تمانين": 80,
    "تسعين": 90, "تسعون": 90,
}

_HUNDREDS: dict[str, int] = {
    "مية": 100, "ميه": 100, "مئة": 100, "مائة": 100,
    "ميتين": 200, "مئتين": 200, "مئتان": 200,
    "تلتمية": 300, "ثلاثمية": 300, "ثلاثمئة": 300, "ثلثمية": 300,
    "اربعمية": 400, "أربعمية": 400, "اربعمئة": 400,
    "خمسمية": 500, "خمسمئة": 500,
    "ستمية": 600, "ستمئة": 600,
    "سبعمية": 700, "سبعمئة": 700,
    "ثمنمية": 800, "تمنمية": 800, "ثمانمئة": 800,
    "تسعمية": 900, "تسعمئة": 900,
}

_MULTIPLIERS: dict[str, int] = {
    "الف": 1_000, "ألف": 1_000, "آلاف": 1_000, "الاف": 1_000,
    "مليون": 1_000_000,
}


def _normalize(text: str) -> str:
    """Remove diacritics and normalise common chars."""
    # Strip tashkeel
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    # Normalise alef variants
    text = re.sub(r"[إأآا]", "ا", text)
    return text.strip()


def arabic_words_to_number(text: str) -> float | None:
    """Parse an Arabic numeric expression into a float.

    Returns None if no number could be extracted.

    Examples:
        "خمسمية" → 500.0
        "ألف و ميتين و خمسة وعشرين" → 1225.0
        "500" → 500.0
        "٥٠٠" → 500.0
        "خمسة دنانير ونص" → 5.5
    """
    text = _normalize(text)

    # 1) Try direct numeric (Western or Eastern Arabic digits)
    western = text.translate(_EASTERN)
    m = re.search(r"(\d+(?:\.\d+)?)", western)
    if m:
        return float(m.group(1))

    # 2) Token-based word parsing
    # Split on "و" (and) and whitespace
    tokens = re.split(r"\s+|(?<=\S)و(?=\S)", text)
    tokens = [t.strip() for t in tokens if t.strip() and t.strip() != "و"]

    if not tokens:
        return None

    total = 0.0
    current = 0.0
    found_any = False

    for token in tokens:
        if token in _UNITS:
            current += _UNITS[token]
            found_any = True
        elif token in _TENS:
            current += _TENS[token]
            found_any = True
        elif token in _HUNDREDS:
            current += _HUNDREDS[token]
            found_any = True
        elif token in _MULTIPLIERS:
            mult = _MULTIPLIERS[token]
            if current == 0:
                current = 1
            total += current * mult
            current = 0
            found_any = True
        elif token in ("نص", "نصف"):
            current += 0.5
            found_any = True
        elif token in ("ربع",):
            current += 0.25
            found_any = True

    total += current

    return total if found_any else None


def extract_amount(text: str) -> float | None:
    """Try to find a monetary amount in Arabic text.

    Looks for patterns like:
      "ابزيد 500", "بدي ازيد خمسمية", "1250 دينار"
    """
    text = _normalize(text)

    # Try numeric first (most common)
    western = text.translate(_EASTERN)
    m = re.search(r"(\d+(?:\.\d+)?)", western)
    if m:
        return float(m.group(1))

    # Try word-based
    return arabic_words_to_number(text)
