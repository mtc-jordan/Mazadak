"""Auction endpoints — SDD §5.4."""

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select, or_, func

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.types import UUIDPath
from app.services.auth.dependencies import get_current_user, require_role
from app.services.auth.models import User
from app.services.auction import schemas, service
from app.services.auction.dependencies import check_bid_rate_limit, get_auction_or_404
from app.services.auction.models import Auction, AuctionStatus
from app.services.listing.models import Listing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auctions", tags=["auctions"])


# ── GET / — Public auction list with filters ─────────────────

@router.get("/", response_model=schemas.AuctionListResponse)
async def list_auctions(
    status_filter: str | None = Query(default=None, alias="status"),
    category_id: int | None = None,
    sort: str | None = Query(
        default=None,
        pattern=r"^(ends_at_asc|price_asc|price_desc|bid_count_desc|newest)$",
    ),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List auctions with optional filters. Defaults to active only."""
    query = (
        select(Auction, Listing)
        .join(Listing, Auction.listing_id == Listing.id)
    )

    # Default to active auctions for public browsing
    if status_filter:
        query = query.where(Auction.status == status_filter)
    else:
        query = query.where(Auction.status == AuctionStatus.ACTIVE.value)

    if category_id is not None:
        query = query.where(Listing.category_id == category_id)

    # Count
    count_q = select(func.count()).select_from(
        query.with_only_columns(Auction.id).subquery()
    )
    total = (await db.execute(count_q)).scalar() or 0

    # Sort
    if sort == "price_asc":
        query = query.order_by(Auction.current_price.asc())
    elif sort == "price_desc":
        query = query.order_by(Auction.current_price.desc())
    elif sort == "bid_count_desc":
        query = query.order_by(Auction.bid_count.desc())
    elif sort == "newest":
        query = query.order_by(Auction.created_at.desc())
    else:
        # Default: ending soonest first
        query = query.order_by(Auction.ends_at.asc())

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    items = []
    for auction, listing in rows:
        image_url = ""
        if listing.images:
            image_url = listing.images[0].s3_key

        items.append(schemas.AuctionListItem(
            id=auction.id,
            listing_id=auction.listing_id,
            title_ar=listing.title_ar,
            title_en=listing.title_en,
            image_url=image_url,
            category_id=listing.category_id,
            condition=listing.condition,
            starting_price=listing.starting_price,
            current_price=float(auction.current_price),
            currency="JOD",
            min_increment=float(auction.min_increment),
            bid_count=auction.bid_count,
            status=auction.status if isinstance(auction.status, str) else auction.status.value,
            starts_at=auction.starts_at,
            ends_at=auction.ends_at,
            is_charity=listing.is_charity,
            is_certified=listing.is_certified,
            location_city=listing.location_city,
            location_country=listing.location_country or "JO",
        ))

    return schemas.AuctionListResponse(
        data=items,
        total_count=total,
        limit=limit,
        offset=offset,
    )


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
            starting_price=listing.starting_price / 100,  # cents → JOD
            current_price=float(auction.current_price),
            currency="JOD",
            bid_count=auction.bid_count,
            status=auction.status if isinstance(auction.status, str) else auction.status.value,
            ends_at=auction.ends_at,
            winner_name=None,
            is_live=auction.status == AuctionStatus.ACTIVE,
        )

        # Categorise — won takes priority to avoid duplicates when
        # user is both seller and winner of the same auction.
        if auction.winner_id == user.id:
            won.append(item)
        elif listing.seller_id == user.id:
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


# ═══════════════════════════════════════════════════════════════
#  Admin auction management endpoints
# ═══════════════════════════════════════════════════════════════

@router.post(
    "/{auction_id}/pause",
    dependencies=[Depends(require_role("admin", "superadmin"))],
)
async def admin_pause_auction(
    auction_id: UUIDPath,
    body: schemas.AdminPauseRequest,
    user: User = Depends(require_role("admin", "superadmin")),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Pause an active auction. Preserves remaining TTL for resume."""
    aid = str(auction_id)
    redis_status = await redis.get(service._k(aid, "status"))

    if redis_status != "ACTIVE":
        raise HTTPException(
            status_code=400,
            detail={"code": "NOT_ACTIVE", "message_en": "Auction is not active"},
        )

    # Save remaining TTL before pausing
    remaining_ttl = await redis.ttl(service._root(aid))
    await redis.set(service._k(aid, "status"), "PAUSED")
    # Store remaining TTL so we can restore it on resume
    await redis.set(service._k(aid, "paused_ttl"), str(max(remaining_ttl, 0)))
    # Remove root key TTL to prevent expiry while paused
    await redis.persist(service._root(aid))

    # Update DB
    auction = await db.get(Auction, aid)
    if auction:
        auction.status = "paused"
        await db.commit()

    # Broadcast pause event
    await redis.publish(f"channel:auction:{aid}", json.dumps({
        "event": "auction_paused",
        "payload": {"auction_id": aid, "reason": body.reason},
    }))

    logger.info("Admin %s paused auction %s: %s", user.id, aid, body.reason)
    return {"success": True, "message": "Auction paused", "remaining_ttl": remaining_ttl}


@router.post(
    "/{auction_id}/resume",
    dependencies=[Depends(require_role("admin", "superadmin"))],
)
async def admin_resume_auction(
    auction_id: UUIDPath,
    body: schemas.AdminResumeRequest,
    user: User = Depends(require_role("admin", "superadmin")),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused auction, optionally extending the time."""
    aid = str(auction_id)
    redis_status = await redis.get(service._k(aid, "status"))

    if redis_status != "PAUSED":
        raise HTTPException(
            status_code=400,
            detail={"code": "NOT_PAUSED", "message_en": "Auction is not paused"},
        )

    # Restore TTL
    paused_ttl_str = await redis.get(service._k(aid, "paused_ttl"))
    paused_ttl = int(paused_ttl_str) if paused_ttl_str else 300  # 5 min default
    new_ttl = paused_ttl + (body.extend_minutes * 60)

    await redis.set(service._k(aid, "status"), "ACTIVE")
    await redis.set(service._root(aid), "active", ex=new_ttl)
    await redis.delete(service._k(aid, "paused_ttl"))

    # Update DB
    auction = await db.get(Auction, aid)
    if auction:
        auction.status = AuctionStatus.ACTIVE.value
        if body.extend_minutes > 0:
            from datetime import timedelta, datetime, timezone
            auction.ends_at = datetime.now(timezone.utc) + timedelta(seconds=new_ttl)
        await db.commit()

    # Broadcast resume event
    await redis.publish(f"channel:auction:{aid}", json.dumps({
        "event": "auction_resumed",
        "payload": {"auction_id": aid, "remaining_seconds": new_ttl},
    }))

    logger.info("Admin %s resumed auction %s (ttl=%ds)", user.id, aid, new_ttl)
    return {"success": True, "message": "Auction resumed", "remaining_seconds": new_ttl}


@router.post(
    "/{auction_id}/cancel",
    dependencies=[Depends(require_role("admin", "superadmin"))],
)
async def admin_cancel_auction(
    auction_id: UUIDPath,
    body: schemas.AdminCancelRequest,
    user: User = Depends(require_role("admin", "superadmin")),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Cancel an auction. No winner, no escrow. All bids voided."""
    aid = str(auction_id)

    # Update Redis
    await redis.set(service._k(aid, "status"), "CANCELLED")
    await redis.delete(service._root(aid))

    # Update DB
    auction = await db.get(Auction, aid)
    if not auction:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})

    auction.status = AuctionStatus.CANCELLED.value
    listing = await db.get(Listing, auction.listing_id)
    if listing:
        listing.status = "cancelled"
    await db.commit()

    # Broadcast cancellation
    await redis.publish(f"channel:auction:{aid}", json.dumps({
        "event": "auction_cancelled",
        "payload": {"auction_id": aid, "reason": body.reason},
    }))

    # Cleanup Redis keys
    await service._cleanup_redis_keys(aid, redis)

    logger.info("Admin %s cancelled auction %s: %s", user.id, aid, body.reason)
    return {"success": True, "message": "Auction cancelled"}


