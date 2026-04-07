"""
Search models — Meilisearch document structure.

No SQLAlchemy models here. Search documents are synced from
the listings table via CDC (Change Data Capture) within 10s
of a status change (SDD §4.2 note).
"""

from pydantic import BaseModel


class SearchableListingDocument(BaseModel):
    """Document shape stored in Meilisearch index."""
    id: str
    title_ar: str
    title_en: str | None = None
    description_ar: str
    description_en: str | None = None
    category_id: int
    condition: str
    starting_price: float
    listing_currency: str
    status: str
    seller_id: str
    is_charity: bool
    image_url: str  # primary image (index 0)
    created_at: str
    # New fields for FR-SRCH
    brand: str | None = None
    city: str | None = None
    is_authenticated: bool = False
    bid_count: int = 0
    ends_at: str | None = None  # from auctions table
