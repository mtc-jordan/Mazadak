"""
Admin service layer — SDD §5.9.

Moderation queue, dispute resolution, user management, dashboard stats.
All mutating operations INSERT to admin_audit_log before executing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin.models import AdminAuditLog
from app.services.auth.models import User, UserStatus
from app.services.auction.models import Auction
from app.services.escrow.models import (
    Dispute,
    DisputeStatus,
    Escrow,
    EscrowState,
)
from app.services.listing.models import Listing

logger = logging.getLogger(__name__)

MODERATION_SLA_MINUTES = 120  # 2 hours


# ═══════════════════════════════════════════════════════════════════
#  Audit log helper
# ═══════════════════════════════════════════════════════════════════

async def _audit(
    admin_id: str,
    action: str,
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """INSERT into admin_audit_log."""
    entry = AdminAuditLog(
        id=str(uuid4()),
        admin_id=admin_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        ip_address=ip_address,
    )
    db.add(entry)


async def log_audit(
    admin_id: str,
    action: str,
    entity_type: str | None,
    entity_id: str | None,
    db: AsyncSession,
) -> None:
    """Public audit logging for use by router endpoints."""
    await _audit(admin_id, action, db, entity_type=entity_type, entity_id=entity_id)


# ═══════════════════════════════════════════════════════════════════
#  Moderation queue
# ═══════════════════════════════════════════════════════════════════

async def get_moderation_queue(
    db: AsyncSession,
    status: str | None = None,
    sort: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Paginated moderation queue with seller history."""
    from app.services.admin.schemas import SellerHistory

    query = select(Listing).where(
        Listing.moderation_status.in_(["pending", "needs_review", "escalated"])
    )
    if status:
        query = query.where(Listing.moderation_status == status)

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Sort
    if sort == "risk_score_desc":
        query = query.order_by(Listing.moderation_score.desc().nullslast())
    else:
        # Default: wait_time_asc (oldest first)
        query = query.order_by(Listing.created_at.asc())

    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    listings = result.scalars().all()

    now = datetime.now(timezone.utc)
    items = []
    for lst in listings:
        # Load seller
        seller = await db.get(User, lst.seller_id)

        # Seller history: count past listings + rejection rate
        seller_total = (await db.execute(
            select(func.count()).where(Listing.seller_id == lst.seller_id)
        )).scalar() or 0
        seller_rejected = (await db.execute(
            select(func.count()).where(
                Listing.seller_id == lst.seller_id,
                Listing.moderation_status == "rejected",
            )
        )).scalar() or 0

        created = lst.created_at
        if created and hasattr(created, "tzinfo") and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        wait_minutes = int((now - created).total_seconds() / 60) if created else 0

        items.append({
            "id": str(lst.id),
            "title_en": lst.title_en,
            "title_ar": lst.title_ar,
            "seller_id": str(lst.seller_id),
            "seller_name": seller.full_name if seller else None,
            "moderation_score": float(lst.moderation_score) if lst.moderation_score else None,
            "moderation_status": lst.moderation_status,
            "moderation_flags": lst.moderation_flags,
            "wait_time_minutes": wait_minutes,
            "is_overdue": wait_minutes > MODERATION_SLA_MINUTES,
            "seller_ats": seller.ats_score if seller else 0,
            "seller_history": SellerHistory(
                past_listings_count=seller_total,
                rejection_rate=round(seller_rejected / seller_total, 2) if seller_total > 0 else 0.0,
            ),
            "created_at": created,
        })

    return {"items": items, "total": total, "page": page, "per_page": per_page}


async def approve_listing(
    listing_id: str,
    admin_id: str,
    notes: str | None,
    db: AsyncSession,
) -> Listing:
    """Approve a listing: moderation_status=approved, status=active."""
    listing = await db.get(Listing, listing_id)
    if not listing:
        return None

    before = {"moderation_status": listing.moderation_status, "status": listing.status}

    await _audit(
        admin_id, "moderation.approve", db,
        entity_type="listing", entity_id=listing_id,
        before_state=before,
        after_state={"moderation_status": "approved", "status": "active", "notes": notes},
    )

    listing.moderation_status = "approved"
    listing.status = "active"
    await db.commit()

    # Sync to Meilisearch
    try:
        from app.services.search.service import sync_listing_to_meilisearch
        await sync_listing_to_meilisearch(listing_id, db)
    except Exception:
        logger.warning("Meilisearch sync failed for listing %s", listing_id)

    # Notify seller
    try:
        from app.services.notification.service import queue_notification
        await queue_notification(
            str(listing.seller_id), "listing_approved", listing_id, "listing",
            {"title": listing.title_en}, db,
        )
    except Exception:
        logger.warning("Notification failed for listing approval %s", listing_id)

    return listing


