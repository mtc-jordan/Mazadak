"""Search request/response schemas — FR-SRCH-001 → FR-SRCH-012."""

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=200)
    category_id: int | None = None
    condition: str | None = None
    city: str | None = None
    is_authenticated: bool | None = None
    status: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None = None
    sort_by: str | None = None  # relevance | price_asc | price_desc | newest | ending_soon | most_bids
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)


class SuggestRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=20)


class SearchHit(BaseModel):
    id: str
    title_ar: str
    title_en: str | None = None
    category_id: int
    condition: str
    starting_price: float
    listing_currency: str
    image_url: str
    is_charity: bool
    brand: str | None = None
    city: str | None = None
    is_authenticated: bool = False
    bid_count: int = 0
    ends_at: str | None = None


class SuggestHit(BaseModel):
    id: str
    title_ar: str
    title_en: str | None = None
    image_url: str = ""


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    query: str
    total_hits: int
    page: int
    total_pages: int
    processing_time_ms: int
    facets: dict[str, dict[str, int]] | None = None


class SuggestResponse(BaseModel):
    hits: list[SuggestHit]
    query: str
    processing_time_ms: int
