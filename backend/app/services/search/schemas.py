"""Search request/response schemas — FR-SRCH-001 -> FR-SRCH-012."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    category_ids: list[int] | None = None
    conditions: list[str] | None = Field(default=None, max_length=10)
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)
    status: list[str] | None = Field(default=None, max_length=5)
    is_certified: bool | None = None
    is_charity: bool | None = None
    location_country: str | None = Field(default=None, max_length=5)
    ends_before: datetime | None = None
    ends_after: datetime | None = None


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=200)
    filters: SearchFilters | None = None
    sort: str | None = None   # ends_asc | price_asc | price_desc | bids_desc | newest
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=50)


class SearchHit(BaseModel):
    id: str
    title_ar: str
    title_en: str | None = None
    category_id: int
    condition: str
    starting_price: int
    current_price: int | None = None
    image_url: str = ""
    is_charity: bool = False
    is_certified: bool = False
    location_city: str | None = None
    location_country: str = "JO"
    bid_count: int = 0
    ends_at: str | None = None


class SuggestHit(BaseModel):
    title_ar: str
    title_en: str | None = None
    category_id: int | None = None


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    total: int
    page: int
    per_page: int
    facets: dict[str, dict[str, int]] | None = None
    query_time_ms: int = 0
    degraded_mode: bool = False


class SuggestResponse(BaseModel):
    hits: list[SuggestHit]
    query: str
    processing_time_ms: int = 0