async def reject_listing(
    listing_id: str,
    admin_id: str,
    reason: str,
    reason_ar: str,
    db: AsyncSession,
) -> Listing:
    """Reject a listing: moderation_status=rejected, status=draft."""
    listing = await db.get(Listing, listing_id)
    if not listing:
        return None

    before = {"moderation_status": listing.moderation_status, "status": listing.status}

    await _audit(
        admin_id, "moderation.reject", db,
        entity_type="listing", entity_id=listing_id,
        before_state=before,
        after_state={"moderation_status": "rejected", "status": "draft", "reason": reason},
    )

    listing.moderation_status = "rejected"
    listing.status = "draft"
    await db.commit()

    # Notify seller
    try:
        from app.services.notification.service import queue_notification
        await queue_notification(
            str(listing.seller_id), "listing_rejected", listing_id, "listing",
            {"title": listing.title_en, "reason": reason}, db,
        )
    except Exception:
        logger.warning("Notification failed for listing rejection %s", listing_id)

    return listing


async def require_edit_listing(
    listing_id: str,
    admin_id: str,
    required_changes: list[str],
    db: AsyncSession,
) -> Listing:
    """Require edits: moderation_status=needs_edit, status=draft."""
    listing = await db.get(Listing, listing_id)
    if not listing:
        return None

    before = {"moderation_status": listing.moderation_status, "status": listing.status}

    await _audit(
        admin_id, "moderation.require_edit", db,
        entity_type="listing", entity_id=listing_id,
        before_state=before,
        after_state={"moderation_status": "needs_edit", "required_changes": required_changes},
    )

    listing.moderation_status = "needs_edit"
    listing.status = "draft"
    await db.commit()

    # Notify seller with required changes
    try:
        from app.services.notification.service import queue_notification
        await queue_notification(
            str(listing.seller_id), "listing_rejected", listing_id, "listing",
            {"title": listing.title_en, "reason": "; ".join(required_changes)}, db,
        )
    except Exception:
        logger.warning("Notification failed for listing require-edit %s", listing_id)

    return listing


async def escalate_listing(
    listing_id: str,
    admin_id: str,
    reason: str,
    db: AsyncSession,
) -> Listing:
    """Escalate: moderation_status=escalated, notify superadmin."""
    listing = await db.get(Listing, listing_id)
    if not listing:
        return None

    before = {"moderation_status": listing.moderation_status}

    await _audit(
        admin_id, "moderation.escalate", db,
        entity_type="listing", entity_id=listing_id,
        before_state=before,
        after_state={"moderation_status": "escalated", "reason": reason},
    )

    listing.moderation_status = "escalated"
    await db.commit()

    # Notify superadmins
    try:
        from app.services.notification.service import queue_notification
        superadmins = (await db.execute(
            select(User).where(User.role == "superadmin")
        )).scalars().all()
        for sa in superadmins:
            await queue_notification(
                str(sa.id), "system_message", listing_id, "listing",
                {"message": f"Listing escalated: {reason}"}, db,
            )
    except Exception:
        logger.warning("Notification failed for listing escalation %s", listing_id)

    return listing


# ═══════════════════════════════════════════════════════════════════
#  Dispute queue
# ═══════════════════════════════════════════════════════════════════

