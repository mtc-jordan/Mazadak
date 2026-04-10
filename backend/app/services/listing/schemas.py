"""Listing request/response schemas — SDD §5.3, FR-LIST-001 -> FR-LIST-013.

All prices are INTEGER cents (1 JOD = 1000 fils, min 100 cents = 1 JOD).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

import re

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Enums ─────────────────────────────────────────────────────

class ListingCondition(str, Enum):
    brand_new = "brand_new"
    like_new = "like_new"
    very_good = "very_good"
    good = "good"
    acceptable = "acceptable"


# Arabic Unicode range check
_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


# ── Create / Update ──────────────────────────────────────────

class CreateListingRequest(BaseModel):
    title_ar: str = Field(..., min_length=3, max_length=200)
    title_en: str = Field(..., min_length=3, max_length=200)
    description_ar: str | None = Field(default=None, max_length=5000)
    description_en: str | None = Field(default=None, min_length=10, max_length=5000)

    @field_validator("title_ar")
    @classmethod
    def title_ar_must_contain_arabic(cls, v: str) -> str:
        if not _ARABIC_RE.search(v):
            raise ValueError("title_ar must contain at least one Arabic character")
        return v
    category_id: int
    condition: ListingCondition
    starting_price: int = Field(..., ge=100, description="Price in cents, min 100 (1 JOD)")
    reserve_price: int | None = Field(default=None, ge=100)
    buy_it_now_price: int | None = Field(default=None, ge=100)
    min_increment: int = Field(default=2500, ge=100, description="Min bid increment in cents")
    starts_at: datetime
    ends_at: datetime
    location_city: str | None = Field(default=None, max_length=100)
    location_country: str = Field(default="JO", max_length=5)
    is_charity: bool = False
    ngo_id: int | None = None
    is_certified: bool = False

    @model_validator(mode="after")
    def validate_listing(self):
        # Price constraints
        if self.reserve_price is not None and self.reserve_price < self.starting_price:
            raise ValueError("reserve_price must be >= starting_price")
        if self.buy_it_now_price is not None and self.buy_it_now_price <= self.starting_price:
            raise ValueError("buy_it_now_price must be > starting_price")

        # Schedule constraints
        now = datetime.now(timezone.utc)
        if self.starts_at.tzinfo is None:
            self.starts_at = self.starts_at.replace(tzinfo=timezone.utc)
        if self.ends_at.tzinfo is None:
            self.ends_at = self.ends_at.replace(tzinfo=timezone.utc)

        if self.starts_at < now + timedelta(minutes=5):
            raise ValueError("starts_at must be at least 5 minutes in the future")
        duration = self.ends_at - self.starts_at
        if duration < timedelta(hours=1):
            raise ValueError("Auction duration must be at least 1 hour")
        if duration > timedelta(days=7):
            raise ValueError("Auction duration must not exceed 7 days")

        # Charity requires ngo_id
        if self.is_charity and not self.ngo_id:
            raise ValueError("ngo_id is required for charity listings")

        return self


class UpdateListingRequest(BaseModel):
    title_ar: str | None = Field(default=None, min_length=1, max_length=200)
    title_en: str | None = Field(default=None, min_length=1, max_length=200)
    description_ar: str | None = Field(default=None, max_length=5000)
    description_en: str | None = Field(default=None, max_length=5000)
    category_id: int | None = None
    condition: ListingCondition | None = None
    starting_price: int | None = Field(default=None, ge=100)
    reserve_price: int | None = Field(default=None, ge=100)
    buy_it_now_price: int | None = Field(default=None, ge=100)
    min_increment: int | None = Field(default=None, ge=100)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    location_city: str | None = Field(default=None, max_length=100)
    location_country: str | None = Field(default=None, max_length=5)
    is_charity: bool | None = None
    ngo_id: int | None = None
    is_certified: bool | None = None

    @model_validator(mode="after")
    def validate_prices(self):
        if (
            self.reserve_price is not None
            and self.starting_price is not None
            and self.reserve_price < self.starting_price
        ):
            raise ValueError("reserve_price must be >= starting_price")
        return self


# ── Image upload flow ─────────────────────────────────────────

class ImageUploadRequest(BaseModel):
    """Request presigned URLs for image upload."""
    count: int = Field(..., ge=1, le=10)
    content_types: list[str] | None = Field(
        default=None,
        description="MIME types per image (default image/jpeg)",
    )


class ImageUploadURL(BaseModel):
    upload_url: str
    s3_key: str


class ImageUploadResponse(BaseModel):
    upload_urls: list[ImageUploadURL]
    expires_in: int = 900


class ImageConfirmRequest(BaseModel):
    """Confirm uploaded images with their S3 keys."""
    s3_keys: list[str] = Field(..., min_length=1, max_length=10)


class ImageConfirmResponse(BaseModel):
    confirmed: int
    processing: bool = True


# ── Image in response ─────────────────────────────────────────

class ListingImageOut(BaseModel):
    id: str
    s3_key: str
    s3_key_thumb_100: str | None = None
    s3_key_thumb_400: str | None = None
    s3_key_thumb_800: str | None = None
    display_order: int

    model_config = {"from_attributes": True}


# ── Seller summary in response ────────────────────────────────

class SellerSummary(BaseModel):
    id: str
    full_name: str | None = None
    full_name_ar: str | None = None
    ats_score: int = 400
    is_pro_seller: bool = False


# ── Listing response ─────────────────────────────────────────

class ListingResponse(BaseModel):
    id: str
    seller_id: str
    seller: SellerSummary | None = None
    category_id: int
    title_ar: str
    title_en: str
    description_ar: str | None = None
    description_en: str | None = None
    condition: str
    status: str
    is_certified: bool = False
    is_charity: bool = False
    ngo_id: int | None = None
    # Prices in cents
    starting_price: int
    reserve_price: int | None = None
    buy_it_now_price: int | None = None
    current_price: int | None = None
    bid_count: int = 0
    watcher_count: int = 0
    min_increment: int = 2500
    # Schedule
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    ended_at: datetime | None = None
    extension_count: int = 0
    # Location
    location_city: str | None = None
    location_country: str = "JO"
    # AI / moderation
    ai_generated: bool = False
    moderation_score: float | None = None
    moderation_status: str = "pending"
    phash: str | None = None
    view_count: int = 0
    # Images
    images: list[ListingImageOut] = []
    # Timestamps
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── My listings (grouped) response ──────────────────────────

class MyListingsResponse(BaseModel):
    active: list[ListingResponse] = []
    ended: list[ListingResponse] = []
    draft: list[ListingResponse] = []
    pending: list[ListingResponse] = []


# ── Paginated list response ──────────────────────────────────

class ListingListResponse(BaseModel):
    data: list[ListingResponse]
    total_count: int
    limit: int
    offset: int


# ── Publish response ─────────────────────────────────────────

class PublishResponse(BaseModel):
    id: str
    status: str
    moderation_score: float | None = None
    moderation_status: str


# ── Watch response ───────────────────────────────────────────

class WatchResponse(BaseModel):
    listing_id: str
    watching: bool
    watcher_count: int
