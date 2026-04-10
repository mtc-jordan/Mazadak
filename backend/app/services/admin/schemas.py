"""Admin API schemas — SDD §5.9."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ── Audit log ─────────────────────────────────────────────────────

class AuditLogEntry(BaseModel):
    id: str
    admin_id: str
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    before_state: dict | None = None
    after_state: dict | None = None
    created_at: datetime


# ── Moderation queue ──────────────────────────────────────────────

class SellerHistory(BaseModel):
    past_listings_count: int = 0
    rejection_rate: float = 0.0


class ModerationQueueItem(BaseModel):
    id: str
    title_en: str
    title_ar: str
    seller_id: str
    seller_name: str | None = None
    moderation_score: float | None = None
    moderation_status: str
    moderation_flags: list | None = None
    wait_time_minutes: int = 0
    is_overdue: bool = False
    seller_ats: int = 0
    seller_history: SellerHistory = SellerHistory()
    created_at: datetime


class ModerationQueueResponse(BaseModel):
    items: list[ModerationQueueItem]
    total: int
    page: int
    per_page: int


class ApproveRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=500)


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    reason_ar: str = Field(..., min_length=1)


class RequireEditRequest(BaseModel):
    required_changes: list[str] = Field(..., min_length=1)


class EscalateRequest(BaseModel):
    reason: str = Field(..., min_length=1)


# ── Dispute queue ─────────────────────────────────────────────────

class DisputeQueueItem(BaseModel):
    id: str
    escrow_id: str
    buyer_id: str
    seller_id: str
    reason: str
    reason_detail: str | None = None
    status: str
    admin_id: str | None = None
    buyer_evidence_count: int = 0
    seller_evidence_count: int = 0
    escrow_amount: float = 0
    escrow_currency: str = "JOD"
    wait_time_minutes: int = 0
    created_at: datetime


class DisputeQueueResponse(BaseModel):
    items: list[DisputeQueueItem]
    total: int
    page: int
    per_page: int


class AssignDisputeRequest(BaseModel):
    admin_id: str = Field(..., min_length=36, max_length=36)


class RuleDisputeRequest(BaseModel):
    outcome: str = Field(..., pattern=r"^(resolved_released|resolved_refunded|resolved_split)$")
    split_ratio_buyer: int | None = Field(default=None, ge=0, le=100)
    ruling_text: str = Field(..., min_length=100)
    ruling_text_ar: str = Field(..., min_length=1)


# ── User management ──────────────────────────────────────────────

class ATSBreakdown(BaseModel):
    overall: int = 0
    identity: int = 0
    completion: int = 0
    speed: int = 0
    rating: int = 0
    quality: int = 0
    dispute: int = 0


class UserRow(BaseModel):
    id: str
    phone: str
    full_name: str | None = None
    full_name_ar: str | None = None
    role: str
    status: str
    kyc_status: str
    ats_score: int = 0
    ats_breakdown: ATSBreakdown = ATSBreakdown()
    strike_count: int = 0
    dispute_count: int = 0
    total_sales: float = 0.0
    created_at: datetime


class UserListResponse(BaseModel):
    items: list[UserRow]
    total: int
    page: int
    per_page: int


class KycDocumentOut(BaseModel):
    id: str
    document_type: str | None = None
    s3_url: str
    status: str | None = None
    uploaded_at: datetime | None = None


class UserDetailResponse(BaseModel):
    user: UserRow
    kyc_documents: list[KycDocumentOut] = []
    audit_history: list[AuditLogEntry] = []


class WarnRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class SuspendRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    duration_hours: int = Field(..., gt=0)


class BanRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class RestoreRequest(BaseModel):
    reason: str = Field(..., min_length=1)


# ── Dashboard stats ──────────────────────────────────────────────

class DashboardPeriodStats(BaseModel):
    active_auctions_count: int = 0
    live_auctions_count: int = 0
    new_users_24h: int = 0
    kyc_pending_count: int = 0
    moderation_queue_count: int = 0
    disputes_open_count: int = 0
    gmv_24h: float = 0.0
    revenue_24h: float = 0.0
    avg_moderation_wait_time_minutes: float = 0.0
    sla_breach_count: int = 0
