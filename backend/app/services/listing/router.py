"""Listing endpoints — SDD §5.3, FR-LIST-001 -> FR-LIST-013."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.core.database import get_db
from app.core.types import UUIDPath
from app.services.auth.dependencies import require_kyc, require_seller
from app.services.auth.models import User
from app.services.listing import schemas, service
from app.services.listing.dependencies import get_listing_or_404, get_own_listing
from app.services.listing.models import Listing, ListingStatus

router = APIRouter(prefix="/listings", tags=["listings"])


def _listing_to_response(
    listing: Listing,
    seller: User | None = None,
) -> schemas.ListingResponse:
    """Convert Listing ORM -> ListingResponse, with optional seller summary."""
    seller_summary = None
    if seller:
        seller_summary = schemas.SellerSummary(
            id=seller.id,
            full_name=seller.full_name,
            full_name_ar=seller.full_name_ar,
            ats_score=seller.ats_score,
            is_pro_seller=seller.is_pro_seller,
        )

    images = [
        schemas.ListingImageOut.model_validate(img)
        for img in (listing.images or [])
    ]

    return schemas.ListingResponse(
        id=listing.id,
        seller_id=listing.seller_id,
        seller=seller_summary,
        category_id=listing.category_id,
        title_ar=listing.title_ar,
        title_en=listing.title_en,
        description_ar=listing.description_ar,
        description_en=listing.description_en,
        condition=listing.condition,
        status=listing.status,
        is_certified=listing.is_certified,
        is_charity=listing.is_charity,
        ngo_id=listing.ngo_id,
        starting_price=listing.starting_price,
        reserve_price=listing.reserve_price,
        buy_it_now_price=listing.buy_it_now_price,
        current_price=listing.current_price,
        bid_count=listing.bid_count,
        watcher_count=listing.watcher_count,
        min_increment=listing.min_increment,
        starts_at=listing.starts_at,
        ends_at=listing.ends_at,
        ended_at=listing.ended_at,
        extension_count=listing.extension_count,
        location_city=listing.location_city,
        location_country=listing.location_country,
        ai_generated=listing.ai_generated,
        moderation_score=float(listing.moderation_score) if listing.moderation_score is not None else None,
        moderation_status=listing.moderation_status,
        phash=listing.phash,
        view_count=listing.view_count,
        images=images,
        created_at=listing.created_at,
        updated_at=listing.updated_at,
    )


# ── POST / — Create listing ────────────────────────────────────

@router.post("/", response_model=schemas.ListingResponse, status_code=201)
async def create_listing(
    body: schemas.CreateListingRequest,
    user: User = Depends(require_seller),
    db: AsyncSession = Depends(get_db),
):
    """Create a draft listing. Requires seller role + KYC. Free tier capped at 5."""
    try:
        listing = await service.create_listing(
            user.id, body, db,
            is_pro_seller=user.is_pro_seller,
        )
    except service.ListingLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "LISTING_LIMIT_REACHED",
                "message_en": str(exc),
                "message_ar": "تم الوصول للحد الأقصى من الإعلانات النشطة",
            },
        )
    return _listing_to_response(listing, seller=user)


# ── GET / — List with filters ──────────────────────────────────

@router.get("/", response_model=schemas.ListingListResponse)
async def list_listings(
    status_filter: str | None = Query(default=None, alias="status"),
    category_id: int | None = None,
    condition: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    seller_id: str | None = None,
    is_certified: bool | None = None,
    is_charity: bool | None = None,
    ends_before: datetime | None = None,
    sort: str | None = Query(
        default=None,
        pattern=r"^(ends_at_asc|price_asc|price_desc|bid_count_desc)$",
    ),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List listings with filters, sort, and pagination."""
    listings, total = await service.get_listings(
        db,
        status=status_filter,
        category_id=category_id,
        condition=condition,
        min_price=min_price,
        max_price=max_price,
        seller_id=seller_id,
        is_certified=is_certified,
        is_charity=is_charity,
        ends_before=ends_before,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return schemas.ListingListResponse(
        data=[_listing_to_response(lst) for lst in listings],
        total_count=total,
        limit=limit,
        offset=offset,
    )


# ── GET /mine — My listings grouped by status ─────────────────

@router.get("/mine", response_model=schemas.MyListingsResponse)
async def list_my_listings(
    user: User = Depends(require_kyc),
    db: AsyncSession = Depends(get_db),
):
    """Return the caller's listings grouped by status."""
    result = await db.execute(
        select(Listing).where(Listing.seller_id == user.id)
    )
    listings = result.scalars().all()

    groups: dict[str, list[schemas.ListingResponse]] = {
        "active": [],
        "ended": [],
        "draft": [],
        "pending": [],
        "cancelled": [],
    }
    for lst in listings:
        resp = _listing_to_response(lst, seller=user)
        if lst.status == ListingStatus.ACTIVE:
            groups["active"].append(resp)
        elif lst.status in (ListingStatus.ENDED, ListingStatus.RELISTED):
            groups["ended"].append(resp)
        elif lst.status == ListingStatus.DRAFT:
            groups["draft"].append(resp)
        elif lst.status == ListingStatus.PENDING_REVIEW:
            groups["pending"].append(resp)
        elif lst.status == ListingStatus.CANCELLED:
            groups["cancelled"].append(resp)

    return schemas.MyListingsResponse(**groups)


# ── GET /:id ───────────────────────────────────────────────────

@router.get("/{listing_id}", response_model=schemas.ListingResponse)
async def get_listing(
    listing: Listing = Depends(get_listing_or_404),
    db: AsyncSession = Depends(get_db),
):
    """Get a single listing by ID with seller summary."""
    seller = await db.get(User, listing.seller_id)
    return _listing_to_response(listing, seller=seller)


# ── PATCH /:id — Update listing ────────────────────────────────

@router.patch("/{listing_id}", response_model=schemas.ListingResponse)
async def update_listing(
    body: schemas.UpdateListingRequest,
    listing: Listing = Depends(get_own_listing),
    db: AsyncSession = Depends(get_db),
):
    """Update a draft/active listing. Blocked if bid_count > 0."""
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
                "message_en": "Only draft or active listings can be edited",
                "message_ar": "يمكن تعديل المسودات أو الإعلانات النشطة فقط",
            },
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message_en": str(exc)},
        )
    return _listing_to_response(updated)


