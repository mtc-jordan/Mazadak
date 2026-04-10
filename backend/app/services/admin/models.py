"""
Admin domain models — SDD §5.9.

Maps to admin_audit_log table from 0001_initial_schema migration.
"""

from __future__ import annotations

from sqlalchemy import DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID, INET
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AdminAuditLog(Base):
    """Append-only admin action audit trail."""

    __tablename__ = "admin_audit_log"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    admin_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    before_state: Mapped[dict | None] = mapped_column(JSONB)
    after_state: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
