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
    description_ar: str | None = None
    description_en: str | None = None
    brand: str | None = None
    category_id: int
    condition: str
    starting_price: int  # cents
    current_price: int | None = None
    status: str
    seller_id: str
    seller_ats: int = 0
    is_charity: bool = False
    is_certified: bool = False
    image_url: str = ""  # primary image thumbnail
    location_city: str | None = None
    location_country: str = "JO"
    bid_count: int = 0
    ends_at_timestamp: int | None = None   # Unix timestamp for range filters
    created_at_timestamp: int | None = None
