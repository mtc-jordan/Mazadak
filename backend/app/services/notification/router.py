"""Notification endpoints — SDD §5.7, FR-NOTIF-001 -> FR-NOTIF-012."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.auth.dependencies import get_current_user
from app.services.auth.models import User
from app.services.notification import schemas, service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/", response_model=schemas.NotificationListResponse)
async def list_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the authenticated user's notifications (newest first, max 50)."""
    notifications, unread_count = await service.get_user_notifications(user.id, db)
    return schemas.NotificationListResponse(
        data=[schemas.NotificationOut.model_validate(n) for n in notifications],
        unread_count=unread_count,
    )


@router.post("/read", status_code=204)
async def mark_read(
    body: schemas.MarkReadRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark one or more notifications as read."""
    await service.mark_as_read(body.notification_ids, user.id, db)


@router.get("/preferences", response_model=schemas.PreferenceOut)
async def get_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the authenticated user's notification channel preferences.

    Returns defaults (all enabled) if the user hasn't set preferences yet.
    """
    pref = await service.get_preferences(user.id, db)
    if pref is None:
        return schemas.PreferenceOut(
            push_enabled=True,
            sms_enabled=True,
            email_enabled=True,
            whatsapp_enabled=True,
        )
    return schemas.PreferenceOut.model_validate(pref)


@router.patch("/preferences", response_model=schemas.PreferenceOut)
async def update_preferences(
    body: schemas.PreferenceUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update notification channel preferences (partial update)."""
    updates = body.model_dump(exclude_none=True)
    pref = await service.update_preferences(user.id, updates, db)
    return schemas.PreferenceOut.model_validate(pref)