# ── DELETE /:id ─────────────────────────────────────────────────

@router.delete("/{listing_id}", status_code=200)
async def delete_listing(
    listing: Listing = Depends(get_own_listing),
    db: AsyncSession = Depends(get_db),
):
    """Cancel/delete a listing. Blocked if bid_count > 0 or active."""
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
    except service.StatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_STATUS",
                "message_en": str(exc),
                "message_ar": "لا يمكن حذف إعلان نشط، استخدم 'إنهاء مبكر'",
            },
        )
    return {"success": True, "status": "cancelled"}


# ── POST /:id/images/request — Get presigned upload URLs ───────

@router.post(
    "/{listing_id}/images/request",
    response_model=schemas.ImageUploadResponse,
)
async def request_image_upload(
    body: schemas.ImageUploadRequest,
    listing: Listing = Depends(get_own_listing),
    db: AsyncSession = Depends(get_db),
):
    """Generate presigned S3 PUT URLs for image upload."""
    try:
        urls = await service.request_image_upload(
            listing.id, body.count, db,
            content_types=body.content_types,
        )
    except service.ImageLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "IMAGE_LIMIT_EXCEEDED",
                "message_en": str(exc),
                "message_ar": "تم تجاوز الحد الأقصى للصور",
            },
        )
    return schemas.ImageUploadResponse(
        upload_urls=[schemas.ImageUploadURL(**u) for u in urls],
        expires_in=900,
    )


# ── POST /:id/images/confirm — Confirm uploaded images ─────────

@router.post(
    "/{listing_id}/images/confirm",
    response_model=schemas.ImageConfirmResponse,
)
async def confirm_images(
    body: schemas.ImageConfirmRequest,
    listing: Listing = Depends(get_own_listing),
    db: AsyncSession = Depends(get_db),
):
    """Confirm uploaded images and queue processing."""
    try:
        confirmed = await service.confirm_images(listing.id, body.s3_keys, db)
    except service.ImageLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "IMAGE_LIMIT_EXCEEDED", "message_en": str(exc)},
        )
    except service.ImageNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "IMAGES_NOT_FOUND", "message_en": str(exc)},
        )
    return schemas.ImageConfirmResponse(confirmed=confirmed, processing=True)


# ── POST /:id/publish — Publish listing ────────────────────────

@router.post(
    "/{listing_id}/publish",
    response_model=schemas.PublishResponse,
)
async def publish_listing(
    listing: Listing = Depends(get_own_listing),
    db: AsyncSession = Depends(get_db),
):
    """Publish a draft listing. Runs AI moderation."""
    try:
        result = await service.publish_listing(listing, db)
    except service.StatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INVALID_STATUS",
                "message_en": str(exc),
                "message_ar": "لا يمكن نشر هذا الإعلان",
            },
        )
    return schemas.PublishResponse(
        id=result.id,
        status=result.status,
        moderation_score=float(result.moderation_score) if result.moderation_score is not None else None,
        moderation_status=result.moderation_status,
    )


# ── POST /:id/watch — Toggle watchlist ─────────────────────────

@router.post("/{listing_id}/watch", response_model=schemas.WatchResponse)
async def toggle_watch(
    listing: Listing = Depends(get_listing_or_404),
    user: User = Depends(require_kyc),
    db: AsyncSession = Depends(get_db),
):
    """Toggle watchlist for a listing."""
    watching, watcher_count = await service.toggle_watch(listing.id, user.id, db)
    return schemas.WatchResponse(
        listing_id=listing.id,
        watching=watching,
        watcher_count=watcher_count,
    )
