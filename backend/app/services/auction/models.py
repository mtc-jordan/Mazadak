"""
Auction domain models — SDD §4.2: auctions, bids, proxy_bids.

bids table is APPEND-ONLY — REVOKE UPDATE, DELETE enforced at DB role level.
"""

import enum

from sqlalchemy import Boolean, Float, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class AuctionStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    ENDED = "ended"
    CANCELLED = "cancelled"


class Auction(Base, TimestampMixin):
    __tablename__ = "auctions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    listing_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), unique=True, nullable=False,
    )
    status: Mapped[AuctionStatus] = mapped_column(
        String(20), default=AuctionStatus.SCHEDULED, nullable=False, index=True,
    )
    starts_at: Mapped[str] = mapped_column(nullable=False)
    ends_at: Mapped[str] = mapped_column(nullable=False)

    current_price: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    min_increment: Mapped[float] = mapped_column(
        Numeric(10, 3), default=25.0, nullable=False,
    )
    bid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extension_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    winner_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    final_price: Mapped[float | None] = mapped_column(Numeric(10, 3))
    reserve_met: Mapped[bool | None] = mapped_column(Boolean)
    redis_synced_at: Mapped[str | None] = mapped_column()


class Bid(Base):
    """APPEND-ONLY — no updates or deletes ever."""

    __tablename__ = "bids"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    auction_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True,
    )
    amount: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    currency: Mapped[str] = mapped_column(Text, default="JOD", nullable=False)
    is_proxy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fraud_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[str] = mapped_column(
        nullable=False, server_default=text("now()"),
    )


class ProxyBid(Base, TimestampMixin):
    __tablename__ = "proxy_bids"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    auction_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    max_amount: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
