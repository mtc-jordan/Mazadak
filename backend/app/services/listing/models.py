"""
Listing domain models — SDD §4.2: listings, listing_images.

Maps 1:1 to 0001_initial_schema migration tables.
All prices stored as INTEGER cents (1 JOD = 1000 fils).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin


# ── Enums (must match CREATE TYPE in migration) ────────────────

class ListingCondition(str, enum.Enum):
    BRAND_NEW = "brand_new"
    LIKE_NEW = "like_new"
    VERY_GOOD = "very_good"
    GOOD = "good"
    ACCEPTABLE = "acceptable"


class ListingStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    ENDED = "ended"
    CANCELLED = "cancelled"
    RELISTED = "relisted"


# ── Listing ────────────────────────────────────────────────────

class Listing(Base, TimestampMixin):
    __tablename__ = "listings"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    seller_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True,
    )
    category_id: Mapped[int] = mapped_column(Integer, nullable=False)

    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    title_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    description_en: Mapped[str | None] = mapped_column(Text)
    description_ar: Mapped[str | None] = mapped_column(Text)

    condition: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(25), nullable=False, server_default="draft", index=True,
    )

    is_certified: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
    )
    is_charity: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
    )
    ngo_id: Mapped[int | None] = mapped_column(Integer)

    # -- Prices in INTEGER cents ---------------------------------
    starting_price: Mapped[int] = mapped_column(Integer, nullable=False)
    reserve_price: Mapped[int | None] = mapped_column(Integer)
    buy_it_now_price: Mapped[int | None] = mapped_column(Integer)
    current_price: Mapped[int | None] = mapped_column(Integer)
    bid_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )
    watcher_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )
    min_increment: Mapped[int] = mapped_column(
        Integer, server_default="2500", nullable=False,
    )

    # -- Schedule ------------------------------------------------
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extension_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )

    # -- Location ------------------------------------------------
    location_city: Mapped[str | None] = mapped_column(String(100))
    location_country: Mapped[str] = mapped_column(
        String(5), server_default="JO", nullable=False,
    )

    # -- AI / moderation -----------------------------------------
    ai_generated: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
    )
    ai_category_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2))
    moderation_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    moderation_status: Mapped[str] = mapped_column(
        String(50), server_default="pending", nullable=False,
    )
    moderation_flags: Mapped[dict] = mapped_column(
        JSONB, server_default="'[]'", nullable=False,
    )
    phash: Mapped[str | None] = mapped_column(String(64))
    view_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )

    # -- Relationships -------------------------------------------
    images: Mapped[list["ListingImage"]] = relationship(
        back_populates="listing",
        lazy="selectin",
        order_by="ListingImage.display_order",
        cascade="all, delete-orphan",
    )


# ── Listing Images ─────────────────────────────────────────────

class ListingImage(Base):
    __tablename__ = "listing_images"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    listing_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("listings.id"), nullable=False, index=True,
    )
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    s3_key_thumb_100: Mapped[str | None] = mapped_column(String(500))
    s3_key_thumb_400: Mapped[str | None] = mapped_column(String(500))
    s3_key_thumb_800: Mapped[str | None] = mapped_column(String(500))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )

    listing: Mapped["Listing"] = relationship(back_populates="images")
