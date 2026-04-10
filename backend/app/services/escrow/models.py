"""
Escrow domain models — SDD §3.3 & §4.2.

12-state FSM. escrow_events is APPEND-ONLY (financial audit trail).
"""

import enum

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


VALID_TRANSITIONS: dict[str, list[str]] = {
    "payment_pending":    ["funds_held", "cancelled"],
    "funds_held":         ["shipping_requested", "cancelled"],
    "shipping_requested": ["label_generated", "disputed", "cancelled"],
    "label_generated":    ["shipped", "disputed"],
    "shipped":            ["in_transit", "disputed"],
    "in_transit":         ["delivered", "disputed"],
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

    payment_deadline: Mapped[str | None] = mapped_column()
    shipping_deadline: Mapped[str | None] = mapped_column()
    inspection_deadline: Mapped[str | None] = mapped_column()
    evidence_deadline: Mapped[str | None] = mapped_column()
    release_deadline: Mapped[str | None] = mapped_column()

    last_transition_at: Mapped[str | None] = mapped_column()
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
    created_at: Mapped[str] = mapped_column(
        nullable=False, server_default=text("now()"),
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
    admin_ruled_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    auto_resolution_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    buyer_evidence_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )
    seller_evidence_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )


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
    uploaded_at: Mapped[str] = mapped_column(
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
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
