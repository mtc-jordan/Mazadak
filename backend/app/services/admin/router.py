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

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.types import UUIDPath
from app.services.auth.dependencies import require_role
from app.services.auth.models import User
from app.services.admin import schemas, service
from app.services.admin.models import Announcement
from app.services.listing.models import Category, Listing

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


# ═══════════════════════════════════════════════════════════════════
#  Featured listings (FR-LIST-010, FR-AUC-016)
# ═══════════════════════════════════════════════════════════════════

@router.post("/listings/{listing_id}/feature")
async def feature_listing(
    listing_id: UUIDPath,
    body: schemas.FeatureListingRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Feature a listing for a specified duration."""
    listing = await db.get(Listing, str(listing_id))
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    now = datetime.now(timezone.utc)
    listing.is_featured = True
    listing.featured_at = now
    listing.featured_until = now + timedelta(hours=body.duration_hours)

    await service.log_audit(str(admin.id), "feature_listing", "listing", str(listing_id), db)
    await db.commit()
    return {"success": True, "listing_id": str(listing_id), "featured_until": listing.featured_until.isoformat()}


@router.post("/listings/{listing_id}/unfeature")
async def unfeature_listing(
    listing_id: UUIDPath,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Remove featured status from a listing."""
    listing = await db.get(Listing, str(listing_id))
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    listing.is_featured = False
    listing.featured_at = None
    listing.featured_until = None

    await service.log_audit(str(admin.id), "unfeature_listing", "listing", str(listing_id), db)
    await db.commit()
    return {"success": True, "listing_id": str(listing_id)}


# ═══════════════════════════════════════════════════════════════════
#  Category management (FR-ADMIN-012)
# ═══════════════════════════════════════════════════════════════════

@router.post("/categories", status_code=201)
async def create_category(
    body: schemas.CreateCategoryRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new category."""
    cat = Category(
        name_ar=body.name_ar,
        name_en=body.name_en,
        slug=body.slug,
        parent_id=body.parent_id,
        sort_order=body.sort_order,
    )
    db.add(cat)
    await db.flush()
    await service.log_audit(str(admin.id), "create_category", "category", str(cat.id), db)
    await db.commit()
    await db.refresh(cat)
    return {"success": True, "id": cat.id, "name_en": cat.name_en, "slug": cat.slug}


@router.patch("/categories/{category_id}")
async def update_category(
    category_id: int,
    body: schemas.UpdateCategoryRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing category."""
    cat = await db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    if body.name_ar is not None:
        cat.name_ar = body.name_ar
    if body.name_en is not None:
        cat.name_en = body.name_en
    if body.slug is not None:
        cat.slug = body.slug
    if body.parent_id is not None:
        cat.parent_id = body.parent_id
    if body.sort_order is not None:
        cat.sort_order = body.sort_order

    await service.log_audit(str(admin.id), "update_category", "category", str(category_id), db)
    await db.commit()
    return {"success": True, "id": cat.id, "name_en": cat.name_en}


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a category. Blocks if it has child categories or listings."""
    cat = await db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    # Check for children
    children = await db.execute(
        select(Category).where(Category.parent_id == category_id).limit(1)
    )
    if children.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Cannot delete category with subcategories")

    # Check for listings using this category
    listings = await db.execute(
        select(Listing).where(Listing.category_id == category_id).limit(1)
    )
    if listings.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Cannot delete category with existing listings")

    await service.log_audit(str(admin.id), "delete_category", "category", str(category_id), db)
    await db.delete(cat)
    await db.commit()
    return {"success": True, "deleted_id": category_id}


# ═══════════════════════════════════════════════════════════════════
#  Announcement management (FR-ADMIN-011)
# ═══════════════════════════════════════════════════════════════════

@router.get("/announcements", response_model=schemas.AnnouncementListResponse)
async def list_announcements(
    active_only: bool = Query(default=False),
    _admin_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all announcements (optionally active only)."""
    query = select(Announcement).order_by(Announcement.created_at.desc())
    if active_only:
        query = query.where(Announcement.is_active == True)  # noqa: E712
    result = await db.execute(query)
    items = result.scalars().all()
    return schemas.AnnouncementListResponse(items=items, total=len(items))


@router.post("/announcements", response_model=schemas.AnnouncementOut, status_code=201)
async def create_announcement(
    body: schemas.CreateAnnouncementRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new announcement/banner."""
    ann = Announcement(
        id=str(uuid4()),
        title_ar=body.title_ar,
        title_en=body.title_en,
        body_ar=body.body_ar,
        body_en=body.body_en,
        type=body.type,
        starts_at=body.starts_at,
        expires_at=body.expires_at,
        target_audience=body.target_audience,
        created_by=str(admin.id),
    )
    db.add(ann)
    await service.log_audit(str(admin.id), "create_announcement", "announcement", ann.id, db)
    await db.commit()
    await db.refresh(ann)
    return ann


@router.patch("/announcements/{announcement_id}", response_model=schemas.AnnouncementOut)
async def update_announcement(
    announcement_id: str,
    body: schemas.UpdateAnnouncementRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing announcement."""
    ann = await db.get(Announcement, announcement_id)
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")

    if body.title_ar is not None:
        ann.title_ar = body.title_ar
    if body.title_en is not None:
        ann.title_en = body.title_en
    if body.body_ar is not None:
        ann.body_ar = body.body_ar
    if body.body_en is not None:
        ann.body_en = body.body_en
    if body.type is not None:
        ann.type = body.type
    if body.is_active is not None:
        ann.is_active = body.is_active
    if body.starts_at is not None:
        ann.starts_at = body.starts_at
    if body.expires_at is not None:
        ann.expires_at = body.expires_at
    if body.target_audience is not None:
        ann.target_audience = body.target_audience

    await service.log_audit(str(admin.id), "update_announcement", "announcement", announcement_id, db)
    await db.commit()
    await db.refresh(ann)
    return ann


@router.delete("/announcements/{announcement_id}")
async def delete_announcement(
    announcement_id: str,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete an announcement."""
    ann = await db.get(Announcement, announcement_id)
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")

    await service.log_audit(str(admin.id), "delete_announcement", "announcement", announcement_id, db)
    await db.delete(ann)
    await db.commit()
    return {"success": True, "deleted_id": announcement_id}


# ═══════════════════════════════════════════════════════════════
#  Analytics (P1-9)
# ═══════════════════════════════════════════════════════════════

@router.get("/analytics/platform")
async def get_platform_analytics(
    days: int = Query(default=30, ge=1, le=365),
    admin: User = Depends(_admin),
):
    """Platform-wide analytics from ClickHouse."""
    from app.core.analytics import get_platform_stats
    return get_platform_stats(days)


@router.get("/analytics/categories")
async def get_category_analytics(
    days: int = Query(default=30, ge=1, le=365),
    admin: User = Depends(_admin),
):
    """Bid activity breakdown by category."""
    from app.core.analytics import get_category_stats
    return {"categories": get_category_stats(days)}


@router.get("/analytics/revenue")
async def get_revenue_analytics(
    days: int = Query(default=30, ge=1, le=365),
    admin: User = Depends(_admin),
):
    """Daily revenue and GMV breakdown."""
    from app.core.analytics import get_revenue_stats
    return {"revenue": get_revenue_stats(days)}
