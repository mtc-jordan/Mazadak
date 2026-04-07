"""Listing dependencies — ownership checks, status guards, bid-count guards."""

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.auth.dependencies import get_current_user, require_kyc_verified
from app.services.auth.models import User
from app.services.listing.models import Listing
from app.services.listing.service import get_listing


async def get_listing_or_404(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
) -> Listing:
    listing = await get_listing(listing_id, db)
    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "LISTING_NOT_FOUND", "message_en": "Listing not found"},
        )
    return listing


async def get_own_listing(
    listing: Listing = Depends(get_listing_or_404),
    user: User = Depends(require_kyc_verified),
) -> Listing:
    """Ensure the current user owns this listing."""
    if listing.seller_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "NOT_OWNER", "message_en": "You do not own this listing"},
        )
    return listing
