"""
Auth domain models — users, kyc_documents, sessions.

SDD §4.2: users table with phone-based auth, KYC status, ATS scoring.
"""

import enum
from uuid import uuid4

from sqlalchemy import Boolean, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class UserRole(str, enum.Enum):
    BUYER = "buyer"
    SELLER = "seller"
    PRO_SELLER = "pro_seller"
    MODERATOR = "moderator"
    MEDIATOR = "mediator"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class KYCStatus(str, enum.Enum):
    PENDING = "pending"
    PENDING_REVIEW = "pending_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ATSTier(str, enum.Enum):
    STARTER = "starter"       # < 300
    TRUSTED = "trusted"       # 300–599
    PRO = "pro"               # 600–799
    ELITE = "elite"           # 800–1000


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    phone: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    full_name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    full_name_en: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)

    role: Mapped[UserRole] = mapped_column(
        String(20), nullable=False, default=UserRole.BUYER,
    )
    kyc_status: Mapped[KYCStatus] = mapped_column(
        String(20), nullable=False, default=KYCStatus.PENDING,
    )
    kyc_verified_at: Mapped[str | None] = mapped_column()
    kyc_attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    ats_score: Mapped[int] = mapped_column(Integer, default=400, nullable=False)
    ats_tier: Mapped[ATSTier] = mapped_column(
        String(10), nullable=False, default=ATSTier.TRUSTED,
    )
    strike_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    country_code: Mapped[str] = mapped_column(Text, default="JO", nullable=False)
    preferred_language: Mapped[str] = mapped_column(Text, default="ar", nullable=False)


class KYCDocument(Base, TimestampMixin):
    __tablename__ = "kyc_documents"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(Text, nullable=False)  # national_id | passport
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    rekognition_result: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
