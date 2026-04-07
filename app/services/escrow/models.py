"""
Escrow domain models — SDD §3.3 & §4.2.

12-state FSM. escrow_events is APPEND-ONLY (financial audit trail).
"""

import enum

from sqlalchemy import Float, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class EscrowState(str, enum.Enum):
    INITIATED = "initiated"
    PAYMENT_PENDING = "payment_pending"
    PAYMENT_FAILED = "payment_failed"
    FUNDS_HELD = "funds_held"
    SHIPPING_REQUESTED = "shipping_requested"
    IN_TRANSIT = "in_transit"
    INSPECTION_PERIOD = "inspection_period"
    DISPUTED = "disputed"
    UNDER_REVIEW = "under_review"
    RELEASED = "released"
    REFUNDED = "refunded"
    PARTIALLY_RELEASED = "partially_released"
    CANCELLED = "cancelled"


VALID_TRANSITIONS: dict[str, list[str]] = {
    "initiated":          ["payment_pending"],
    "payment_pending":    ["funds_held", "payment_failed", "cancelled"],
    "payment_failed":     ["payment_pending", "cancelled"],
    "funds_held":         ["shipping_requested"],
    "shipping_requested": ["in_transit", "disputed"],
    "in_transit":         ["inspection_period"],
    "inspection_period":  ["released", "disputed"],
    "disputed":           ["under_review"],
    "under_review":       ["released", "refunded", "partially_released"],
    "released":           [],
    "refunded":           [],
    "partially_released": [],
    "cancelled":          [],
}


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
        String(25), default=EscrowState.INITIATED, nullable=False, index=True,
    )

    amount: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    currency: Mapped[str] = mapped_column(Text, default="JOD", nullable=False)
    seller_amount: Mapped[float | None] = mapped_column(Numeric(10, 3))

    payment_intent_id: Mapped[str | None] = mapped_column(Text)
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
