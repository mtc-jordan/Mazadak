"""Auction dependencies — auction lookup, bid rate limiting."""

from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.services.auth.dependencies import get_current_user
from app.services.auth.models import User
from app.services.auction.models import Auction
from app.services.auction.service import get_auction


async def get_auction_or_404(
    auction_id: str,
    db: AsyncSession = Depends(get_db),
) -> Auction:
    auction = await get_auction(auction_id, db)
    if not auction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "AUCTION_NOT_FOUND", "message_en": "Auction not found"},
        )
    return auction


async def check_bid_rate_limit(
    auction_id: str,
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> User:
    """Enforce max bids per user per auction per minute (SDD §4.3)."""
    key = f"rate:bid:{user.id}:{auction_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    if count > settings.RATE_LIMIT_BID_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "BID_RATE_LIMITED", "message_en": "Too many bids, slow down"},
        )
    return user