async def get_dispute_queue(
    db: AsyncSession,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Paginated dispute queue sorted by wait time."""
    query = select(Dispute)

    if status == "open":
        query = query.where(Dispute.status == "open")
    elif status == "under_review":
        query = query.where(Dispute.status == "under_review")
    else:
        query = query.where(Dispute.status.in_(["open", "under_review"]))

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Sort by created_at ASC (longest waiting first)
    query = query.order_by(Dispute.created_at.asc())
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    disputes = result.scalars().all()

    now = datetime.now(timezone.utc)
    items = []
    for d in disputes:
        # Load escrow for amount
        escrow = await db.get(Escrow, d.escrow_id)

        created = d.created_at
        if created and hasattr(created, "tzinfo") and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        wait_minutes = int((now - created).total_seconds() / 60) if created else 0

        items.append({
            "id": str(d.id),
            "escrow_id": str(d.escrow_id),
            "buyer_id": str(d.buyer_id),
            "seller_id": str(d.seller_id),
            "reason": d.reason,
            "reason_detail": d.reason_detail,
            "status": d.status,
            "admin_id": str(d.admin_id) if d.admin_id else None,
            "buyer_evidence_count": d.buyer_evidence_count,
            "seller_evidence_count": d.seller_evidence_count,
            "escrow_amount": float(escrow.amount) if escrow else 0,
            "escrow_currency": escrow.currency if escrow else "JOD",
            "wait_time_minutes": wait_minutes,
            "created_at": created,
        })

    return {"items": items, "total": total, "page": page, "per_page": per_page}


async def assign_dispute(
    dispute_id: str,
    admin_id: str,
    assignee_id: str,
    db: AsyncSession,
) -> Dispute:
    """Assign a dispute to an admin and transition escrow to under_review."""
    dispute = await db.get(Dispute, dispute_id)
    if not dispute:
        return None

    before = {"admin_id": dispute.admin_id, "status": dispute.status}

    await _audit(
        admin_id, "dispute.assign", db,
        entity_type="dispute", entity_id=dispute_id,
        before_state=before,
        after_state={"admin_id": assignee_id},
    )

    dispute.admin_id = assignee_id
    if dispute.status == "open":
        dispute.status = "under_review"

    # Transition escrow to under_review if disputed
    escrow = await db.get(Escrow, dispute.escrow_id)
    if escrow and escrow.state in ("disputed",):
        try:
            from app.services.escrow.service import transition_escrow
            await transition_escrow(
                dispute.escrow_id, "under_review",
                assignee_id, "admin", "dispute_assigned",
                {"dispute_id": dispute_id}, db,
            )
        except Exception:
            logger.warning("Escrow transition to under_review failed for %s", dispute.escrow_id)

    await db.commit()
    return dispute


async def rule_dispute(
    dispute_id: str,
    admin_id: str,
    outcome: str,
    ruling_text: str,
    ruling_text_ar: str,
    split_ratio_buyer: int | None,
    db: AsyncSession,
) -> Dispute:
    """Rule on a dispute: transition escrow, trigger payout, notify parties."""
    dispute = await db.get(Dispute, dispute_id)
    if not dispute:
        return None

    # Validate split ratio
    if outcome == "resolved_split":
        if split_ratio_buyer is None:
            raise ValueError("split_ratio_buyer required for resolved_split")
        if not (0 <= split_ratio_buyer <= 100):
            raise ValueError("split_ratio_buyer must be 0-100")

    now = datetime.now(timezone.utc)
    before = {"status": dispute.status}

    await _audit(
        admin_id, "dispute.rule", db,
        entity_type="dispute", entity_id=dispute_id,
        before_state=before,
        after_state={
            "outcome": outcome, "ruling_text": ruling_text,
            "split_ratio_buyer": split_ratio_buyer,
        },
    )

    # Map outcome to dispute status
    status_map = {
        "resolved_released": "resolved_seller",
        "resolved_refunded": "resolved_buyer",
        "resolved_split": "resolved_split",
    }
    dispute.status = status_map[outcome]
    dispute.admin_ruling = ruling_text
    dispute.admin_ruled_at = now

    # Transition escrow
    escrow = await db.get(Escrow, dispute.escrow_id)
    if escrow:
        try:
            from app.services.escrow.service import transition_escrow
            await transition_escrow(
                dispute.escrow_id, outcome,
                admin_id, "admin", f"dispute_ruled_{outcome}",
                {"ruling": ruling_text, "dispute_id": dispute_id}, db,
            )
        except Exception:
            logger.warning("Escrow transition to %s failed for %s", outcome, dispute.escrow_id)

        # Trigger payout tasks
        try:
            if outcome == "resolved_released":
                from app.tasks.escrow import trigger_seller_payout
                trigger_seller_payout.delay(str(escrow.id))
            elif outcome == "resolved_refunded":
                from app.tasks.escrow import trigger_buyer_refund
                trigger_buyer_refund.delay(str(escrow.id))
            elif outcome == "resolved_split":
                from app.tasks.escrow import trigger_split_payout
                trigger_split_payout.delay(str(escrow.id), split_ratio_buyer)
        except Exception:
            logger.warning("Payout task dispatch failed for escrow %s", escrow.id)

    await db.commit()

    # Notify both parties
    try:
        from app.services.notification.service import queue_notification
        for user_id in (dispute.buyer_id, dispute.seller_id):
            await queue_notification(
                str(user_id), "dispute_resolved", dispute_id, "dispute",
                {"resolution": outcome, "amount": str(escrow.amount) if escrow else "0", "currency": "JOD"},
                db,
            )
    except Exception:
        logger.warning("Notification failed for dispute ruling %s", dispute_id)

    return dispute


# ═══════════════════════════════════════════════════════════════════
#  User management
# ═══════════════════════════════════════════════════════════════════

async def get_users(
    db: AsyncSession,
    phone: str | None = None,
    name: str | None = None,
    ats_min: int | None = None,
    ats_max: int | None = None,
    status: str | None = None,
    kyc_status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Search/filter user list with aggregated stats."""
    query = select(User)

    if phone:
        query = query.where(User.phone.ilike(f"%{phone}%"))
    if name:
        pattern = f"%{name}%"
        query = query.where(or_(
            User.full_name.ilike(pattern),
            User.full_name_ar.ilike(pattern),
        ))
    if ats_min is not None:
        query = query.where(User.ats_score >= ats_min)
    if ats_max is not None:
        query = query.where(User.ats_score <= ats_max)
    if status:
        query = query.where(User.status == status)
    if kyc_status:
        query = query.where(User.kyc_status == kyc_status)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(User.created_at.desc())
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    users = result.scalars().all()

    items = []
    for u in users:
        # Dispute count as buyer or seller
        dispute_count = (await db.execute(
            select(func.count()).where(
                or_(Dispute.buyer_id == u.id, Dispute.seller_id == u.id)
            )
        )).scalar() or 0

        # Total sales (released escrows as seller)
        total_sales = (await db.execute(
            select(func.coalesce(func.sum(Escrow.amount), 0)).where(
                Escrow.seller_id == u.id,
                Escrow.state.in_(["released", "resolved_released"]),
            )
        )).scalar() or 0

        items.append({
            "id": str(u.id),
            "phone": u.phone,
            "full_name": u.full_name,
            "full_name_ar": u.full_name_ar,
            "role": u.role if isinstance(u.role, str) else u.role.value,
            "status": u.status if isinstance(u.status, str) else u.status.value,
            "kyc_status": u.kyc_status if isinstance(u.kyc_status, str) else u.kyc_status.value,
            "ats_score": u.ats_score,
            "ats_breakdown": {
                "overall": u.ats_score,
                "identity": u.ats_identity_score,
                "completion": u.ats_completion_score,
                "speed": u.ats_speed_score,
                "rating": u.ats_rating_score,
                "quality": u.ats_quality_score,
                "dispute": u.ats_dispute_score,
            },
            "strike_count": u.strike_count,
            "dispute_count": dispute_count,
            "total_sales": float(total_sales),
            "created_at": u.created_at,
        })

    return {"items": items, "total": total, "page": page, "per_page": per_page}


async def get_user_detail(
    user_id: str,
    db: AsyncSession,
) -> dict | None:
    """Full user profile with KYC docs (pre-signed URLs) and audit history."""
    user = await db.get(User, user_id)
    if not user:
        return None

    # Dispute count
    dispute_count = (await db.execute(
        select(func.count()).where(
            or_(Dispute.buyer_id == user_id, Dispute.seller_id == user_id)
        )
    )).scalar() or 0

    total_sales = (await db.execute(
        select(func.coalesce(func.sum(Escrow.amount), 0)).where(
            Escrow.seller_id == user_id,
            Escrow.state.in_(["released", "resolved_released"]),
        )
    )).scalar() or 0

    user_data = {
        "id": str(user.id),
        "phone": user.phone,
        "full_name": user.full_name,
        "full_name_ar": user.full_name_ar,
        "role": user.role if isinstance(user.role, str) else user.role.value,
        "status": user.status if isinstance(user.status, str) else user.status.value,
        "kyc_status": user.kyc_status if isinstance(user.kyc_status, str) else user.kyc_status.value,
        "ats_score": user.ats_score,
        "ats_breakdown": {
            "overall": user.ats_score,
            "identity": user.ats_identity_score,
            "completion": user.ats_completion_score,
            "speed": user.ats_speed_score,
            "rating": user.ats_rating_score,
            "quality": user.ats_quality_score,
            "dispute": user.ats_dispute_score,
        },
        "strike_count": user.strike_count,
        "dispute_count": dispute_count,
        "total_sales": float(total_sales),
        "created_at": user.created_at,
    }

    # KYC documents with pre-signed S3 URLs
    kyc_docs = []
    from app.services.auth.models import UserKycDocument
    docs_result = await db.execute(
        select(UserKycDocument).where(UserKycDocument.user_id == user_id)
    )
    for doc in docs_result.scalars().all():
        s3_url = doc.s3_key  # In production, generate pre-signed URL
        try:
            from app.core.config import settings
            import boto3
            s3 = boto3.client(
                "s3",
                region_name=settings.AWS_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            s3_url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.S3_BUCKET_KYC, "Key": doc.s3_key},
                ExpiresIn=900,  # 15 min
            )
        except Exception:
            pass  # Fall back to raw key

        kyc_docs.append({
            "id": str(doc.id),
            "document_type": getattr(doc, "document_type", None),
            "s3_url": s3_url,
            "status": getattr(doc, "status", None),
            "uploaded_at": getattr(doc, "uploaded_at", None),
        })

    # Audit history for this user
    audit_result = await db.execute(
        select(AdminAuditLog)
        .where(AdminAuditLog.entity_id == user_id)
        .order_by(AdminAuditLog.created_at.desc())
        .limit(50)
    )
    audit_history = [
        {
            "id": str(a.id),
            "admin_id": str(a.admin_id),
            "action": a.action,
            "entity_type": a.entity_type,
            "entity_id": str(a.entity_id) if a.entity_id else None,
            "before_state": a.before_state,
            "after_state": a.after_state,
            "created_at": a.created_at,
        }
        for a in audit_result.scalars().all()
    ]

    return {
        "user": user_data,
        "kyc_documents": kyc_docs,
        "audit_history": audit_history,
    }


