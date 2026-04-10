"""Auction endpoints — SDD §5.4."""

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select, or_

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.types import UUIDPath
from app.services.auth.dependencies import get_current_user
from app.services.auth.models import User
from app.services.auction import schemas, service
from app.services.auction.dependencies import check_bid_rate_limit, get_auction_or_404
from app.services.auction.models import Auction, AuctionStatus
from app.services.listing.models import Listing

router = APIRouter(prefix="/auctions", tags=["auctions"])


# ── GET /mine — My auctions (seller + won) ────────────────────

@router.get("/mine", response_model=schemas.MyAuctionsResponse)
async def list_my_auctions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return auctions where the caller is seller or winner, grouped."""
    # Fetch auctions where user is seller (via listing) or winner
    result = await db.execute(
        select(Auction, Listing)
        .join(Listing, Auction.listing_id == Listing.id)
        .where(
            or_(
                Listing.seller_id == user.id,
                Auction.winner_id == user.id,
            )
        )
    )
    rows = result.all()

    active: list[schemas.MyAuctionItem] = []
    ended: list[schemas.MyAuctionItem] = []
    won: list[schemas.MyAuctionItem] = []

    for auction, listing in rows:
        # Pick first image URL if available
        image_url = ""
        if listing.images:
            image_url = listing.images[0].s3_key

        item = schemas.MyAuctionItem(
            id=auction.id,
            listing_id=auction.listing_id,
            title_ar=listing.title_ar,
            title_en=listing.title_en,
            image_url=image_url,
            starting_price=float(listing.starting_price),
            current_price=float(auction.current_price),
            currency="JOD",
            bid_count=auction.bid_count,
            status=auction.status if isinstance(auction.status, str) else auction.status.value,
            ends_at=auction.ends_at,
            winner_name=None,
            is_live=auction.status == AuctionStatus.ACTIVE,
        )

        # Categorise
        if auction.winner_id == user.id:
            won.append(item)
        if listing.seller_id == user.id:
            if auction.status == AuctionStatus.ACTIVE:
                active.append(item)
            elif auction.status == AuctionStatus.ENDED:
                ended.append(item)

    return schemas.MyAuctionsResponse(active=active, ended=ended, won=won)


@router.get("/{auction_id}", response_model=schemas.AuctionOut)
async def get_auction(auction: Auction = Depends(get_auction_or_404)):
    return auction


@router.post("/{auction_id}/bids", status_code=201)
async def place_bid(
    auction_id: UUIDPath,
    body: schemas.PlaceBidRequest,
    user: User = Depends(check_bid_rate_limit),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Place a bid — atomic validation via Redis Lua."""
    amount = int(body.amount)

    result = await service.place_bid(auction_id, user.id, amount, redis)
    if not result.accepted:
        detail = {
            "code": result.rejection_reason,
            "message_en": f"Bid rejected: {result.rejection_reason}",
        }
        if result.min_required is not None:
            detail["min_required"] = result.min_required
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )

    bid = await service.persist_bid(
        auction_id, user.id, amount, "JOD", db,
    )

    # Trigger proxy bid engine — competing proxy bids counter automatically
    proxy_bid = await service.execute_proxy_bids(
        auction_id, user.id, amount, redis, db,
    )
    new_price = int(proxy_bid.amount) if proxy_bid else result.new_price

    return schemas.BidAcceptedResponse(
        status="ACCEPTED",
        bid=schemas.BidOut.model_validate(bid),
        new_price=new_price,
    )


@router.post("/{auction_id}/proxy-bids", status_code=201)
async def set_proxy_bid(
    auction_id: UUIDPath,
    body: schemas.ProxyBidRequest,
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Set a maximum proxy bid — system bids on user's behalf.

    The proxy engine places the minimum necessary bid (current_price + min_increment)
    whenever someone else bids, up to the user's max_amount.
    """
    from sqlalchemy import select, update
    from app.services.auction.models import ProxyBid

    auction = await service.get_auction(auction_id, db)
    if not auction:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "AUCTION_NOT_FOUND",
                "message_en": "Auction not found",
                "message_ar": "المزاد غير موجود",
            },
        )

    if auction.status != "active":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "AUCTION_NOT_ACTIVE",
                "message_en": "Auction is not active",
                "message_ar": "المزاد غير نشط",
            },
        )

    if body.max_amount <= float(auction.current_price):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MAX_BELOW_CURRENT",
                "message_en": "Max amount must exceed current price",
                "message_ar": "الحد الأقصى يجب أن يتجاوز السعر الحالي",
            },
        )

    # Deactivate any existing proxy bid for this user/auction
    await db.execute(
        update(ProxyBid)
        .where(
            ProxyBid.auction_id == auction_id,
            ProxyBid.user_id == user.id,
            ProxyBid.is_active.is_(True),
        )
        .values(is_active=False)
    )

    # Create new proxy bid
    proxy = ProxyBid(
        auction_id=auction_id,
        user_id=user.id,
        max_amount=body.max_amount,
        is_active=True,
    )
    db.add(proxy)
    await db.commit()
    await db.refresh(proxy)

    # Immediately place a bid at current_price + min_increment if competitive
    next_bid = int(auction.current_price) + int(auction.min_increment)
    if next_bid <= int(body.max_amount):
        result = await service.place_bid(auction_id, user.id, next_bid, redis)
        if result.accepted:
            bid = await service.persist_bid(
                auction_id, user.id, next_bid, "JOD", db,
            )
            bid.is_proxy = True
            await db.commit()

    return {
        "data": {
            "id": proxy.id,
            "auction_id": auction_id,
            "max_amount": float(proxy.max_amount),
            "is_active": proxy.is_active,
        },
        "message": "Proxy bid set successfully",
        "success": True,
    }


@router.get("/{auction_id}/bids", response_model=list[schemas.BidOut])
async def list_bids(
    auction_id: UUIDPath,
    db: AsyncSession = Depends(get_db),
):
    """List bid history for an auction."""
    from sqlalchemy import select
    from app.services.auction.models import Bid
    result = await db.execute(
        select(Bid)
        .where(Bid.auction_id == auction_id)
        .order_by(Bid.created_at.desc())
        .limit(100)
    )
    return [schemas.BidOut.model_validate(b) for b in result.scalars().all()]
