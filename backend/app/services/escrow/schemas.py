"""Escrow request/response schemas — SDD §5.5."""

from datetime import datetime

from pydantic import BaseModel, Field


class EscrowOut(BaseModel):
    id: str
    auction_id: str
    winner_id: str
    seller_id: str
    mediator_id: str | None = None
    state: str
    amount: float
    currency: str
    seller_amount: float | None = None
    payment_link: str | None = None
    tracking_number: str | None = None
    carrier: str | None = None
    payment_deadline: datetime | None = None
    shipping_deadline: datetime | None = None
    inspection_deadline: datetime | None = None

    model_config = {"from_attributes": True}


class ConfirmReceiptRequest(BaseModel):
    pass  # No body — just the action


class UploadTrackingRequest(BaseModel):
    tracking_number: str
    carrier: str = Field(..., pattern=r"^(aramex|fetchr|jordan_post|other)$")


class FileDisputeRequest(BaseModel):
    reason: str = Field(..., min_length=10, max_length=1000)
    evidence_s3_keys: list[str] = Field(default_factory=list, max_length=5)


class InitiatePaymentResponse(BaseModel):
    escrow_id: str
    payment_link: str
    expires_at: datetime | None = None


class EscrowEventOut(BaseModel):
    id: str
    escrow_id: str
    from_state: str
    to_state: str
    actor_id: str | None = None
    actor_type: str
    trigger: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Seller dispute response (FR-DISP-004) ────────────────────

class SellerDisputeResponseRequest(BaseModel):
    response_text: str = Field(..., min_length=10, max_length=5000)
    evidence_s3_keys: list[str] = Field(default_factory=list, max_length=10)
    proposed_resolution: str | None = Field(
        default=None,
        pattern=r"^(full_refund|partial_refund|reject|replacement)$",
    )


# ── Invoice (FR-ESC-024) ──────────────────────────────────────

class InvoiceLineItem(BaseModel):
    description_ar: str
    description_en: str
    amount: float
    currency: str = "JOD"


class InvoiceOut(BaseModel):
    invoice_number: str
    escrow_id: str
    auction_id: str
    issued_at: str
    buyer_id: str
    seller_id: str
    item_title: str
    item_description: str | None = None
    subtotal: float
    platform_fee: float
    platform_fee_percent: float
    seller_payout: float
    total: float
    currency: str = "JOD"
    status: str
    line_items: list[InvoiceLineItem] = []


class DisputeOut(BaseModel):
    id: str
    escrow_id: str
    buyer_id: str
    seller_id: str
    reason: str
    reason_detail: str | None = None
    status: str
    seller_response: str | None = None
    seller_responded_at: datetime | None = None
    seller_proposed_resolution: str | None = None
    buyer_evidence_count: int = 0
    seller_evidence_count: int = 0
    admin_id: str | None = None
    admin_ruling: str | None = None
    admin_ruled_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── Dispute messages ──────────────────────────────────────────

class SendDisputeMessageRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)
    attachment_s3_key: str | None = Field(default=None, max_length=500)


class DisputeMessageOut(BaseModel):
    id: str
    dispute_id: str
    sender_id: str
    sender_role: str
    body: str
    attachment_s3_key: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Post-transaction ratings ──────────────────────────────────

class SubmitRatingRequest(BaseModel):
    score: int = Field(..., ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)
    is_anonymous: bool = False


# ── Shipping (P1-8) ─────────────────────────────────────────

class ShippingAddress(BaseModel):
    line1: str = Field(..., min_length=1, max_length=200)
    line2: str = ""
    city: str = Field(default="Amman", max_length=100)
    state: str = ""
    postal_code: str = ""
    country_code: str = Field(default="JO", max_length=2)
    contact_name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=5, max_length=20)
    email: str = ""


class CreateShipmentRequest(BaseModel):
    seller_address: ShippingAddress
    buyer_address: ShippingAddress
    weight_kg: float = Field(default=1.0, ge=0.1, le=70.0)
    description: str = Field(default="Auction item", max_length=200)


class ShipmentResponse(BaseModel):
    success: bool
    tracking_number: str = ""
    label_url: str = ""
    error: str = ""


class TrackingEventOut(BaseModel):
    timestamp: datetime
    location: str
    description: str
    code: str


class TrackingResponse(BaseModel):
    success: bool
    tracking_number: str = ""
    current_status: str = ""
    delivered: bool = False
    events: list[TrackingEventOut] = []
    error: str = ""


class RatingOut(BaseModel):
    id: str
    escrow_id: str
    rater_id: str
    ratee_id: str
    role: str
    score: int
    comment: str | None = None
    is_anonymous: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}