async def warn_user(
    user_id: str,
    admin_id: str,
    reason: str,
    db: AsyncSession,
) -> User | None:
    """Send warning notification and log."""
    user = await db.get(User, user_id)
    if not user:
        return None

    await _audit(
        admin_id, "user.warn", db,
        entity_type="user", entity_id=user_id,
        after_state={"reason": reason},
    )
    await db.commit()

    # Notify user
    try:
        from app.services.notification.service import queue_notification
        await queue_notification(
            user_id, "system_message", None, None,
            {"message": f"Warning: {reason}"}, db,
        )
    except Exception:
        logger.warning("Notification failed for user warning %s", user_id)

    return user


async def suspend_user(
    user_id: str,
    admin_id: str,
    reason: str,
    duration_hours: int,
    redis,
    db: AsyncSession,
) -> User | None:
    """Suspend user for duration_hours. Blacklist all JWTs."""
    user = await db.get(User, user_id)
    if not user:
        return None

    before = {"status": user.status if isinstance(user.status, str) else user.status.value}

    await _audit(
        admin_id, "user.suspend", db,
        entity_type="user", entity_id=user_id,
        before_state=before,
        after_state={"status": "suspended", "reason": reason, "duration_hours": duration_hours},
    )

    user.status = UserStatus.SUSPENDED
    await db.commit()

    # Blacklist all active JWTs
    ttl = duration_hours * 3600
    await redis.set(f"blacklist:user:{user_id}", "1", ex=ttl)

    # Notify user
    try:
        from app.services.notification.service import queue_notification
        await queue_notification(
            user_id, "system_message", None, None,
            {"message": f"Account suspended for {duration_hours}h: {reason}"}, db,
        )
    except Exception:
        logger.warning("Notification failed for user suspension %s", user_id)

    return user


