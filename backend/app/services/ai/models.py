"""
AI service models — request/result tracking for audit.

The actual ML models (CLIP, GPT-4o, Whisper, XGBoost) run in the
separate ai-service GPU container. This module tracks API calls
and caches results.
"""

from sqlalchemy import Float, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class AIRequest(Base, TimestampMixin):
    """Audit log of AI service calls."""

    __tablename__ = "ai_requests"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    request_type: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True,
    )  # snap_to_list | price_oracle | moderate | fraud_score | transcribe | intent
    user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), index=True)
    listing_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    input_payload: Mapped[dict | None] = mapped_column(JSONB)
    output_payload: Mapped[dict | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        String(15), default="pending", nullable=False,
    )  # pending | completed | failed | fallback
