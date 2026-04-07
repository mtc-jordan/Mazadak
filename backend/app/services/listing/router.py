"""Listing endpoints — SDD §5.3, FR-LIST-001 → FR-LIST-013."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.auth.dependencies import require_kyc_verified
from app.services.auth.models import User
from app.services.listing import schemas, service
from app.services.listing.dependencies import get_listing_or_404, get_own_listing
from app.services.listing.models import Listing, get_image_urls

router = APIRouter(prefix="/listings", tags=["listings"])


def _listing_to_out(listing: Listing) -> schemas.ListingOut:
    """Convert Listing ORM → ListingOut, deserialising image_urls JSON."""
    data = {
        "id": listing.id,
        "seller_id": listing.seller_id,
        "title_ar": listing.title_ar,
        "title_en": listing.title_en,
        "description_ar": listing.description_ar,
        "description_en": listing.description_en,
        "category_id": listing.category_id,
        "condition": listing.condition,
        "starting_price": float(listing.starting_price),
        "reserve_price": float(listing.reserve_price) if listing.reserve_price is not None else None,
        "buy_it_now_price": float(listing.buy_it_now_price) if listing.buy_it_now_price is not None else None,
        "listing_currency": listing.listing_currency,
        "duration_hours": listing.duration_hours,
        "status": listing.status,
        "ai_generated": listing.ai_generated,
        "ai_price_low": float(listing.ai_price_low) if listing.ai_price_low is not None else None,
        "ai_price_high": float(listing.ai_price_high) if listing.ai_price_high is not None else None,
        "phash": listing.phash,
        "moderation_score": listing.moderation_score,
        "is_charity": listing.is_charity,
        "image_urls": get_image_urls(listing),
        "bid_count": listing.bid_count,
        "published_at": listing.published_at,
    }
    return schemas.ListingOut(**data)


# ── POST / — Create listing ───────────────────────────────────

@router.post("/", response_model=schemas.ListingOut, status_code=201)
async def create_listing(
    body: schemas.ListingCreateRequest,
    user: User = Depends(require_kyc_verified),
    db: AsyncSession = Depends(get_db),
):
    """Create a draft listing.

    FR-LIST-001: Full validation (title_ar required, duration 1h-7d,
    reserve >= starting, max 5 active for Free tier).
    """
    try:
        listing = await service.create_listing(user.id, body, db)
    except service.ListingLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "LISTING_LIMIT_REACHED",
                "message_en": str(exc),
                "message_ar": "تم الوصول للحد الأقصى من الإعلانات النشطة",
            },
        )
    return _listing_to_out(listing)


# ── GET / — List with filters ─────────────────────────────────

@router.get("/", response_model=schemas.ListingListResponse)
async def list_listings(
    status_filter: str | None = Query(default=None, alias="status"),
    category_id: int | None = None,
    condition: str | None = None,
    currency: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    seller_id: str | None = None,
    sort_by: str | None = Query(default=None, pattern=r"^(price_asc|price_desc|newest)$"),
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    listings, total = await service.list_listings(
        db,
        status=status_filter,
        category_id=category_id,
        condition=condition,
        currency=currency,
        min_price=min_price,
        max_price=max_price,
        seller_id=seller_id,
        sort_by=sort_by,
        cursor=cursor,
        limit=limit,
    )
    next_cursor = listings[-1].id if listings else None
    return schemas.ListingListResponse(
        data=[_listing_to_out(l) for l in listings],
        next_cursor=next_cursor,
        total_count=total,
    )


# ── GET /:id ──────────────────────────────────────────────────

@router.get("/{listing_id}", response_model=schemas.ListingOut)
async def get_listing(listing: Listing = Depends(get_listing_or_404)):
    return _listing_to_out(listing)


# ── PATCH /:id — Update listing ──────────────────────────────

@router.patch("/{listing_id}", response_model=schemas.ListingOut)
async def update_listing(
    body: schemas.ListingUpdateRequest,
    listing: Listing = Depends(get_own_listing),
    db: AsyncSession = Depends(get_db),
):
    """Update a draft listing. Blocked if bid_count > 0."""
    try:
        updated = await service.update_listing(listing, body, db)
    except service.BidCountError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "HAS_BIDS",
                "message_en": "Cannot edit listing with active bids",
                "message_ar": "لا يمكن تعديل الإعلان بعد وجود مزايدات",
            },
        )
    except service.StatusError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INVALID_STATUS",
                "message_en": "Only draft listings can be edited",
                "message_ar": "يمكن تعديل المسودات فقط",
            },
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message_en": str(exc)},
        )
    return _listing_to_out(updated)


# ── DELETE /:id ───────────────────────────────────────────────

@router.delete("/{listing_id}", status_code=200)
async def delete_listing(
    listing: Listing = Depends(get_own_listing),
    db: AsyncSession = Depends(get_db),
):
    """Cancel/delete a listing. Blocked if bid_count > 0."""
    try:
        await service.delete_listing(listing, db)
    except service.BidCountError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "HAS_BIDS",
                "message_en": "Cannot delete listing with active bids",
                "message_ar": "لا يمكن حذف الإعلان بعد وجود مزايدات",
            },
        )
    return {"success": True, "status": "cancelled"}


# ── POST /:id/submit — Submit for moderation ─────────────────

@router.post("/{listing_id}/submit", response_model=schemas.ListingOut)
async def submit_listing(
    listing: Listing = Depends(get_own_listing),
    db: AsyncSession = Depends(get_db),
):
    """Submit listing for AI moderation → active or moderation queue."""
    try:
        result = await service.submit_for_moderation(listing, db)
    except service.StatusError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INVALID_STATUS",
                "message_en": "Only draft listings can be submitted",
            },
        )
    return _listing_to_out(result)


# ── POST /:id/images — Get presigned upload URLs ─────────────

@router.post(
    "/{listing_id}/images",
    response_model=schemas.ImageUploadResponse,
)
async def get_upload_urls(
    body: schemas.ImageUploadRequest,
    listing: Listing = Depends(get_own_listing),
):
    """Generate S3 presigned upload URLs for listing images."""
    urls = service.generate_upload_urls(listing.id, body.count)
    return schemas.ImageUploadResponse(
        upload_urls=[schemas.ImageUploadURL(**u) for u in urls],
    )