async def ban_user(
    user_id: str,
    admin_id: str,
    reason: str,
    redis,
    db: AsyncSession,
) -> User | None:
    """Permanently ban user. Blacklist JWTs, cancel active listings."""
    user = await db.get(User, user_id)
    if not user:
        return None

    before = {"status": user.status if isinstance(user.status, str) else user.status.value}

    await _audit(
        admin_id, "user.ban", db,
        entity_type="user", entity_id=user_id,
        before_state=before,
        after_state={"status": "banned", "reason": reason},
    )

    user.status = UserStatus.BANNED
    await db.commit()

    # Permanent JWT blacklist (30 day TTL covers max token lifetime)
    await redis.set(f"blacklist:user:{user_id}", "1", ex=30 * 86400)

    # Cancel all active listings
    active_listings = (await db.execute(
        select(Listing).where(
            Listing.seller_id == user_id,
            Listing.status.in_(["active", "pending_review", "draft"]),
        )
    )).scalars().all()
    for lst in active_listings:
        lst.status = "cancelled"
    if active_listings:
        await db.commit()

    return user


async def restore_user(
    user_id: str,
    admin_id: str,
    reason: str,
    redis,
    db: AsyncSession,
) -> User | None:
    """Restore a suspended/banned user."""
    user = await db.get(User, user_id)
    if not user:
        return None

    before = {"status": user.status if isinstance(user.status, str) else user.status.value}

    await _audit(
        admin_id, "user.restore", db,
        entity_type="user", entity_id=user_id,
        before_state=before,
        after_state={"status": "active", "reason": reason},
    )

    user.status = UserStatus.ACTIVE
    await db.commit()

    # Remove blacklist keys
    await redis.delete(f"blacklist:user:{user_id}")

    return user


