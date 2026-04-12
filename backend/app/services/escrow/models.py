"""
Escrow domain models — SDD §3.3 & §4.2.

12-state FSM. escrow_events is APPEND-ONLY (financial audit trail).
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class EscrowState(str, enum.Enum):
    PAYMENT_PENDING = "payment_pending"
    FUNDS_HELD = "funds_held"
    SHIPPING_REQUESTED = "shipping_requested"
    LABEL_GENERATED = "label_generated"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    INSPECTION_PERIOD = "inspection_period"
    DISPUTED = "disputed"
    UNDER_REVIEW = "under_review"
    RELEASED = "released"
    RESOLVED_RELEASED = "resolved_released"
    RESOLVED_REFUNDED = "resolved_refunded"
    RESOLVED_SPLIT = "resolved_split"
    CANCELLED = "cancelled"


# NOTE on the carrier-event states (label_generated, shipped, in_transit,
# delivered): the SDD describes a fully tracked carrier path, but in v1 we
# do not poll Aramex for live tracking events.  Sellers either upload an
# AWB number (upload_tracking → in_transit) or generate an Aramex label
# (create_shipment → label_generated), and buyers explicitly mark
# delivered (mark_delivered → inspection_period).  The extra transitions
# below collapse the unreachable middle of the FSM into the few hops we
# actually fire from production endpoints, while leaving the original
# fully-tracked path intact for when Aramex polling lands in Phase 2.
VALID_TRANSITIONS: dict[str, list[str]] = {
    "payment_pending":    ["funds_held", "cancelled"],
    "funds_held":         ["shipping_requested", "cancelled"],
    "shipping_requested": ["label_generated", "in_transit", "disputed", "cancelled"],
    "label_generated":    ["shipped", "in_transit", "inspection_period", "disputed"],
    "shipped":            ["in_transit", "disputed"],
    "in_transit":         ["delivered", "inspection_period", "disputed"],
    "delivered":          ["inspection_period", "disputed"],
    "inspection_period":  ["released", "disputed"],
    "disputed":           ["under_review"],
    "under_review":       ["resolved_released", "resolved_refunded", "resolved_split"],
    # Terminal states
    "released":           [],
    "resolved_released":  [],
    "resolved_refunded":  [],
    "resolved_split":     [],
    "cancelled":          [],
}

TERMINAL_STATES = {"released", "resolved_released", "resolved_refunded", "resolved_split", "cancelled"}


class CarrierType(str, enum.Enum):
    ARAMEX = "aramex"
    FETCHR = "fetchr"
    JORDAN_POST = "jordan_post"
    OTHER = "other"


class ActorType(str, enum.Enum):
    BUYER = "buyer"
    SELLER = "seller"
    MEDIATOR = "mediator"
    ADMIN = "admin"
    SYSTEM = "system"


class Escrow(Base, TimestampMixin):
    __tablename__ = "escrows"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    auction_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), unique=True, nullable=False,
    )
    winner_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    seller_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    mediator_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))

    state: Mapped[EscrowState] = mapped_column(
        String(25), default=EscrowState.PAYMENT_PENDING, nullable=False, index=True,
    )

    amount: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    currency: Mapped[str] = mapped_column(Text, default="JOD", nullable=False)
    seller_amount: Mapped[float | None] = mapped_column(Numeric(10, 3))

    payment_intent_id: Mapped[str | None] = mapped_column(Text)
    checkout_payment_id: Mapped[str | None] = mapped_column(Text)
    payment_link: Mapped[str | None] = mapped_column(Text)

    tracking_number: Mapped[str | None] = mapped_column(Text)
    carrier: Mapped[str | None] = mapped_column(String(20))

    dispute_reason: Mapped[str | None] = mapped_column(Text)
    evidence_s3_keys: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    evidence_hashes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    payment_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shipping_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inspection_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    last_transition_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transition_count: Mapped[int] = mapped_column(default=0, server_default="0")

    retry_count: Mapped[int] = mapped_column(default=0, server_default="0")


class EscrowEvent(Base):
    """APPEND-ONLY — permanent financial audit trail."""

    __tablename__ = "escrow_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    escrow_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    from_state: Mapped[str] = mapped_column(Text, nullable=False)
    to_state: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    actor_type: Mapped[ActorType] = mapped_column(String(10), nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


class DisputeReason(str, enum.Enum):
    NOT_AS_DESCRIBED = "not_as_described"
    NOT_RECEIVED = "not_received"
    DAMAGED = "damaged"
    COUNTERFEIT = "counterfeit"
    WRONG_ITEM = "wrong_item"
    OTHER = "other"


class DisputeStatus(str, enum.Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED_BUYER = "resolved_buyer"
    RESOLVED_SELLER = "resolved_seller"
    RESOLVED_SPLIT = "resolved_split"
    CLOSED = "closed"


class Dispute(Base, TimestampMixin):
    __tablename__ = "disputes"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    escrow_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    buyer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    seller_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_detail: Mapped[str | None] = mapped_column(Text)
    desired_resolution: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="open", index=True,
    )
    admin_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    admin_ruling: Mapped[str | None] = mapped_column(Text)
    admin_ruled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_resolution_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    buyer_evidence_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )
    seller_evidence_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )
    # -- Seller response (FR-DISP-004) ──────────────────────────
    seller_response: Mapped[str | None] = mapped_column(Text)
    seller_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seller_response_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seller_proposed_resolution: Mapped[str | None] = mapped_column(String(50))


class DisputeEvidence(Base):
    __tablename__ = "dispute_evidence"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    dispute_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    uploader_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    uploader_role: Mapped[str] = mapped_column(String(10), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int | None] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class NgoPartner(Base):
    """NGO partners for charity auctions — zakat-eligible organizations."""

    __tablename__ = "ngo_partners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    logo_s3_key: Mapped[str | None] = mapped_column(String(500))
    is_zakat_eligible: Mapped[bool] = mapped_column(
        server_default="false", nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        server_default="true", nullable=False,
    )
    checkout_merchant_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class ZakatReceipt(Base):
    """Zakat receipt issued for charity auction proceeds."""

    __tablename__ = "zakat_receipts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    escrow_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    ngo_id: Mapped[int] = mapped_column(Integer, nullable=False)
    buyer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # cents
    receipt_number: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    pdf_s3_key: Mapped[str | None] = mapped_column(String(500))
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class DisputeMessage(Base):
    """Dispute communication thread — buyer, seller, and admin messages."""

    __tablename__ = "dispute_messages"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    dispute_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    sender_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    sender_role: Mapped[str] = mapped_column(String(10), nullable=False)  # buyer, seller, admin
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_s3_key: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class Rating(Base):
    """Post-transaction rating — one per escrow (buyer rates seller or vice versa)."""

    __tablename__ = "ratings"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    escrow_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, unique=True)
    rater_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    ratee_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    is_anonymous: Mapped[bool] = mapped_column(
        server_default="false", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
