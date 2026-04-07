"""Escrow request/response schemas — SDD §5.5."""

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
    payment_deadline: str | None = None
    shipping_deadline: str | None = None
    inspection_deadline: str | None = None

    model_config = {"from_attributes": True}


class ConfirmReceiptRequest(BaseModel):
    pass  # No body — just the action


class UploadTrackingRequest(BaseModel):
    tracking_number: str
    carrier: str = Field(..., pattern=r"^(aramex|fetchr|jordan_post|other)$")


class FileDisputeRequest(BaseModel):
    reason: str = Field(..., min_length=10, max_length=1000)
    evidence_s3_keys: list[str] = Field(default_factory=list, max_length=5)


class EscrowEventOut(BaseModel):
    id: str
    escrow_id: str
    from_state: str
    to_state: str
    actor_id: str | None = None
    actor_type: str
    trigger: str
    created_at: str

    model_config = {"from_attributes": True}
