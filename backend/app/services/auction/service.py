"""
Auction engine — SDD §3.2.

Core real-time component.  Bid validation is atomic via Redis Lua.
PostgreSQL is the persistence layer (Celery async writes).

Redis key schema (individual keys per auction):
  auction:{id}:price         → current bid (integer cents)
  auction:{id}:status        → ACTIVE | ENDED | CANCELLED
  auction:{id}:seller        → seller_id string
  auction:{id}:last_bidder   → last bidder user_id
  auction:{id}:bid_count     → integer
  auction:{id}:extension_ct  → anti-snipe extension count
  auction:{id}:watcher_ct    → current watcher count
  auction:{id}:min_increment → minimum increment (integer cents)
  auction:{id}:reserve       → reserve price or 0
  auction:{id}:banned_set    → SET of banned user_ids
  auction:{id}               → "active" with TTL = seconds until ends_at
                                (root key triggers keyspace expiry notification)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.auction.models import Auction, AuctionStatus, Bid

logger = logging.getLogger(__name__)


# ── Key helpers ────────────────────────────────────────────────

def _k(auction_id: str | UUID, suffix: str) -> str:
    """Build Redis key for an auction field."""
    return f"auction:{auction_id}:{suffix}"


def _root(auction_id: str | UUID) -> str:
    """Root key with TTL for keyspace expiry."""
    return f"auction:{auction_id}"


ALL_SUFFIXES = (
    "price", "status", "seller", "last_bidder", "bid_count",
    "extension_ct", "watcher_ct", "min_increment", "reserve",
    "banned_set",
)


# ── Initialize auction in Redis ────────────────────────────────

async def initialize_auction(
    auction_id: UUID,
    listing_id: UUID,
    db: AsyncSession,
    redis: Redis,
) -> dict:
    """Push auction state to Redis when auction starts.

    Celery task — triggered at starts_at via apply_async(eta=starts_at).

    Steps:
    1. Load listing + auction from DB
    2. Verify auction.status == 'scheduled' (idempotency)
    3. Calculate TTL; if negative → mark ended, return early
    4. Atomic Redis pipeline sets all individual keys
    5. UPDATE auction + listing status in DB
    6. Sync to Meilisearch, notify watchers
    """
    from app.services.listing.models import Listing

    aid = str(auction_id)

    # 1. Load from DB
    auction = await db.get(Auction, aid)
    if not auction:
        logger.error("initialize_auction: auction %s not found", aid)
        return {"status": "error", "reason": "not_found"}

    listing = await db.get(Listing, str(listing_id))
    if not listing:
        logger.error("initialize_auction: listing %s not found", listing_id)
        return {"status": "error", "reason": "listing_not_found"}

    # 2. Idempotency: skip if already active or ended
    if auction.status in (AuctionStatus.ACTIVE.value, AuctionStatus.ACTIVE):
        logger.info("initialize_auction: %s already active, skipping", aid)
        return {"status": "skipped", "reason": "already_active"}
    if auction.status not in (AuctionStatus.SCHEDULED.value, AuctionStatus.SCHEDULED):
        logger.info("initialize_auction: %s status=%s, skipping", aid, auction.status)
        return {"status": "skipped", "reason": f"wrong_status:{auction.status}"}

    # 3. Calculate TTL
    ends_at = datetime.fromisoformat(str(auction.ends_at))
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    ttl = int((ends_at - now).total_seconds())

    if ttl <= 0:
        # Already past end time — mark as ended
        auction.status = AuctionStatus.ENDED.value
        listing.status = "ended"
        listing.ended_at = now
        await db.commit()
        logger.warning("initialize_auction: %s TTL=%d, marked ended", aid, ttl)
        return {"status": "ended", "reason": "past_ends_at", "ttl": ttl}

    # 4. Atomic Redis pipeline — individual keys
    pipe = redis.pipeline(transaction=True)
    pipe.set(_k(aid, "price"), str(listing.starting_price))
    pipe.set(_k(aid, "status"), "ACTIVE")
    pipe.set(_k(aid, "seller"), str(listing.seller_id))
    pipe.set(_k(aid, "last_bidder"), "")
    pipe.set(_k(aid, "bid_count"), "0")
    pipe.set(_k(aid, "extension_ct"), "0")
    pipe.set(_k(aid, "watcher_ct"), "0")
    pipe.set(_k(aid, "min_increment"), str(listing.min_increment))
    pipe.set(_k(aid, "reserve"), str(listing.reserve_price or 0))
    # Root key with TTL — keyspace notification fires on expiry
    pipe.set(_root(aid), "active", ex=ttl)
    await pipe.execute()

    # 5. Update DB state
    auction.status = AuctionStatus.ACTIVE.value
    auction.redis_synced_at = now.isoformat()
    listing.status = "active"
    await db.commit()

    # 6. Async: sync to Meilisearch
    try:
        from app.tasks.listing import sync_listing_to_meilisearch
        sync_listing_to_meilisearch.delay(str(listing_id))
    except Exception:
        logger.warning("Failed to queue Meilisearch sync for listing %s", listing_id)

    # 7. Notify watchers: auction started
    try:
        from app.tasks.notification import send_notification
        send_notification.delay(
            event="auction_started",
            listing_id=str(listing_id),
            auction_id=aid,
            data={"ttl_seconds": ttl},
        )
    except Exception:
        logger.warning("Failed to queue auction_started notification for %s", aid)

    logger.info(
        "Auction initialized: auction=%s listing=%s ttl=%ds",
        aid, listing_id, ttl,
    )
    return {
        "status": "initialized",
        "auction_id": aid,
        "listing_id": str(listing_id),
        "ttl_seconds": ttl,
        "redis_initialized_at": now.isoformat(),
    }


# ── Handle auction expiry ──────────────────────────────────────

async def handle_auction_expiry(
    auction_id: str,
    redis: Redis,
    db: AsyncSession,
) -> dict:
    """Handle auction end on Redis key expiry.

    Triggered by keyspace notification when root key expires.

    Steps:
    1. Fetch final state from Redis (individual keys persist after root expires)
    2. Idempotency check
    3. Read final values + check reserve price
    4. DB transaction: update auction, listing, create escrow if winner
    5. Publish ended event via Redis Pub/Sub
    6. Send notifications, queue ATS score update
    7. Cleanup Redis keys
    """
    from app.services.listing.models import Listing

    # 1. Read final state from Redis
    final_price = await redis.get(_k(auction_id, "price"))
    status = await redis.get(_k(auction_id, "status"))
    last_bidder = await redis.get(_k(auction_id, "last_bidder"))
    bid_count_str = await redis.get(_k(auction_id, "bid_count"))
    extension_ct_str = await redis.get(_k(auction_id, "extension_ct"))
    seller_id = await redis.get(_k(auction_id, "seller"))
    reserve_str = await redis.get(_k(auction_id, "reserve"))

    bid_count = int(bid_count_str) if bid_count_str else 0
    extension_count = int(extension_ct_str) if extension_ct_str else 0
    reserve_price = int(reserve_str) if reserve_str else 0
    price = int(final_price) if final_price else 0

    # 2. Idempotency
    if status == "ENDED":
        logger.info("handle_auction_expiry: %s already ENDED, skipping", auction_id)
        return {"status": "skipped", "reason": "already_ended"}

    # Mark as ENDED in Redis immediately (prevent re-entry)
    await redis.set(_k(auction_id, "status"), "ENDED")

    # Load DB records
    auction = await db.get(Auction, auction_id)
    if not auction:
        logger.error("handle_auction_expiry: auction %s not found", auction_id)
        await _cleanup_redis_keys(auction_id, redis)
        return {"status": "error", "reason": "not_found"}

    if auction.status == AuctionStatus.ENDED.value:
        logger.info("handle_auction_expiry: %s already ended in DB", auction_id)
        await _cleanup_redis_keys(auction_id, redis)
        return {"status": "skipped", "reason": "already_ended_db"}

    listing = await db.get(Listing, auction.listing_id)

    # 3. Determine outcome
    winner_id = None
    outcome = "no_bids"

    if bid_count == 0:
        outcome = "no_bids"
    elif reserve_price > 0 and price < reserve_price:
        outcome = "reserve_not_met"
        auction.reserve_met = False
    else:
        winner_id = last_bidder if last_bidder else None
        outcome = "winner" if winner_id else "no_bids"
        if reserve_price > 0:
            auction.reserve_met = True

    # 4. DB transaction
    now = datetime.now(timezone.utc)
    auction.status = AuctionStatus.ENDED.value
    auction.current_price = price
    auction.final_price = price if winner_id else None
    auction.bid_count = bid_count
    auction.extension_count = extension_count
    auction.winner_id = winner_id

    if listing:
        listing.status = "ended"
        listing.ended_at = now

    escrow = None
    if winner_id and seller_id:
        try:
            from app.services.escrow.service import create_escrow
            # price is in cents from Redis; escrow.amount must be JOD
            amount_jod = round(price / 100, 2)
            escrow = await create_escrow(
                auction_id=auction_id,
                winner_id=winner_id,
                seller_id=seller_id,
                amount=amount_jod,
                currency="JOD",
                db=db,
            )
            logger.info(
                "Escrow %s created: auction=%s winner=%s amount=%d",
                escrow.id, auction_id, winner_id, price,
            )
        except Exception:
            logger.exception("Failed to create escrow for auction=%s", auction_id)

    await db.commit()

    # 5. Publish ended event via Pub/Sub
    try:
        import json
        await redis.publish(
            f"channel:auction:{auction_id}",
            json.dumps({
                "event": "auction_ended",
                "payload": {
                    "auction_id": auction_id,
                    "winner_id": winner_id,
                    "final_price": round(price / 100, 2),
                    "bid_count": bid_count,
                    "outcome": outcome,
                },
            }),
        )
    except Exception:
        logger.warning("Failed to publish auction_ended for %s", auction_id)

    # 6. Notifications
    try:
        from app.tasks.notification import send_notification

        price_jod = round(price / 100, 2)
        if outcome == "winner":
            send_notification.delay(
                event="winner_notification",
                auction_id=auction_id,
                user_id=winner_id,
                data={"final_price": price_jod},
            )
            send_notification.delay(
                event="seller_auction_ended",
                auction_id=auction_id,
                user_id=seller_id,
                data={"final_price": price_jod, "winner_id": winner_id},
            )
        elif outcome == "reserve_not_met":
            send_notification.delay(
                event="reserve_not_met",
                auction_id=auction_id,
                user_id=seller_id,
                data={"final_price": price_jod, "reserve": round(reserve_price / 100, 2)},
            )
        elif outcome == "no_bids":
            send_notification.delay(
                event="seller_auction_ended",
                auction_id=auction_id,
                user_id=seller_id,
                data={"final_price": 0, "bid_count": 0},
            )
    except Exception:
        logger.warning("Failed to queue notifications for auction=%s", auction_id)

    # Sync listing to Meilisearch (status changed to ended)
    if listing:
        try:
            from app.tasks.listing import sync_listing_to_meilisearch
            sync_listing_to_meilisearch.delay(str(listing.id), action="index")
        except Exception:
            logger.warning("Failed to queue Meilisearch sync for listing=%s", listing.id)

    # Queue ATS score update for all participants
    try:
        from app.tasks.ats import update_ats_scores
        update_ats_scores.delay(auction_id=auction_id)
    except Exception:
        logger.warning("Failed to queue ATS update for auction=%s", auction_id)

    # 7. Cleanup Redis keys
    await _cleanup_redis_keys(auction_id, redis)

    logger.info(
        "Auction expired: id=%s outcome=%s winner=%s price=%d bids=%d",
        auction_id, outcome, winner_id, price, bid_count,
    )
    return {
        "status": "ended",
        "outcome": outcome,
        "winner_id": winner_id,
        "final_price": price,
        "bid_count": bid_count,
    }


# ── Get auction state ──────────────────────────────────────────

async def get_auction_state(
    auction_id: UUID | str,
    redis: Redis,
    db: AsyncSession | None = None,
) -> dict:
    """Read full auction state from Redis.

    Falls back to DB if Redis has no data (auction ended or not started).
    Returns a dict with all auction fields.
    """
    aid = str(auction_id)

    # Try Redis first
    pipe = redis.pipeline(transaction=False)
    pipe.get(_k(aid, "price"))
    pipe.get(_k(aid, "status"))
    pipe.get(_k(aid, "seller"))
    pipe.get(_k(aid, "last_bidder"))
    pipe.get(_k(aid, "bid_count"))
    pipe.get(_k(aid, "extension_ct"))
    pipe.get(_k(aid, "watcher_ct"))
    pipe.get(_k(aid, "min_increment"))
    pipe.get(_k(aid, "reserve"))
    pipe.ttl(_root(aid))
    results = await pipe.execute()

    price, status, seller, last_bidder, bid_count, ext_ct, watcher_ct, min_inc, reserve, ttl = results

    if status is not None:
        return {
            "auction_id": aid,
            "current_price": int(price) if price else 0,
            "status": status,
            "seller_id": seller or "",
            "last_bidder": last_bidder or None,
            "bid_count": int(bid_count) if bid_count else 0,
            "extension_count": int(ext_ct) if ext_ct else 0,
            "watcher_count": int(watcher_ct) if watcher_ct else 0,
            "min_increment": int(min_inc) if min_inc else 0,
            "reserve_price": int(reserve) if reserve else 0,
            "ttl_seconds": max(0, ttl) if ttl and ttl > 0 else 0,
        }

    # Fallback: read from DB
    if db:
        auction = await db.get(Auction, aid)
        if auction:
            return {
                "auction_id": aid,
                "current_price": int(auction.current_price) if auction.current_price else 0,
                "status": auction.status if isinstance(auction.status, str) else auction.status.value,
                "seller_id": "",
                "last_bidder": auction.winner_id,
                "bid_count": auction.bid_count or 0,
                "extension_count": auction.extension_count or 0,
                "watcher_count": 0,
                "min_increment": int(auction.min_increment) if auction.min_increment else 0,
                "reserve_price": 0,
                "ttl_seconds": 0,
            }

    return {"auction_id": aid, "status": "NOT_FOUND"}


# ── Bid placement (via Lua script) ─────────────────────────────

async def place_bid(
    auction_id: str,
    user_id: str,
    amount: int,
    redis: Redis,
) -> "BidResult":
    """Execute atomic bid via Lua script (EVALSHA).

    Returns a BidResult dataclass with accepted, new_price, extended,
    new_ttl, rejection_reason, and min_required fields.
    Anti-snipe is handled inside the Lua script atomically.
    """
    from app.services.auction.lua_scripts import BidLuaScripts

    return await BidLuaScripts.validate_bid(redis, str(auction_id), amount, user_id)


# ── Bid persistence ────────────────────────────────────────────

async def persist_bid(
    auction_id: str,
    user_id: str,
    amount: int,
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


# ── Auction lookup ─────────────────────────────────────────────

async def get_auction(auction_id: str, db: AsyncSession) -> Auction | None:
    return await db.get(Auction, auction_id)


# ── Proxy bids ─────────────────────────────────────────────────

async def execute_proxy_bids(
    auction_id: str,
    current_bidder_id: str,
    current_amount: int,
    redis: Redis,
    db: AsyncSession,
) -> Bid | None:
    """After a bid, check if any proxy bids should counter-bid.

    Finds the highest active proxy bid (excluding current bidder) whose
    max_amount can beat the current price.  Places the minimum necessary bid.
    """
    from sqlalchemy import select, desc
    from app.services.auction.models import ProxyBid

    result = await db.execute(
        select(ProxyBid)
        .where(
            ProxyBid.auction_id == auction_id,
            ProxyBid.user_id != current_bidder_id,
            ProxyBid.is_active.is_(True),
        )
        .order_by(desc(ProxyBid.max_amount))
        .limit(1)
    )
    proxy = result.scalar_one_or_none()
    if not proxy:
        return None

    min_inc_str = await redis.get(_k(auction_id, "min_increment"))
    min_increment = int(min_inc_str) if min_inc_str else settings.DEFAULT_MIN_INCREMENT

    next_bid = current_amount + min_increment

    if next_bid > int(proxy.max_amount):
        proxy.is_active = False
        await db.commit()
        return None

    result = await place_bid(auction_id, proxy.user_id, next_bid, redis)
    if not result.accepted:
        return None

    bid = await persist_bid(auction_id, proxy.user_id, next_bid, "JOD", db)
    bid.is_proxy = True
    await db.commit()
    await db.refresh(bid)

    logger.info(
        "Proxy bid placed: auction=%s user=%s amount=%d (max=%d) extended=%s",
        auction_id, proxy.user_id, next_bid, int(proxy.max_amount), result.extended,
    )
    return bid


# ── End auction (manual / sync) ────────────────────────────────

async def end_auction(
    auction_id: str,
    redis: Redis,
    db: AsyncSession,
) -> Auction | None:
    """Sync final state from Redis → PostgreSQL, set winner.

    For programmatic auction ending (admin cancel, buy-it-now, etc.).
    For normal expiry, use handle_auction_expiry instead.
    """
    return (await handle_auction_expiry(auction_id, redis, db)).get("auction")


# ── Stale auction failsafe ─────────────────────────────────────

async def check_stale_auctions(redis: Redis, db: AsyncSession) -> int:
    """Failsafe: find auctions marked ACTIVE in DB whose ends_at has
    passed (by > 5 minutes), and re-trigger expiry handling if Redis
    key already expired and was missed.

    Called every 5 minutes via Celery Beat.
    Returns the number of stale auctions recovered.
    """
    from sqlalchemy import select
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    result = await db.execute(
        select(Auction).where(
            Auction.status == AuctionStatus.ACTIVE.value,
            Auction.ends_at < cutoff,
        )
    )
    stale = result.scalars().all()

    if not stale:
        return 0

    logger.warning("Found %d stale active auctions", len(stale))
    recovered = 0

    for auction in stale:
        aid = auction.id
        # Check if Redis root key still exists
        root_exists = await redis.exists(_root(aid))
        if root_exists:
            # Redis key still alive — not actually stale, TTL may have been extended
            continue

        # Redis key gone but DB still says active → missed expiry
        logger.warning("Recovering stale auction %s (ends_at=%s)", aid, auction.ends_at)
        try:
            await handle_auction_expiry(aid, redis, db)
            recovered += 1
        except Exception:
            logger.exception("Failed to recover stale auction %s", aid)

    return recovered


# ── Redis cleanup ──────────────────────────────────────────────

async def _cleanup_redis_keys(auction_id: str, redis: Redis) -> None:
    """Delete all Redis keys for an auction."""
    keys = [_k(auction_id, s) for s in ALL_SUFFIXES]
    keys.append(_root(auction_id))
    await redis.delete(*keys)
