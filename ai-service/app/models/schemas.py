"""Pydantic request/response models for the AI service API.

All prices are integer cents (100 = 1 JOD).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Snap-to-List
# ---------------------------------------------------------------------------

class SnapToListRequest(BaseModel):
    image_s3_keys: list[str] = Field(..., min_length=3, max_length=20)


class PriceEstimateSnap(BaseModel):
    price_low: int
    price_high: int
    price_mid: int
    suggested_start: int | None = None
    confidence: str  # "high" | "medium" | "low"


class SnapResult(BaseModel):
    title_ar: str
    title_en: str
    description_ar: str
    description_en: str
    category_id: int
    category_name_en: str
    category_name_ar: str
    condition: str
    brand: str | None = None
    model: str | None = None
    clip_confidence: float
    price_estimate: PriceEstimateSnap | None = None
    flags: list[str] = Field(default_factory=list)
    partial: bool = False


# ---------------------------------------------------------------------------
# Moderation
# ---------------------------------------------------------------------------

class ModerationRequest(BaseModel):
    listing_id: str
    title_ar: str
    description_ar: str
    image_urls: list[str] = Field(default_factory=list)


class ModerationResponse(BaseModel):
    score: float
    flags: list[str] = Field(default_factory=list)
    auto_approve: bool


# ---------------------------------------------------------------------------
# Price Oracle
# ---------------------------------------------------------------------------

class PriceOracleRequest(BaseModel):
    category_id: int
    condition: str
    brand: str | None = None


class PriceOracleResponse(BaseModel):
    price_low: int
    price_high: int
    price_mid: int
    suggested_start: int | None = None
    confidence: str
    comparable_count: int
    date_range_days: int | None = None


# ---------------------------------------------------------------------------
# Fraud Score
# ---------------------------------------------------------------------------

class FraudScoreRequest(BaseModel):
    user_id: str
    auction_id: str
    bid_amount: int


class FraudScoreResponse(BaseModel):
    score: float
    risk_factors: list[str] = Field(default_factory=list)
