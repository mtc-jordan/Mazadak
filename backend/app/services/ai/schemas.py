"""AI service schemas — SDD §3.4."""

from pydantic import BaseModel, Field


# ── Snap-to-List (FR-LIST-002, PM-04) ──────────────────────────

class SnapToListRequest(BaseModel):
    image_s3_keys: list[str] = Field(..., min_length=3, max_length=20)


class CLIPResult(BaseModel):
    category_id: int
    category_name_en: str
    category_name_ar: str
    confidence: float = Field(..., ge=0, le=100)
    condition_guess: str | None = None
    brand_guess: str | None = None


class OCRResult(BaseModel):
    brand: str | None = None
    model: str | None = None
    storage: str | None = None
    color: str | None = None


class PriceEstimateSnap(BaseModel):
    """Price oracle subset embedded in snap result."""
    price_low: int | None = None
    price_high: int | None = None
    price_mid: int | None = None
    suggested_start: int | None = None
    confidence: str = "none"


class CategoryCandidate(BaseModel):
    name: str
    category_id: int
    confidence: float = Field(0.0, ge=0, le=100)


class SnapResult(BaseModel):
    title_en: str
    title_ar: str
    description_en: str
    description_ar: str
    category_id: int
    category_name_en: str
    category_name_ar: str
    condition: str
    brand: str | None = None
    model: str | None = None
    clip_confidence: float = Field(0.0, ge=0, le=100)
    price_estimate: PriceEstimateSnap | None = None
    flags: list[str] = []
    partial: bool = False


class SnapToListResponse(BaseModel):
    """Full snap-to-list pipeline response (snap_to_list.py)."""
    title_ar: str
    title_en: str
    description_ar: str
    description_en: str
    category: str
    category_id: int
    category_candidates: list[CategoryCandidate] = []
    condition: str
    brand: str | None = None
    price_low: float | None = None
    price_high: float | None = None
    suggested_start: float | None = None
    confidence: float = Field(0.0, ge=0, le=100)
    partial: bool = False
    warnings: list[str] = []


# ── Price Oracle (FR-AI-001) ────────────────────────────────────

class PriceOracleRequest(BaseModel):
    category_id: int
    condition: str = Field(
        ...,
        pattern=r"^(brand_new|like_new|very_good|good|acceptable)$",
    )
    brand: str | None = None


class PriceOracleResponse(BaseModel):
    """All prices in integer cents (1 JOD = 1000 fils)."""
    price_low: int | None = None
    price_high: int | None = None
    price_mid: int | None = None
    suggested_start: int | None = None
    confidence: str = Field(..., pattern=r"^(high|medium|low|none)$")
    comparable_count: int
    date_range_days: int | None = None


# ── Content moderation ──────────────────────────────────────────

class ModerationRequest(BaseModel):
    listing_id: str
    title_ar: str
    description_ar: str
    image_urls: list[str]


class ModerationResponse(BaseModel):
    score: float = Field(..., ge=0, le=100)
    flags: list[str]  # e.g. ["prohibited_item", "misleading_description"]
    auto_approve: bool  # True if score < 30


# ── Fraud scoring ───────────────────────────────────────────────

class FraudScoreRequest(BaseModel):
    user_id: str
    auction_id: str
    bid_amount: float


class FraudScoreResponse(BaseModel):
    score: float = Field(..., ge=0, le=100)
    risk_factors: list[str]


# ── Transcription (WhatsApp voice) ──────────────────────────────

class TranscribeRequest(BaseModel):
    audio_s3_key: str
    language: str = "ar"


class TranscribeResponse(BaseModel):
    text: str
    language: str
    confidence: float


# ── Intent extraction (WhatsApp bot) ────────────────────────────

class IntentRequest(BaseModel):
    text: str
    user_id: str


class IntentResponse(BaseModel):
    intent: str  # bid | search | status | help | unknown
    entities: dict  # extracted values: amount, item, auction_id, etc.
    confidence: float
