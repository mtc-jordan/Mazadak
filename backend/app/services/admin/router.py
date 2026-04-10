"""
Admin API endpoints — SDD §5.9.

All endpoints require require_role('admin', 'superadmin').
All mutating endpoints INSERT to admin_audit_log before executing.

Sections:
  1. Moderation queue (listings)
  2. Dispute queue
  3. User management
  4. Dashboard stats
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.types import UUIDPath
from app.services.auth.dependencies import require_role
from app.services.auth.models import User
from app.services.admin import schemas, service

router = APIRouter(prefix="/admin", tags=["admin"])

_admin = require_role("admin", "superadmin")


# ═══════════════════════════════════════════════════════════════════
#  Moderation queue
# ═══════════════════════════════════════════════════════════════════

@router.get("/moderation/queue", response_model=schemas.ModerationQueueResponse)
async def moderation_queue(
    status: str | None = Query(default=None, pattern=r"^(pending|needs_review|escalated)$"),
    sort: str | None = Query(default=None, pattern=r"^(wait_time_asc|risk_score_desc)$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=50),
    _admin_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Paginated moderation queue with seller history and SLA flags."""
    return await service.get_moderation_queue(db, status=status, sort=sort, page=page, per_page=per_page)


@router.post("/moderation/{listing_id}/approve")
async def approve_listing(
    listing_id: UUIDPath,
    body: schemas.ApproveRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve listing: moderation_status=approved, status=active."""
    listing = await service.approve_listing(listing_id, str(admin.id), body.notes, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {"success": True, "listing_id": listing_id, "status": "approved"}


@router.post("/moderation/{listing_id}/reject")
async def reject_listing(
    listing_id: UUIDPath,
    body: schemas.RejectRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reject listing: moderation_status=rejected, status=draft."""
    listing = await service.reject_listing(listing_id, str(admin.id), body.reason, body.reason_ar, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {"success": True, "listing_id": listing_id, "status": "rejected"}


@router.post("/moderation/{listing_id}/require-edit")
async def require_edit_listing(
    listing_id: UUIDPath,
    body: schemas.RequireEditRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Require edits: moderation_status=needs_edit, status=draft."""
    listing = await service.require_edit_listing(listing_id, str(admin.id), body.required_changes, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {"success": True, "listing_id": listing_id, "status": "needs_edit"}


@router.post("/moderation/{listing_id}/escalate")
async def escalate_listing(
    listing_id: UUIDPath,
    body: schemas.EscalateRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Escalate to superadmin: moderation_status=escalated."""
    listing = await service.escalate_listing(listing_id, str(admin.id), body.reason, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {"success": True, "listing_id": listing_id, "status": "escalated"}


# ═══════════════════════════════════════════════════════════════════
#  Dispute queue
# ═══════════════════════════════════════════════════════════════════

@router.get("/disputes/queue", response_model=schemas.DisputeQueueResponse)
async def dispute_queue(
    status: str | None = Query(default=None, pattern=r"^(open|under_review|all)$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=50),
    _admin_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Paginated dispute queue sorted by wait time (longest first)."""
    filter_status = None if status == "all" else status
    return await service.get_dispute_queue(db, status=filter_status, page=page, per_page=per_page)


@router.post("/disputes/{dispute_id}/assign")
async def assign_dispute(
    dispute_id: UUIDPath,
    body: schemas.AssignDisputeRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Assign dispute to an admin and transition escrow to under_review."""
    dispute = await service.assign_dispute(dispute_id, str(admin.id), body.admin_id, db)
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    return {"success": True, "dispute_id": dispute_id, "admin_id": body.admin_id}


@router.post("/disputes/{dispute_id}/rule")
async def rule_dispute(
    dispute_id: UUIDPath,
    body: schemas.RuleDisputeRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Rule on a dispute: release/refund/split, trigger payout, notify parties."""
    try:
        dispute = await service.rule_dispute(
            dispute_id, str(admin.id),
            body.outcome, body.ruling_text, body.ruling_text_ar,
            body.split_ratio_buyer, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    return {"success": True, "dispute_id": dispute_id, "outcome": body.outcome}


# ═══════════════════════════════════════════════════════════════════
#  User management
# ═══════════════════════════════════════════════════════════════════

@router.get("/users", response_model=schemas.UserListResponse)
async def list_users(
    phone: str | None = Query(default=None, max_length=20),
    name: str | None = Query(default=None, max_length=100),
    ats_min: int | None = Query(default=None, ge=0, le=1000),
    ats_max: int | None = Query(default=None, ge=0, le=1000),
    status: str | None = Query(default=None, max_length=20),
    kyc_status: str | None = Query(default=None, max_length=20),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=50),
    _admin_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Search/filter users with ATS breakdown, strike count, dispute count, total sales."""
    return await service.get_users(
        db, phone=phone, name=name, ats_min=ats_min, ats_max=ats_max,
        status=status, kyc_status=kyc_status, page=page, per_page=per_page,
    )


@router.get("/users/{user_id}", response_model=schemas.UserDetailResponse)
async def get_user_detail(
    user_id: UUIDPath,
    _admin_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Full user profile + KYC docs (pre-signed S3 URLs) + audit history."""
    result = await service.get_user_detail(user_id, db)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return result


@router.post("/users/{user_id}/warn")
async def warn_user(
    user_id: UUIDPath,
    body: schemas.WarnRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send warning notification to user."""
    user = await service.warn_user(user_id, str(admin.id), body.reason, db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True, "user_id": user_id, "action": "warned"}


@router.post("/users/{user_id}/suspend")
async def suspend_user(
    user_id: UUIDPath,
    body: schemas.SuspendRequest,
    admin: User = Depends(_admin),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Suspend user for duration_hours. Blacklist all active JWTs."""
    user = await service.suspend_user(
        user_id, str(admin.id), body.reason, body.duration_hours, redis, db,
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True, "user_id": user_id, "action": "suspended", "duration_hours": body.duration_hours}


@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: UUIDPath,
    body: schemas.BanRequest,
    admin: User = Depends(_admin),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Permanently ban user. Blacklist JWTs, cancel active listings."""
    user = await service.ban_user(user_id, str(admin.id), body.reason, redis, db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True, "user_id": user_id, "action": "banned"}


@router.post("/users/{user_id}/restore")
async def restore_user(
    user_id: UUIDPath,
    body: schemas.RestoreRequest,
    admin: User = Depends(_admin),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Restore a suspended/banned user. Remove JWT blacklist."""
    user = await service.restore_user(user_id, str(admin.id), body.reason, redis, db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True, "user_id": user_id, "action": "restored"}


# ═══════════════════════════════════════════════════════════════════
#  Dashboard stats
# ═══════════════════════════════════════════════════════════════════

@router.get("/dashboard", response_model=schemas.DashboardPeriodStats)
async def dashboard_stats(
    _admin_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate dashboard stats: active auctions, GMV, SLA breaches, etc."""
    return await service.get_dashboard_stats(db)
