"""B2B Tender Rooms Pydantic schemas.

Mobile contract (from tender_room_screen.dart):
  GET /tenders/{id}  → TenderRoomResponse
  POST /tenders/{id}/bids → BidSubmittedResponse
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════════════════════════════════
#  Bidder-facing schemas (match mobile contract exactly)
# ═══════════════════════════════════════════════════════════════════


class TenderDocument(BaseModel):
    name: str
    size: str
    url: str


class TenderResultItem(BaseModel):
    rank: int
    amount: float  # JOD (dollars, not cents) — mobile displays as float
    is_awarded: bool
    is_you: bool


class TenderRoomResponse(BaseModel):
    """Mobile GET /tenders/{id} response."""

    access: str  # "invited" | "denied"
    phase: str  # "open" | "submitted" | "results"
    client_name: str
    client_logo_url: str | None = None
    reference: str
    deadline: str  # ISO 8601
    sealed_notice: bool
    documents: list[TenderDocument] = Field(default_factory=list)
    submitted_at: str | None = None
    submission_ref: str | None = None
    bid_result: str = "pending"  # "pending" | "won" | "lost"
    results: list[TenderResultItem] = Field(default_factory=list)
    winning_amount: float | None = None


class SubmitBidRequest(BaseModel):
    """Mobile POST /tenders/{id}/bids request."""

    amount: float = Field(..., gt=0, description="Bid amount in JOD (e.g. 15000.50)")
    notes: str = ""
    validity_days: int = Field(..., ge=1, le=365)
    attachment_paths: list[str] = Field(default_factory=list)


class BidSubmittedResponse(BaseModel):
    """Mobile POST /tenders/{id}/bids response."""

    submitted_at: str  # ISO 8601
    submission_ref: str


# ═══════════════════════════════════════════════════════════════════
#  Admin schemas
# ═══════════════════════════════════════════════════════════════════


class TenderRoomCreateRequest(BaseModel):
    client_name: str = Field(..., min_length=2, max_length=300)
    client_name_ar: str | None = Field(default=None, max_length=300)
    tender_reference: str = Field(..., min_length=3, max_length=200)
    description: str | None = None
    submission_deadline: datetime
    sealed: bool = True
    min_lot_amount: int = Field(default=1_000_000, ge=1_000_000, description="Cents; FR-B2B-002 min 10K JOD")
    estimated_value: int | None = Field(default=None, ge=0)
    client_logo_url: str | None = None
    documents: list[dict] = Field(default_factory=list)

    @field_validator("submission_deadline")
    @classmethod
    def deadline_in_future(cls, v: datetime) -> datetime:
        from datetime import timezone
        now = datetime.now(timezone.utc)
        deadline = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if deadline <= now:
            raise ValueError("submission_deadline must be in the future")
        return deadline


class RoomUpdateRequest(BaseModel):
    status: str | None = None
    submission_deadline: datetime | None = None
    description: str | None = None
    client_logo_url: str | None = None
    estimated_value: int | None = None


class InviteBidderItem(BaseModel):
    user_id: str
    min_ats_score: int | None = None
    min_kyc_level: str | None = None


class InviteBiddersRequest(BaseModel):
    invitations: list[InviteBidderItem] = Field(..., min_length=1)


class AnnounceResultsRequest(BaseModel):
    winner_bid_id: str


class AdminBidItem(BaseModel):
    id: str
    bidder_id: str
    bidder_name: str | None = None
    amount: int  # cents
    notes: str | None = None
    validity_days: int
    is_winner: bool
    submitted_at: datetime
    submission_ref: str | None = None

    model_config = {"from_attributes": True}


class AdminInvitationItem(BaseModel):
    id: str
    user_id: str
    user_name: str | None = None
    status: str
    min_ats_score: int | None = None
    min_kyc_level: str | None = None
    invited_at: datetime
    responded_at: datetime | None = None

    model_config = {"from_attributes": True}


class AdminRoomListItem(BaseModel):
    id: str
    client_name: str
    client_name_ar: str | None = None
    tender_reference: str
    status: str
    submission_deadline: datetime
    sealed: bool
    min_lot_amount: int
    estimated_value: int | None = None
    bid_count: int = 0
    invitation_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminRoomListResponse(BaseModel):
    items: list[AdminRoomListItem]
    total: int
    page: int
    per_page: int


class AdminRoomDetail(BaseModel):
    id: str
    client_name: str
    client_name_ar: str | None = None
    tender_reference: str
    description: str | None = None
    status: str
    submission_deadline: datetime
    results_announced_at: datetime | None = None
    sealed: bool
    min_lot_amount: int
    estimated_value: int | None = None
    client_logo_url: str | None = None
    documents: list[dict] = Field(default_factory=list)
    created_at: datetime
    bids: list[AdminBidItem] = Field(default_factory=list)
    invitations: list[AdminInvitationItem] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RoomAnalytics(BaseModel):
    room_id: str
    invited_count: int
    bid_count: int
    participation_rate: float  # 0.0–1.0
    avg_bid_amount: int | None = None  # cents
    min_bid_amount: int | None = None
    max_bid_amount: int | None = None
    price_vs_estimate_ratio: float | None = None  # winning_amount / estimated_value
    winner_amount: int | None = None
    time_to_close_hours: float | None = None


class CsvImportResponse(BaseModel):
    created_count: int
    created_ids: list[str]
    errors: list[str] = Field(default_factory=list)
