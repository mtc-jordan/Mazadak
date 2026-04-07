"""Auction endpoints — SDD §5.4."""

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.services.auth.dependencies import get_current_user
from app.services.auth.models import User
from app.services.auction import schemas, service
from app.services.auction.dependencies import check_bid_rate_limit, get_auction_or_404
from app.services.auction.models import Auction

router = APIRouter(prefix="/auctions", tags=["auctions"])


@router.get("/{auction_id}", response_model=schemas.AuctionOut)
async def get_auction(auction: Auction = Depends(get_auction_or_404)):
    return auction


@router.post("/{auction_id}/bids", status_code=201)
async def place_bid(
    auction_id: str,
    body: schemas.PlaceBidRequest,
    user: User = Depends(check_bid_rate_limit),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Place a bid — atomic validation via Redis Lua."""
    bid_status, reason = await service.place_bid(
        auction_id, user.id, body.amount, redis,
    )
    if bid_status == "REJECTED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": reason, "message_en": f"Bid rejected: {reason}"},
        )

    # Anti-snipe check after accepted bid
    await service.check_anti_snipe(auction_id, redis)

    bid = await service.persist_bid(
        auction_id, user.id, body.amount, "JOD", db,
    )
    new_price = body.amount
    return schemas.BidAcceptedResponse(
        status="ACCEPTED",
        bid=schemas.BidOut.model_validate(bid),
        new_price=new_price,
    )


@router.post("/{auction_id}/proxy-bids", response_model=schemas.BidOut, status_code=201)
async def set_proxy_bid(
    auction_id: str,
    body: schemas.ProxyBidRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set a maximum proxy bid — system bids on user's behalf."""
    # TODO: Implement proxy bid engine
    raise HTTPException(status_code=501, detail="Proxy bidding not yet implemented")


@router.get("/{auction_id}/bids", response_model=list[schemas.BidOut])
async def list_bids(
    auction_id: str,
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