@router.post(
    "/{auction_id}/override",
    dependencies=[Depends(require_role("admin", "superadmin"))],
)
async def admin_override_auction(
    auction_id: UUIDPath,
    body: schemas.AdminOverrideRequest,
    user: User = Depends(require_role("admin", "superadmin")),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Override auction parameters: extend time, change min increment."""
    aid = str(auction_id)
    redis_status = await redis.get(service._k(aid, "status"))

    if redis_status not in ("ACTIVE", "PAUSED"):
        raise HTTPException(
            status_code=400,
            detail={"code": "NOT_ACTIVE", "message_en": "Auction must be active or paused"},
        )

    if body.extend_minutes is None and body.new_min_increment is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_CHANGES", "message_en": "At least one override field required"},
        )

    changes = {}

    if body.extend_minutes is not None:
        current_ttl = await redis.ttl(service._root(aid))
        new_ttl = max(current_ttl, 0) + (body.extend_minutes * 60)
        await redis.set(service._root(aid), "active", ex=new_ttl)
        changes["remaining_seconds"] = new_ttl

        auction = await db.get(Auction, aid)
        if auction:
            from datetime import timedelta, datetime, timezone
            auction.ends_at = datetime.now(timezone.utc) + timedelta(seconds=new_ttl)
            await db.commit()

    if body.new_min_increment is not None:
        await redis.set(service._k(aid, "min_increment"), str(body.new_min_increment))
        changes["min_increment"] = body.new_min_increment

        auction = await db.get(Auction, aid)
        if auction:
            auction.min_increment = body.new_min_increment
            await db.commit()

    # Broadcast override event
    await redis.publish(f"channel:auction:{aid}", json.dumps({
        "event": "auction_override",
        "payload": {"auction_id": aid, **changes},
    }))

    logger.info("Admin %s overrode auction %s: %s", user.id, aid, changes)
    return {"success": True, "message": "Auction updated", "changes": changes}


@router.post(
    "/emergency-kill",
    dependencies=[Depends(require_role("superadmin"))],
)
async def emergency_kill_switch(
    body: schemas.EmergencyKillRequest,
    user: User = Depends(require_role("superadmin")),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Emergency kill switch: pause ALL active auctions platform-wide.

    Superadmin only. Requires confirm=true as safety guard.
    Sets a global Redis flag that prevents new bids and pauses all auctions.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail={"code": "CONFIRM_REQUIRED", "message_en": "Set confirm=true to execute kill switch"},
        )

    # Set global kill switch flag in Redis
    await redis.set("platform:kill_switch", "1")
    await redis.set("platform:kill_switch:reason", body.reason)
    await redis.set("platform:kill_switch:by", str(user.id))

    # Find all active auctions and pause them
    result = await db.execute(
        select(Auction).where(Auction.status == AuctionStatus.ACTIVE.value)
    )
    active_auctions = result.scalars().all()
    paused_count = 0

    for auction in active_auctions:
        aid = auction.id
        redis_status = await redis.get(service._k(aid, "status"))
        if redis_status == "ACTIVE":
            remaining_ttl = await redis.ttl(service._root(aid))
            await redis.set(service._k(aid, "status"), "PAUSED")
            await redis.set(service._k(aid, "paused_ttl"), str(max(remaining_ttl, 0)))
            await redis.persist(service._root(aid))

            # Broadcast pause
            await redis.publish(f"channel:auction:{aid}", json.dumps({
                "event": "auction_paused",
                "payload": {"auction_id": aid, "reason": f"Emergency: {body.reason}"},
            }))

        auction.status = "paused"
        paused_count += 1

    await db.commit()

    logger.critical(
        "EMERGENCY KILL SWITCH activated by %s: %s — %d auctions paused",
        user.id, body.reason, paused_count,
    )
    return {
        "success": True,
        "message": f"Emergency kill switch activated. {paused_count} auctions paused.",
        "paused_count": paused_count,
    }


@router.post(
    "/emergency-resume",
    dependencies=[Depends(require_role("superadmin"))],
)
async def emergency_resume(
    user: User = Depends(require_role("superadmin")),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Lift the emergency kill switch and resume all paused auctions."""
    kill_active = await redis.get("platform:kill_switch")
    if kill_active != "1":
        raise HTTPException(
            status_code=400,
            detail={"code": "NOT_ACTIVE", "message_en": "Kill switch is not active"},
        )

    # Clear kill switch flag
    await redis.delete("platform:kill_switch", "platform:kill_switch:reason", "platform:kill_switch:by")

    # Resume all paused auctions
    result = await db.execute(
        select(Auction).where(Auction.status == "paused")
    )
    paused_auctions = result.scalars().all()
    resumed_count = 0

    for auction in paused_auctions:
        aid = auction.id
        paused_ttl_str = await redis.get(service._k(aid, "paused_ttl"))
        paused_ttl = int(paused_ttl_str) if paused_ttl_str else 300

        await redis.set(service._k(aid, "status"), "ACTIVE")
        await redis.set(service._root(aid), "active", ex=paused_ttl)
        await redis.delete(service._k(aid, "paused_ttl"))

        auction.status = AuctionStatus.ACTIVE.value
        resumed_count += 1

        await redis.publish(f"channel:auction:{aid}", json.dumps({
            "event": "auction_resumed",
            "payload": {"auction_id": aid, "remaining_seconds": paused_ttl},
        }))

    await db.commit()

    logger.info(
        "Emergency kill switch lifted by %s — %d auctions resumed",
        user.id, resumed_count,
    )
    return {
        "success": True,
        "message": f"Kill switch lifted. {resumed_count} auctions resumed.",
        "resumed_count": resumed_count,
    }
