"""
WhatsApp Bot data models — FR-BOT-001.

WaAccount links a WhatsApp phone number to a MZADAK user account.
BotConversation tracks multi-turn state for disambiguation flows.
"""

from __future__ import annotations

import enum

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class BotIntent(str, enum.Enum):
    BID = "bid"
    CHECK = "check"
    HELP = "help"
    LINK = "link"
    UNKNOWN = "unknown"


class ConversationState(str, enum.Enum):
    IDLE = "idle"
    AWAITING_AUCTION_CHOICE = "awaiting_auction_choice"
    AWAITING_AMOUNT = "awaiting_amount"
    AWAITING_CONFIRMATION = "awaiting_confirmation"


class WaAccount(Base, TimestampMixin):
    """Links a WhatsApp phone number to a MZADAK user.

    One phone → one account.  The user links via OTP flow (FR-BOT-002).
    """

    __tablename__ = "wa_accounts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    wa_phone: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, comment="E.164 without +",
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), index=True,
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (
        Index("ix_wa_accounts_phone_active", "wa_phone", "is_active"),
    )


class BotConversation(Base, TimestampMixin):
    """Tracks multi-turn conversation state for disambiguation.

    TTL is enforced by the service layer (expire after 5 min inactivity).
    """

    __tablename__ = "bot_conversations"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    wa_phone: Mapped[str] = mapped_column(String(20), index=True)
    state: Mapped[ConversationState] = mapped_column(
        String(50), default=ConversationState.IDLE,
    )
    intent: Mapped[BotIntent] = mapped_column(
        String(20), default=BotIntent.UNKNOWN,
    )
    # Stash partial context between turns
    context_auction_ids: Mapped[str | None] = mapped_column(
        Text, default=None, comment="JSON array of candidate auction IDs",
    )
    context_amount: Mapped[float | None] = mapped_column(default=None)
    context_keyword: Mapped[str | None] = mapped_column(
        String(200), default=None,
    )
