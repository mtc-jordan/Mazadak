"""AI service dependencies."""

from fastapi import Depends

from app.services.auth.dependencies import get_current_user, require_kyc_verified
from app.services.auth.models import User


async def get_ai_user(
    user: User = Depends(get_current_user),
) -> User:
    """Authenticated user for AI endpoints."""
    return user