# ═══════════════════════════════════════════════════════════════════
#  Dashboard stats
# ═══════════════════════════════════════════════════════════════════

async def get_dashboard_stats(db: AsyncSession) -> dict:
    """Aggregate dashboard stats: last 24h / 7d / 30d windows."""
    from app.services.auction.models import Bid

    now = datetime.now(timezone.utc)
    h24 = now - timedelta(hours=24)

    # Active auctions (status = active or scheduled)
    active_auctions_count = (await db.execute(
        select(func.count(Auction.id)).where(Auction.status.in_(["active", "scheduled"]))
    )).scalar() or 0

    # Live auctions (status = active)
    live_auctions_count = (await db.execute(
        select(func.count(Auction.id)).where(Auction.status == "active")
    )).scalar() or 0

    # New users in 24h
    new_users_24h = (await db.execute(
        select(func.count(User.id)).where(User.created_at >= h24)
    )).scalar() or 0

    # KYC pending
    kyc_pending_count = (await db.execute(
        select(func.count(User.id)).where(
            User.kyc_status.in_(["pending", "pending_review"])
        )
    )).scalar() or 0

    # Moderation queue count
    moderation_queue_count = (await db.execute(
        select(func.count(Listing.id)).where(
            Listing.moderation_status.in_(["pending", "needs_review", "escalated"])
        )
    )).scalar() or 0

    # Open disputes
    disputes_open_count = (await db.execute(
        select(func.count(Dispute.id)).where(
            Dispute.status.in_(["open", "under_review"])
        )
    )).scalar() or 0

    # GMV 24h (sum of escrow.amount where state=released in last 24h)
    gmv_24h = (await db.execute(
        select(func.coalesce(func.sum(Escrow.amount), 0)).where(
            Escrow.state.in_(["released", "resolved_released"]),
            Escrow.updated_at >= h24,
        )
    )).scalar() or 0

    # Revenue 24h (5% platform commission on GMV)
    revenue_24h = float(gmv_24h) * 0.05

    # Average moderation wait time (items currently in queue)
    queue_listings = (await db.execute(
        select(Listing.created_at).where(
            Listing.moderation_status.in_(["pending", "needs_review", "escalated"])
        )
    )).scalars().all()
    if queue_listings:
        total_wait = sum(
            (now - (c.replace(tzinfo=timezone.utc) if c.tzinfo is None else c)).total_seconds() / 60
            for c in queue_listings
        )
        avg_moderation_wait = total_wait / len(queue_listings)
    else:
        avg_moderation_wait = 0.0

    # SLA breach count (moderation items > 2h)
    sla_breach_count = sum(
        1 for c in queue_listings
        if (now - (c.replace(tzinfo=timezone.utc) if c.tzinfo is None else c)).total_seconds() > MODERATION_SLA_MINUTES * 60
    )

    return {
        "active_auctions_count": active_auctions_count,
        "live_auctions_count": live_auctions_count,
        "new_users_24h": new_users_24h,
        "kyc_pending_count": kyc_pending_count,
        "moderation_queue_count": moderation_queue_count,
        "disputes_open_count": disputes_open_count,
        "gmv_24h": float(gmv_24h),
        "revenue_24h": revenue_24h,
        "avg_moderation_wait_time_minutes": round(avg_moderation_wait, 1),
        "sla_breach_count": sla_breach_count,
    }
