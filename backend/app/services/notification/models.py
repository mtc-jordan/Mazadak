"""
Notification domain models — SDD §4.1.

Maps 1:1 to 0001_initial_schema migration ``notifications`` table.
Channels: push (FCM), sms (Twilio), email, whatsapp, in_app.
"""

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NotificationChannel(str, enum.Enum):
    PUSH = "push"
    SMS = "sms"
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    entity_type: Mapped[str | None] = mapped_column(String(50))
    title_en: Mapped[str | None] = mapped_column(String(200))
    title_ar: Mapped[str | None] = mapped_column(String(200))
    body_en: Mapped[str | None] = mapped_column(Text)
    body_ar: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, server_default="'{}'", nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channels_sent: Mapped[list] = mapped_column(JSONB, server_default="'[]'", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), unique=True, nullable=False)
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
