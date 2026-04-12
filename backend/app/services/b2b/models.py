"""B2B Tender Rooms domain models — SDD §4.2, FR-B2B-001..010.

Three tables:
  - b2b_rooms        — private tender rooms created by admins for institutional clients
  - b2b_invitations  — access control: pre-qualified bidders invited per room
  - b2b_bids         — one sealed bid per user per room (append-only after submission)
"""

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin


class B2BRoomStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    RESULTS_ANNOUNCED = "results_announced"


class B2BInvitationStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REVOKED = "revoked"


class B2BRoom(Base):
    """Private tender room for institutional asset disposal.

    FR-B2B-002: invite-only, min lot 10K JOD.
    FR-B2B-004: sealed bid mode (amounts hidden until close).
    """

    __tablename__ = "b2b_rooms"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    client_name: Mapped[str] = mapped_column(String(300), nullable=False)
    client_name_ar: Mapped[str | None] = mapped_column(String(300))
    tender_reference: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True,
    )
    description: Mapped[str | None] = mapped_column(Text)
    documents: Mapped[list] = mapped_column(
        JSONB, server_default="'[]'", nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50), server_default="open", nullable=False,
    )
    submission_deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    results_announced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )

    # -- Added in migration 0005 ----------------------------------------
    client_logo_url: Mapped[str | None] = mapped_column(String(500))
    sealed: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False,
    )
    min_lot_amount: Mapped[int] = mapped_column(
        Integer, server_default="1000000", nullable=False,
    )  # cents — FR-B2B-002 min 10K JOD = 1,000,000 cents
    estimated_value: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    # -- Relationships --------------------------------------------------
    bids: Mapped[list["B2BBid"]] = relationship(
        back_populates="room",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    invitations: Mapped[list["B2BInvitation"]] = relationship(
        back_populates="room",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class B2BBid(Base):
    """One sealed bid per invited user per room.

    Append-only once submitted; cannot be edited.
    Uniqueness enforced by service layer + single check at submit time.
    """

    __tablename__ = "b2b_bids"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    room_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("b2b_rooms.id"),
        nullable=False,
        index=True,
    )
    bidder_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # cents
    notes: Mapped[str | None] = mapped_column(Text)
    validity_days: Mapped[int] = mapped_column(Integer, nullable=False)
    attachments: Mapped[list] = mapped_column(
        JSONB, server_default="'[]'", nullable=False,
    )
    is_winner: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
    submission_ref: Mapped[str | None] = mapped_column(String(50), unique=True)

    room: Mapped["B2BRoom"] = relationship(back_populates="bids")


class B2BInvitation(Base):
    """Access control for tender rooms — FR-B2B-003 pre-qualification."""

    __tablename__ = "b2b_invitations"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    room_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("b2b_rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    invited_by: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30), server_default="pending", nullable=False,
    )
    min_ats_score: Mapped[int | None] = mapped_column(Integer)
    min_kyc_level: Mapped[str | None] = mapped_column(String(20))
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    room: Mapped["B2BRoom"] = relationship(back_populates="invitations")
