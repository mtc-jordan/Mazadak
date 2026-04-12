"""B2B Tender Rooms FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.types import UUIDPath
from app.services.auth.dependencies import get_current_user
from app.services.auth.models import User
from app.services.b2b.models import B2BInvitation, B2BRoom
from app.services.b2b.service import check_access, get_room


async def get_tender_or_404(
    tender_id: UUIDPath,
    db: AsyncSession = Depends(get_db),
) -> B2BRoom:
    room = await get_room(tender_id, db)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TENDER_NOT_FOUND",
                "message_en": "Tender room not found",
                "message_ar": "غرفة المناقصة غير موجودة",
            },
        )
    return room


async def require_tender_access(
    room: B2BRoom = Depends(get_tender_or_404),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[B2BRoom, User, B2BInvitation]:
    """Ensure the user is invited and pre-qualified for this room.

    Returns (room, user, invitation) tuple for use by downstream endpoints.
    """
    invitation = await check_access(room, user, db)
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "TENDER_ACCESS_DENIED",
                "message_en": "You are not invited to this tender room",
                "message_ar": "أنت غير مدعو إلى غرفة المناقصة هذه",
            },
        )
    return room, user, invitation
