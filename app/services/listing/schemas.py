"""Listing request/response schemas — SDD §5.3, FR-LIST-001 → FR-LIST-013."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


# ── Create / Update ────────────────────────────────────────────

class ListingCreateRequest(BaseModel):
    title_ar: str = Field(..., min_length=1, max_length=80)
    title_en: str | None = Field(default=None, max_length=80)
    description_ar: str = Field(..., min_length=50, max_length=2000)
    description_en: str | None = Field(default=None, max_length=2000)
    category_id: int
    condition: str = Field(..., pattern=r"^(new|like_new|good|fair|for_parts)$")
    starting_price: float = Field(..., gt=0)
    reserve_price: float | None = Field(default=None, gt=0)
    buy_it_now_price: float | None = Field(default=None, gt=0)
    listing_currency: str = Field(default="JOD", pattern=r"^(JOD|SAR|AED)$")
    duration_hours: int = Field(default=24, ge=1, le=168)  # 1h – 7d (168h)
    image_urls: list[str] = Field(..., min_length=1, max_length=10)
    is_charity: bool = False
    ngo_id: str | None = None

    @model_validator(mode="after")
    def validate_prices(self):
        if self.reserve_price is not None and self.reserve_price < self.starting_price:
            raise ValueError("reserve_price must be >= starting_price")
        if self.buy_it_now_price is not None and self.buy_it_now_price <= self.starting_price:
            raise ValueError("buy_it_now_price must be > starting_price")
        return self


class ListingUpdateRequest(BaseModel):
    title_ar: str | None = Field(default=None, min_length=1, max_length=80)
    title_en: str | None = Field(default=None, max_length=80)
    description_ar: str | None = Field(default=None, min_length=50, max_length=2000)
    description_en: str | None = Field(default=None, max_length=2000)
    category_id: int | None = None
    condition: str | None = Field(default=None, pattern=r"^(new|like_new|good|fair|for_parts)$")
    starting_price: float | None = Field(default=None, gt=0)
    reserve_price: float | None = Field(default=None, gt=0)
    buy_it_now_price: float | None = Field(default=None, gt=0)
    duration_hours: int | None = Field(default=None, ge=1, le=168)
    image_urls: list[str] | None = Field(default=None, min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_prices(self):
        if (
            self.reserve_price is not None
            and self.starting_price is not None
            and self.reserve_price < self.starting_price
        ):
            raise ValueError("reserve_price must be >= starting_price")
        return self


# ── Image upload ───────────────────────────────────────────────

class ImageUploadRequest(BaseModel):
    count: int = Field(..., ge=1, le=10)


class ImageUploadURL(BaseModel):
    upload_url: str
    s3_key: str


class ImageUploadResponse(BaseModel):
    upload_urls: list[ImageUploadURL]
    expires_in: int = 300


# ── Response models ────────────────────────────────────────────

class ListingOut(BaseModel):
    id: str
    seller_id: str
    title_ar: str
    title_en: str | None = None
    description_ar: str
    description_en: str | None = None
    category_id: int
    condition: str
    starting_price: float
    reserve_price: float | None = None
    buy_it_now_price: float | None = None
    listing_currency: str
    duration_hours: int = 24
    status: str
    ai_generated: bool = False
    ai_price_low: float | None = None
    ai_price_high: float | None = None
    phash: str | None = None
    moderation_score: float | None = None
    is_charity: bool = False
    image_urls: list[str] = []
    bid_count: int = 0
    published_at: str | None = None

    model_config = {"from_attributes": True}


class ListingListResponse(BaseModel):
    data: list[ListingOut]
    next_cursor: str | None = None
    total_count: int
