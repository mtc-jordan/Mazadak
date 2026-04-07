"""
Listing domain models — SDD §4.2: listings, listing_images, authentication_certs.
"""

import enum
from uuid import uuid4

from sqlalchemy import Boolean, Float, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class ListingStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_MODERATION = "pending_moderation"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    ENDED = "ended"
    SOLD = "sold"
    UNSOLD = "unsold"
    CANCELLED = "cancelled"


class ItemCondition(str, enum.Enum):
    NEW = "new"
    LIKE_NEW = "like_new"
    GOOD = "good"
    FAIR = "fair"
    FOR_PARTS = "for_parts"


class Listing(Base, TimestampMixin):
    __tablename__ = "listings"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    seller_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)

    title_ar: Mapped[str] = mapped_column(Text, nullable=False)
    title_en: Mapped[str | None] = mapped_column(Text)
    description_ar: Mapped[str] = mapped_column(Text, nullable=False)
    description_en: Mapped[str | None] = mapped_column(Text)

    category_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    condition: Mapped[str] = mapped_column(String(20), nullable=False)

    starting_price: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    reserve_price: Mapped[float | None] = mapped_column(Numeric(10, 3))
    buy_it_now_price: Mapped[float | None] = mapped_column(Numeric(10, 3))
    listing_currency: Mapped[str] = mapped_column(Text, default="JOD", nullable=False)

    duration_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)

    status: Mapped[str] = mapped_column(
        String(25), default=ListingStatus.DRAFT.value, nullable=False, index=True,
    )

    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_price_low: Mapped[float | None] = mapped_column(Numeric(10, 3))
    ai_price_high: Mapped[float | None] = mapped_column(Numeric(10, 3))
    phash: Mapped[str | None] = mapped_column(Text)
    moderation_score: Mapped[float | None] = mapped_column(Float)
    moderation_flags: Mapped[str | None] = mapped_column(Text)  # JSON-serialised list

    authentication_cert_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))

    brand: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(50))

    is_charity: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ngo_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))

    # Store as JSON text for SQLite compat; PostgreSQL migration uses ARRAY
    image_urls: Mapped[str | None] = mapped_column(Text)  # JSON array string
    bid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    published_at: Mapped[str | None] = mapped_column()


# ── Helper to serialise / deserialise image_urls ──────────────

import json as _json


def get_image_urls(listing: Listing) -> list[str]:
    """Deserialise image_urls JSON text → list."""
    if not listing.image_urls:
        return []
    if isinstance(listing.image_urls, list):
        return listing.image_urls
    return _json.loads(listing.image_urls)


def set_image_urls(listing: Listing, urls: list[str]) -> None:
    """Serialise list → JSON text for storage."""
    listing.image_urls = _json.dumps(urls)
