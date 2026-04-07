"""Notification endpoints."""

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
    await service.mark_as_read(body.notification_ids, user.id, db)
