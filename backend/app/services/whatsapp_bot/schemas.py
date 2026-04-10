"""
Pydantic schemas for Meta Cloud API webhook payloads and bot responses.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Inbound Meta webhook payload (simplified) ────────────────────

class WhatsAppProfile(BaseModel):
    name: str | None = None


class WhatsAppContact(BaseModel):
    profile: WhatsAppProfile | None = None
    wa_id: str  # sender phone, E.164 without +


class WhatsAppAudio(BaseModel):
    id: str
    mime_type: str | None = None


class WhatsAppText(BaseModel):
    body: str


class WhatsAppInteractive(BaseModel):
    """Button / list reply."""
    type: str  # "button_reply" | "list_reply"
    button_reply: dict | None = None
    list_reply: dict | None = None


class WhatsAppMessage(BaseModel):
    from_: str | None = Field(None, alias="from")
    id: str
    timestamp: str
    type: str  # text | audio | interactive | image | ...
    text: WhatsAppText | None = None
    audio: WhatsAppAudio | None = None
    interactive: WhatsAppInteractive | None = None

    class Config:
        populate_by_name = True


class WhatsAppValue(BaseModel):
    messaging_product: str = "whatsapp"
    metadata: dict | None = None
    contacts: list[WhatsAppContact] | None = None
    messages: list[WhatsAppMessage] | None = None


class WhatsAppChange(BaseModel):
    value: WhatsAppValue
    field: str = "messages"


class WhatsAppEntry(BaseModel):
    id: str
    changes: list[WhatsAppChange]


class WhatsAppWebhookPayload(BaseModel):
    """Top-level Meta Cloud API webhook body."""
    object: str = "whatsapp_business_account"
    entry: list[WhatsAppEntry]


# ── Internal pipeline types ──────────────────────────────────────

class ParsedIntent(BaseModel):
    intent: str  # bid | check | help | link | unknown
    keyword: str | None = None
    amount: float | None = None
    auction_id: str | None = None
    confidence: float = 0.0
