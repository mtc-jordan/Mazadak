"""Notification dependencies."""

from fastapi import Depends

from app.services.auth.dependencies import get_current_user
from app.services.auth.models import User


async def get_notification_user(
    user: User = Depends(get_current_user),
) -> User:
    """Authenticated user for notification endpoints."""
    return user
