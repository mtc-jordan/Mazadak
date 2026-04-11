"""
Redis auction state management tests — SDD §3.2.1.

Tests cover:
- Initialize auction: sets all Redis keys, idempotency, past ends_at
- Handle expiry: winner + escrow, reserve not met, no bids
- Get auction state from Redis
- Anti-snipe extension logic
- Bid + anti-snipe integration
- Stale auction failsafe
- Celery Beat schedule verification
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.auction.models import Auction, AuctionStatus
from app.services.auction.service import (
    _k,
    _root,
    get_auction_state,
    handle_auction_expiry,
    initialize_auction,
    place_bid,
)


# ── Helpers ──────────────────────────────────────────────────────

SELLER_ID = str(uuid4())
BIDDER_ID = str(uuid4())
_now = datetime.now(timezone.utc)


def _make_auction(**overrides) -> Auction:
    """Build an Auction ORM object with sensible defaults."""
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=str(uuid4()),
        listing_id=str(uuid4()),
        status=AuctionStatus.SCHEDULED.value,
        starts_at=now.isoformat(),
        ends_at=(now + timedelta(hours=2)).isoformat(),
        current_price=10000,
        min_increment=2500,
        bid_count=0,
        extension_count=0,
        winner_id=None,
        final_price=None,
        reserve_met=None,
        redis_synced_at=None,
    )
    defaults.update(overrides)
    return Auction(**defaults)


def _make_listing(listing_id: str | None = None, **overrides):
    """Build a Listing ORM object for tests."""
    from app.services.listing.models import Listing

    defaults = dict(
        id=listing_id or str(uuid4()),
        seller_id=SELLER_ID,
        title_en="Test Listing",
        title_ar="اختبار",
        description_ar="وصف",
        category_id=1,
        condition="good",
        starting_price=10000,
        min_increment=2500,
        reserve_price=0,
        status="active",
        starts_at=_now + timedelta(minutes=10),
        ends_at=_now + timedelta(hours=25),
        moderation_flags="[]",
        moderation_status="pending",
    )
    defaults.update(overrides)
    return Listing(**defaults)


async def _init_auction_redis(fake_redis, auction_id, listing):
    """Set up individual Redis keys matching what initialize_auction writes."""
    aid = str(auction_id)
    await fake_redis.set(_k(aid, "price"), str(listing.starting_price))
    await fake_redis.set(_k(aid, "status"), "ACTIVE")
    await fake_redis.set(_k(aid, "seller"), str(listing.seller_id))
    await fake_redis.set(_k(aid, "last_bidder"), "")
    await fake_redis.set(_k(aid, "bid_count"), "0")
    await fake_redis.set(_k(aid, "extension_ct"), "0")
    await fake_redis.set(_k(aid, "watcher_ct"), "0")
    await fake_redis.set(_k(aid, "min_increment"), str(listing.min_increment))
    await fake_redis.set(_k(aid, "reserve"), str(listing.reserve_price or 0))
    await fake_redis.set(_root(aid), "active", ex=7200)


def _has_celery() -> bool:
    try:
        import celery  # noqa: F401
        return hasattr(celery, "__version__")  # MagicMock won't have this
    except ImportError:
        return False


# ═══════════════════════════════════════════════════════════════════
# 1. test_initialize_auction_sets_all_redis_keys
# ═══════════════════════════════════════════════════════════════════

class TestInitializeAuctionSetsAllKeys:
    @pytest.mark.asyncio
    async def test_initialize_auction_sets_all_redis_keys(self, fake_redis, db_session):
        """initialize_auction sets all individual Redis keys + root TTL."""
        listing = _make_listing(starting_price=15000, min_increment=2500, reserve_price=50000)
        db_session.add(listing)
        await db_session.flush()

        now = datetime.now(timezone.utc)
        auction = _make_auction(
            listing_id=listing.id,
            status=AuctionStatus.SCHEDULED.value,
            starts_at=(now - timedelta(minutes=1)).isoformat(),
            ends_at=(now + timedelta(hours=2)).isoformat(),
            current_price=15000,
        )
        db_session.add(auction)
        await db_session.commit()

        with patch("app.services.auction.service.sync_listing_to_meilisearch", create=True), \
             patch("app.services.auction.service.send_notification", create=True):
            result = await initialize_auction(
                auction_id=auction.id,
                listing_id=listing.id,
                db=db_session,
                redis=fake_redis,
            )

        assert result["status"] == "initialized"

        aid = auction.id
        # Verify all individual keys
        assert await fake_redis.get(_k(aid, "price")) == "15000"
        assert await fake_redis.get(_k(aid, "status")) == "ACTIVE"
        assert await fake_redis.get(_k(aid, "seller")) == SELLER_ID
        assert await fake_redis.get(_k(aid, "last_bidder")) == ""
        assert await fake_redis.get(_k(aid, "bid_count")) == "0"
        assert await fake_redis.get(_k(aid, "extension_ct")) == "0"
        assert await fake_redis.get(_k(aid, "watcher_ct")) == "0"
        assert await fake_redis.get(_k(aid, "min_increment")) == "2500"
        assert await fake_redis.get(_k(aid, "reserve")) == "50000"

        # Root key with TTL
        root_val = await fake_redis.get(_root(aid))
        assert root_val == "active"
        root_ttl = await fake_redis.ttl(_root(aid))
        assert root_ttl > 0

        # DB updated
        await db_session.refresh(auction)
        assert auction.status == AuctionStatus.ACTIVE.value


# ═══════════════════════════════════════════════════════════════════
# 2. test_initialize_auction_idempotent
# ═══════════════════════════════════════════════════════════════════

class TestInitializeAuctionIdempotent:
    @pytest.mark.asyncio
    async def test_initialize_auction_idempotent(self, fake_redis, db_session):
        """Calling initialize_auction twice → second call is skipped."""
        listing = _make_listing()
        db_session.add(listing)
        await db_session.flush()

        now = datetime.now(timezone.utc)
        auction = _make_auction(
            listing_id=listing.id,
            status=AuctionStatus.SCHEDULED.value,
            starts_at=(now - timedelta(minutes=1)).isoformat(),
            ends_at=(now + timedelta(hours=2)).isoformat(),
        )
        db_session.add(auction)
        await db_session.commit()

        with patch("app.services.auction.service.sync_listing_to_meilisearch", create=True), \
             patch("app.services.auction.service.send_notification", create=True):
            result1 = await initialize_auction(auction.id, listing.id, db_session, fake_redis)
            assert result1["status"] == "initialized"

            # Second call — auction is now ACTIVE, should skip
            result2 = await initialize_auction(auction.id, listing.id, db_session, fake_redis)
            assert result2["status"] == "skipped"
            assert result2["reason"] == "already_active"


# ═══════════════════════════════════════════════════════════════════
# 3. test_initialize_auction_past_ends_at → marks ended immediately
# ═══════════════════════════════════════════════════════════════════

class TestInitializeAuctionPastEndsAt:
    @pytest.mark.asyncio
    async def test_initialize_auction_past_ends_at(self, fake_redis, db_session):
        """Auction with past ends_at → marked ended immediately, no Redis keys."""
        listing = _make_listing()
        db_session.add(listing)
        await db_session.flush()

        now = datetime.now(timezone.utc)
        auction = _make_auction(
            listing_id=listing.id,
            status=AuctionStatus.SCHEDULED.value,
            starts_at=(now - timedelta(hours=3)).isoformat(),
            ends_at=(now - timedelta(hours=1)).isoformat(),
        )
        db_session.add(auction)
        await db_session.commit()

        result = await initialize_auction(auction.id, listing.id, db_session, fake_redis)

        assert result["status"] == "ended"
        assert result["reason"] == "past_ends_at"

        # No Redis keys should be set
        assert await fake_redis.get(_k(auction.id, "status")) is None
        assert await fake_redis.get(_root(auction.id)) is None

        # DB should be marked ended
        await db_session.refresh(auction)
        assert auction.status == AuctionStatus.ENDED.value


# ═══════════════════════════════════════════════════════════════════
# 4. test_handle_expiry_with_winner → escrow created, winner notified
# ═══════════════════════════════════════════════════════════════════

class TestHandleExpiryWithWinner:
    @pytest.mark.asyncio
    async def test_handle_expiry_with_winner(self, fake_redis, db_session):
        """Auction with bids → escrow created, winner + seller notified."""
        listing = _make_listing()
        db_session.add(listing)
        await db_session.flush()

        auction = _make_auction(
            listing_id=listing.id,
            status=AuctionStatus.ACTIVE.value,
        )
        db_session.add(auction)
        await db_session.commit()

        # Set up Redis state with a winning bid
        await _init_auction_redis(fake_redis, auction.id, listing)
        await place_bid(auction.id, BIDDER_ID, 50000, fake_redis)

        # Verify bid was accepted
        assert await fake_redis.get(_k(auction.id, "last_bidder")) == BIDDER_ID
        assert await fake_redis.get(_k(auction.id, "bid_count")) == "1"

        with patch("app.services.escrow.service.create_escrow", new_callable=AsyncMock) as mock_escrow, \
             patch("app.services.auction.service.send_notification", create=True), \
             patch("app.services.auction.service.update_ats_scores", create=True):
            mock_escrow.return_value = MagicMock(id=str(uuid4()), amount=50000)
            result = await handle_auction_expiry(auction.id, fake_redis, db_session)

        assert result["status"] == "ended"
        assert result["outcome"] == "winner"
        assert result["winner_id"] == BIDDER_ID
        assert result["final_price"] == 50000
        assert result["bid_count"] == 1

        # Escrow was created
        mock_escrow.assert_called_once()
        call_kw = mock_escrow.call_args.kwargs
        assert call_kw["winner_id"] == BIDDER_ID
        assert call_kw["seller_id"] == SELLER_ID
        assert call_kw["amount"] == 500.0  # 50000 cents → 500.0 JOD

        # DB updated
        await db_session.refresh(auction)
        assert auction.status == AuctionStatus.ENDED.value
        assert auction.winner_id == BIDDER_ID

        # Redis keys cleaned up
        assert await fake_redis.get(_k(auction.id, "status")) is None
        assert await fake_redis.get(_k(auction.id, "price")) is None


# ═══════════════════════════════════════════════════════════════════
# 5. test_handle_expiry_reserve_not_met → no escrow, all notified
# ═══════════════════════════════════════════════════════════════════

class TestHandleExpiryReserveNotMet:
    @pytest.mark.asyncio
    async def test_handle_expiry_reserve_not_met(self, fake_redis, db_session):
        """Bids exist but below reserve → no escrow, reserve_met=False."""
        listing = _make_listing(reserve_price=100000)
        db_session.add(listing)
        await db_session.flush()

        auction = _make_auction(
            listing_id=listing.id,
            status=AuctionStatus.ACTIVE.value,
        )
        db_session.add(auction)
        await db_session.commit()

        # Set up Redis with reserve and a bid below it
        await _init_auction_redis(fake_redis, auction.id, listing)
        await place_bid(auction.id, BIDDER_ID, 50000, fake_redis)

        with patch("app.services.escrow.service.create_escrow", new_callable=AsyncMock) as mock_escrow, \
             patch("app.services.auction.service.send_notification", create=True), \
             patch("app.services.auction.service.update_ats_scores", create=True):
            result = await handle_auction_expiry(auction.id, fake_redis, db_session)

        assert result["status"] == "ended"
        assert result["outcome"] == "reserve_not_met"
        assert result["winner_id"] is None

        # No escrow created
        mock_escrow.assert_not_called()

        # DB: reserve_met = False
        await db_session.refresh(auction)
        assert auction.reserve_met is False


# ═══════════════════════════════════════════════════════════════════
# 6. test_handle_expiry_no_bids → listing marked ended cleanly
# ═══════════════════════════════════════════════════════════════════

class TestHandleExpiryNoBids:
    @pytest.mark.asyncio
    async def test_handle_expiry_no_bids(self, fake_redis, db_session):
        """No bids at all → listing ended, no escrow, no winner."""
        listing = _make_listing()
        db_session.add(listing)
        await db_session.flush()

        auction = _make_auction(
            listing_id=listing.id,
            status=AuctionStatus.ACTIVE.value,
        )
        db_session.add(auction)
        await db_session.commit()

        await _init_auction_redis(fake_redis, auction.id, listing)

        with patch("app.services.escrow.service.create_escrow", new_callable=AsyncMock) as mock_escrow, \
             patch("app.services.auction.service.send_notification", create=True), \
             patch("app.services.auction.service.update_ats_scores", create=True):
            result = await handle_auction_expiry(auction.id, fake_redis, db_session)

        assert result["status"] == "ended"
        assert result["outcome"] == "no_bids"
        assert result["winner_id"] is None
        assert result["bid_count"] == 0

        mock_escrow.assert_not_called()

        await db_session.refresh(auction)
        assert auction.status == AuctionStatus.ENDED.value
        assert auction.winner_id is None

        # Listing ended
        await db_session.refresh(listing)
        assert listing.status == "ended"
        assert listing.ended_at is not None


# ═══════════════════════════════════════════════════════════════════
# 7. test_stale_auction_failsafe_triggered
# ═══════════════════════════════════════════════════════════════════

class TestStaleAuctionFailsafe:
    @pytest.mark.asyncio
    async def test_stale_auction_failsafe_triggered(self, fake_redis, db_session):
        """Auction active in DB but Redis root key gone → failsafe recovers it."""
        from app.services.auction.service import check_stale_auctions

        listing = _make_listing()
        db_session.add(listing)
        await db_session.flush()

        now = datetime.now(timezone.utc)
        auction = _make_auction(
            listing_id=listing.id,
            status=AuctionStatus.ACTIVE.value,
            ends_at=(now - timedelta(minutes=10)).isoformat(),
        )
        db_session.add(auction)
        await db_session.commit()

        # Don't set any Redis keys — simulates expired key that was missed

        with patch("app.services.escrow.service.create_escrow", new_callable=AsyncMock), \
             patch("app.services.auction.service.send_notification", create=True), \
             patch("app.services.auction.service.update_ats_scores", create=True):
            recovered = await check_stale_auctions(fake_redis, db_session)

        assert recovered == 1

        await db_session.refresh(auction)
        assert auction.status == AuctionStatus.ENDED.value


# ═══════════════════════════════════════════════════════════════════
# 8. Get auction state
# ═══════════════════════════════════════════════════════════════════

class TestGetAuctionState:
    @pytest.mark.asyncio
    async def test_returns_full_state_from_redis(self, fake_redis):
        """get_auction_state reads all individual keys."""
        listing = _make_listing()
        aid = str(uuid4())
        await _init_auction_redis(fake_redis, aid, listing)

        state = await get_auction_state(aid, fake_redis)
        assert state["status"] == "ACTIVE"
        assert state["current_price"] == 10000
        assert state["seller_id"] == SELLER_ID
        assert state["bid_count"] == 0
        assert state["watcher_count"] == 0
        assert state["min_increment"] == 2500

    @pytest.mark.asyncio
    async def test_returns_not_found_for_missing(self, fake_redis):
        state = await get_auction_state("nonexistent", fake_redis)
        assert state["status"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_falls_back_to_db(self, fake_redis, db_session):
        """If no Redis keys, reads from DB."""
        auction = _make_auction(status=AuctionStatus.ENDED.value, current_price=50000, bid_count=5)
        db_session.add(auction)
        await db_session.commit()

        state = await get_auction_state(auction.id, fake_redis, db=db_session)
        assert state["status"] == AuctionStatus.ENDED.value
        assert state["current_price"] == 50000
        assert state["bid_count"] == 5


# ═══════════════════════════════════════════════════════════════════
# 9. Anti-snipe extension
# ═══════════════════════════════════════════════════════════════════

class TestAntiSnipe:
    @pytest.mark.asyncio
    async def test_bid_extends_when_ttl_under_threshold(self, fake_redis):
        """Bid with TTL <= 180s triggers anti-snipe extension inside Lua."""
        from app.services.auction.lua_scripts import BidLuaScripts
        BidLuaScripts.reset()

        listing = _make_listing(starting_price=10000, min_increment=2500)
        aid = str(uuid4())
        await _init_auction_redis(fake_redis, aid, listing)
        await fake_redis.set(_root(aid), "active", ex=100)

        result = await place_bid(aid, BIDDER_ID, 20000, fake_redis)
        assert result.accepted
        assert result.extended is True
        assert result.new_ttl == 280  # 100 + 180

        ext = await fake_redis.get(_k(aid, "extension_ct"))
        assert ext == "1"

    @pytest.mark.asyncio
    async def test_bid_no_extend_when_ttl_above_threshold(self, fake_redis):
        """Bid with TTL > 180s does NOT trigger anti-snipe."""
        from app.services.auction.lua_scripts import BidLuaScripts
        BidLuaScripts.reset()

        listing = _make_listing(starting_price=10000, min_increment=2500)
        aid = str(uuid4())
        await _init_auction_redis(fake_redis, aid, listing)
        await fake_redis.set(_root(aid), "active", ex=300)

        result = await place_bid(aid, BIDDER_ID, 20000, fake_redis)
        assert result.accepted
        assert result.extended is False


# ═══════════════════════════════════════════════════════════════════
# 10. Bid integration
# ═══════════════════════════════════════════════════════════════════

class TestBidIntegration:
    @pytest.mark.asyncio
    async def test_bid_accepted_updates_keys(self, fake_redis):
        from app.services.auction.lua_scripts import BidLuaScripts
        BidLuaScripts.reset()

        listing = _make_listing(starting_price=10000, min_increment=2500)
        aid = str(uuid4())
        await _init_auction_redis(fake_redis, aid, listing)

        result = await place_bid(aid, BIDDER_ID, 20000, fake_redis)
        assert result.accepted
        assert result.new_price == 20000

        assert await fake_redis.get(_k(aid, "price")) == "20000"
        assert await fake_redis.get(_k(aid, "last_bidder")) == BIDDER_ID
        assert await fake_redis.get(_k(aid, "bid_count")) == "1"

    @pytest.mark.asyncio
    async def test_bid_too_low_rejected(self, fake_redis):
        from app.services.auction.lua_scripts import BidLuaScripts
        BidLuaScripts.reset()

        listing = _make_listing(starting_price=10000, min_increment=2500)
        aid = str(uuid4())
        await _init_auction_redis(fake_redis, aid, listing)

        result = await place_bid(aid, BIDDER_ID, 11000, fake_redis)
        assert not result.accepted
        assert result.rejection_reason == "BID_TOO_LOW"
        assert result.min_required == 12500

    @pytest.mark.asyncio
    async def test_seller_cannot_bid(self, fake_redis):
        from app.services.auction.lua_scripts import BidLuaScripts
        BidLuaScripts.reset()

        listing = _make_listing()
        aid = str(uuid4())
        await _init_auction_redis(fake_redis, aid, listing)

        result = await place_bid(aid, SELLER_ID, 50000, fake_redis)
        assert not result.accepted
        assert result.rejection_reason == "SELLER_CANNOT_BID"

    @pytest.mark.asyncio
    async def test_banned_user_rejected(self, fake_redis):
        from app.services.auction.lua_scripts import BidLuaScripts
        BidLuaScripts.reset()

        banned_id = str(uuid4())
        listing = _make_listing()
        aid = str(uuid4())
        await _init_auction_redis(fake_redis, aid, listing)
        await fake_redis.sadd(_k(aid, "banned_set"), banned_id)

        result = await place_bid(aid, banned_id, 50000, fake_redis)
        assert not result.accepted
        assert result.rejection_reason == "BIDDER_BANNED"

    @pytest.mark.asyncio
    async def test_bid_on_ended_auction(self, fake_redis):
        from app.services.auction.lua_scripts import BidLuaScripts
        BidLuaScripts.reset()

        listing = _make_listing()
        aid = str(uuid4())
        await _init_auction_redis(fake_redis, aid, listing)
        await fake_redis.set(_k(aid, "status"), "ENDED")

        result = await place_bid(aid, BIDDER_ID, 50000, fake_redis)
        assert not result.accepted
        assert result.rejection_reason == "AUCTION_NOT_ACTIVE"

    @pytest.mark.asyncio
    async def test_sequential_bids(self, fake_redis):
        """Multiple bids update state correctly in sequence."""
        from app.services.auction.lua_scripts import BidLuaScripts
        BidLuaScripts.reset()

        listing = _make_listing(starting_price=10000, min_increment=1000)
        aid = str(uuid4())
        await _init_auction_redis(fake_redis, aid, listing)

        bidder_a = str(uuid4())
        bidder_b = str(uuid4())

        r1 = await place_bid(aid, bidder_a, 15000, fake_redis)
        assert r1.accepted

        r2 = await place_bid(aid, bidder_b, 20000, fake_redis)
        assert r2.accepted

        # bidder_a can't bid below current + increment
        r3 = await place_bid(aid, bidder_a, 20500, fake_redis)
        assert not r3.accepted
        assert r3.rejection_reason == "BID_TOO_LOW"

        assert await fake_redis.get(_k(aid, "price")) == "20000"
        assert await fake_redis.get(_k(aid, "last_bidder")) == bidder_b
        assert await fake_redis.get(_k(aid, "bid_count")) == "2"


# ═══════════════════════════════════════════════════════════════════
# 11. Handle expiry idempotency
# ═══════════════════════════════════════════════════════════════════

class TestExpiryIdempotency:
    @pytest.mark.asyncio
    async def test_already_ended_skips(self, fake_redis, db_session):
        """Already-ended auction is skipped."""
        auction = _make_auction(status=AuctionStatus.ENDED.value)
        db_session.add(auction)
        await db_session.commit()

        result = await handle_auction_expiry(auction.id, fake_redis, db_session)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_redis_status_ended_skips(self, fake_redis, db_session):
        """If Redis status already ENDED, skip."""
        listing = _make_listing()
        db_session.add(listing)
        await db_session.flush()

        auction = _make_auction(listing_id=listing.id, status=AuctionStatus.ACTIVE.value)
        db_session.add(auction)
        await db_session.commit()

        await _init_auction_redis(fake_redis, auction.id, listing)
        await fake_redis.set(_k(auction.id, "status"), "ENDED")

        result = await handle_auction_expiry(auction.id, fake_redis, db_session)
        assert result["status"] == "skipped"
        assert result["reason"] == "already_ended"


# ═══════════════════════════════════════════════════════════════════
# 12. Celery Beat schedule verification
# ═══════════════════════════════════════════════════════════════════

class TestCeleryBeatSchedule:
    @pytest.mark.skipif(not _has_celery(), reason="celery not installed")
    def test_auction_activation_in_beat_schedule(self):
        from app.core.celery import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "activate-scheduled-auctions" in schedule
        entry = schedule["activate-scheduled-auctions"]
        assert entry["task"] == "app.tasks.auction.activate_scheduled_auctions"
        assert entry["schedule"] == 30.0

    @pytest.mark.skipif(not _has_celery(), reason="celery not installed")
    def test_stale_auction_check_in_beat_schedule(self):
        from app.core.celery import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "check-stale-auctions" in schedule
        entry = schedule["check-stale-auctions"]
        assert entry["task"] == "app.tasks.auction.check_stale_auctions"
        assert entry["schedule"] == 300.0
