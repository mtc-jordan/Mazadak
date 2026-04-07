"""
Auction engine — SDD §3.2.

Core real-time component. Bid validation is atomic via Redis Lua.
PostgreSQL is the persistence layer (Celery async writes).
Redis Hash per auction stores real-time state with TTL = auction duration.
"""

import logging

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.auction.models import Auction, AuctionStatus, Bid

logger = logging.getLogger(__name__)

async def initialize_auction_in_redis(
    auction: Auction,
    seller_id: str,
    redis: Redis,
    ttl_seconds: int,
) -> None:
    """Push auction state to Redis when auction starts."""
    key = f"auction:{auction.id}"
    await redis.hset(key, mapping={
        "current_price": str(auction.current_price),
        "status": "ACTIVE",
        "seller_id": seller_id,
        "last_bidder": "",
        "bid_count": "0",
        "extension_count": "0",
        "watcher_count": "0",
        "min_increment": str(auction.min_increment),
    })
    await redis.expire(key, ttl_seconds)


async def place_bid(
    auction_id: str,
    user_id: str,
    amount: float,
    redis: Redis,
) -> tuple[str, str | None]:
    """Execute atomic bid via Lua script (EVALSHA).

    The Lua script reads min_increment from the Hash itself — no
    pre-fetch needed. Returns (status, reason):
      ('ACCEPTED', None) or ('REJECTED', 'BID_TOO_LOW').
    """
    from app.services.auction.lua_scripts import BidScript

    key = f"auction:{auction_id}"
    return await BidScript.execute(redis, key, user_id, amount)


async def persist_bid(
    auction_id: str,
    user_id: str,
    amount: float,
    currency: str,
    db: AsyncSession,
) -> Bid:
    """Write accepted bid to PostgreSQL (called async via Celery)."""
    bid = Bid(
        auction_id=auction_id,
        user_id=user_id,
        amount=amount,
        currency=currency,
    )
    db.add(bid)
    await db.commit()
    await db.refresh(bid)
    return bid


async def get_auction(auction_id: str, db: AsyncSession) -> Auction | None:
    return await db.get(Auction, auction_id)


async def end_auction(
    auction_id: str,
    redis: Redis,
    db: AsyncSession,
) -> Auction | None:
    """Sync final state from Redis → PostgreSQL, set winner."""
    key = f"auction:{auction_id}"
    state = await redis.hgetall(key)
    if not state:
        return None

    auction = await db.get(Auction, auction_id)
    if not auction:
        return None

    auction.status = AuctionStatus.ENDED
    auction.current_price = float(state.get("current_price", 0))
    auction.bid_count = int(state.get("bid_count", 0))
    auction.extension_count = int(state.get("extension_count", 0))
    auction.final_price = float(state.get("current_price", 0))
    auction.winner_id = state.get("last_bidder") or None

    await db.commit()
    await db.refresh(auction)
    await redis.delete(key)
    return auction


async def read_auction_state(auction_id: str, redis: Redis) -> dict[str, str] | None:
    """Read full auction state from Redis Hash. Returns None if key missing."""
    key = f"auction:{auction_id}"
    state = await redis.hgetall(key)
    return state if state else None


async def check_anti_snipe(auction_id: str, redis: Redis) -> bool:
    """Anti-snipe extension — SDD §3.2.1.

    After every accepted bid, check if TTL <= ANTI_SNIPE_WINDOW_SECONDS.
    If so, extend TTL by ANTI_SNIPE_EXTENSION_SECONDS and increment
    extension_count. Respects MAX_ANTI_SNIPE_EXTENSIONS cap.

    Returns True if extension was applied, False otherwise.
    """
    key = f"auction:{auction_id}"
    current_ttl = await redis.ttl(key)

    # Key missing or no expiry set
    if current_ttl < 0:
        return False

    if current_ttl > settings.ANTI_SNIPE_WINDOW_SECONDS:
        return False

    # Check extension cap
    ext_count = int(await redis.hget(key, "extension_count") or "0")
    if ext_count >= settings.MAX_ANTI_SNIPE_EXTENSIONS:
        logger.info(
            "Anti-snipe cap reached (%d/%d) for auction=%s",
            ext_count, settings.MAX_ANTI_SNIPE_EXTENSIONS, auction_id,
        )
        return False

    # Extend TTL and increment counter
    new_ttl = current_ttl + settings.ANTI_SNIPE_EXTENSION_SECONDS
    await redis.expire(key, new_ttl)
    await redis.hincrby(key, "extension_count", 1)

    logger.info(
        "Anti-snipe extended auction=%s by %ds (TTL %d→%d, ext #%d)",
        auction_id,
        settings.ANTI_SNIPE_EXTENSION_SECONDS,
        current_ttl,
        new_ttl,
        ext_count + 1,
    )
    return True
