"""
Auth domain models — users, user_kyc_documents, refresh_tokens.

SDD §4.2: users table with phone-based auth, KYC status, ATS scoring.
Maps 1:1 to 0001_initial_schema migration.
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin


# ── Enums (must match CREATE TYPE in migration) ────────────────

class UserRole(str, enum.Enum):
    BUYER = "buyer"
    SELLER = "seller"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class UserStatus(str, enum.Enum):
    PENDING_KYC = "pending_kyc"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BANNED = "banned"


class KYCStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    PENDING_REVIEW = "pending_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ATSTier(str, enum.Enum):
    STARTER = "starter"       # < 300
    TRUSTED = "trusted"       # 300–599
    PRO = "pro"               # 600–799
    ELITE = "elite"           # 800–1000


# ── Users ──────────────────────────────────────────────────────

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    phone_verified: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
    )
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    full_name_ar: Mapped[str | None] = mapped_column(String(255))

    role: Mapped[UserRole] = mapped_column(
        String(20), nullable=False, server_default="buyer",
    )
    status: Mapped[UserStatus] = mapped_column(
        String(20), nullable=False, server_default="pending_kyc",
    )
    kyc_status: Mapped[KYCStatus] = mapped_column(
        String(20), nullable=False, server_default="not_started",
    )
    kyc_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kyc_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kyc_rejection_reason: Mapped[str | None] = mapped_column(Text)

    # -- ATS (Auction Trust Score) composite -------------------------
    ats_score: Mapped[int] = mapped_column(
        Integer, server_default="400", nullable=False,
    )
    ats_identity_score: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )
    ats_completion_score: Mapped[int] = mapped_column(
        Integer, server_default="400", nullable=False,
    )
    ats_speed_score: Mapped[int] = mapped_column(
        Integer, server_default="400", nullable=False,
    )
    ats_rating_score: Mapped[int] = mapped_column(
        Integer, server_default="400", nullable=False,
    )
    ats_quality_score: Mapped[int] = mapped_column(
        Integer, server_default="400", nullable=False,
    )
    ats_dispute_score: Mapped[int] = mapped_column(
        Integer, server_default="400", nullable=False,
    )
    strike_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )

    # -- Pro seller --------------------------------------------------
    is_pro_seller: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
    )
    pro_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    commission_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), server_default="0.0500", nullable=False,
    )

    # -- WhatsApp bot link -------------------------------------------
    whatsapp_linked: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
    )
    whatsapp_linked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    # -- FCM push tokens (JSON array) ---------------------------------
    fcm_tokens: Mapped[list | None] = mapped_column(JSONB, server_default="'[]'")

    # -- Preferences & tracking --------------------------------------
    preferred_language: Mapped[str] = mapped_column(
        String(5), server_default="ar", nullable=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # -- Relationships -----------------------------------------------
    kyc_documents: Mapped[list["UserKycDocument"]] = relationship(
        back_populates="user", lazy="selectin",
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", lazy="noload",
    )

    # -- Convenience properties --------------------------------------
    @property
    def is_banned(self) -> bool:
        s = self.status.value if hasattr(self.status, "value") else self.status
        return s == "banned"

    @property
    def is_suspended(self) -> bool:
        s = self.status.value if hasattr(self.status, "value") else self.status
        return s == "suspended"

    @property
    def ats_tier(self) -> ATSTier:
        if self.ats_score < 300:
            return ATSTier.STARTER
        if self.ats_score < 600:
            return ATSTier.TRUSTED
        if self.ats_score < 800:
            return ATSTier.PRO
        return ATSTier.ELITE


# ── KYC Documents ──────────────────────────────────────────────

class UserKycDocument(Base):
    __tablename__ = "user_kyc_documents"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True,
    )
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    rekognition_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="kyc_documents")


# ── Refresh Tokens ─────────────────────────────────────────────

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    device_info: Mapped[dict | None] = mapped_column(JSONB)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")
