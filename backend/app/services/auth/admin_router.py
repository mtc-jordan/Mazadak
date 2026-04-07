"""Admin KYC review endpoints — FR-AUTH-005, PM-02 Steps 9-12."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.auth import schemas
from app.services.auth import kyc_service
from app.services.auth.dependencies import require_role
from app.services.auth.models import User

router = APIRouter(prefix="/admin/kyc", tags=["admin-kyc"])


@router.get(
    "/queue",
    response_model=list[schemas.KYCQueueItem],
)
async def get_kyc_queue(
    user: User = Depends(require_role("admin", "super_admin", "moderator")),
    db: AsyncSession = Depends(get_db),
):
    """Get all KYC submissions pending manual review.

    PM-02: Manual reviewer sees documents for confidence 70-84%
    or when Rekognition was unavailable.
    """
    items = await kyc_service.get_pending_reviews(db)
    return items


@router.post(
    "/{user_id}/approve",
    status_code=status.HTTP_200_OK,
)
async def approve_kyc(
    user_id: str,
    admin: User = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Approve a user's KYC — sets status to KYC_VERIFIED.

    PM-02 Step 11: KYC_VERIFIED based on reviewer decision.
    Triggers notification Celery task.
    """
    success = await kyc_service.review_kyc(
        user_id=user_id,
        decision="approve",
        reason="",
        reviewer_id=admin.id,
        db=db,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NO_PENDING_REVIEW",
                "message_en": "No pending KYC review found for this user",
            },
        )

    # Fire Celery notification task
    try:
        from app.tasks.kyc import notify_kyc_outcome
        notify_kyc_outcome.delay(user_id, "approved")
    except Exception:
        pass  # Non-critical — notification is best-effort

    return {"success": True, "status": "verified"}


@router.post(
    "/{user_id}/reject",
    status_code=status.HTTP_200_OK,
)
async def reject_kyc(
    user_id: str,
    body: schemas.KYCReviewRequest,
    admin: User = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Reject a user's KYC — sets status to REJECTED with reason.

    PM-02 Step 11: KYC_REJECTED based on reviewer decision.
    PM-02: User notified via push + WhatsApp with rejection reason.
    """
    success = await kyc_service.review_kyc(
        user_id=user_id,
        decision="reject",
        reason=body.reason,
        reviewer_id=admin.id,
        db=db,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NO_PENDING_REVIEW",
                "message_en": "No pending KYC review found for this user",
            },
        )

    try:
        from app.tasks.kyc import notify_kyc_outcome
        notify_kyc_outcome.delay(user_id, "rejected", body.reason)
    except Exception:
        pass

    return {"success": True, "status": "rejected"}
