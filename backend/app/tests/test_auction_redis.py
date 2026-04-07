"""
Redis auction state management tests — SDD §3.2.1.

Tests cover:
- Initialize auction state in Redis
- Read auction state
- Anti-snipe extension logic
- Bid + anti-snipe integration
- Auction expiry → PostgreSQL sync + escrow creation
- Scheduled auction activation (Celery Beat task)
- Edge cases (max extensions, no bids, already ended)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.auction.models import Auction, AuctionStatus


def _has_celery() -> bool:
    try:
        import celery  # noqa: F401
        return True
    except ImportError:
        return False
from app.services.auction.service import (
    check_anti_snipe,
    initialize_auction_in_redis,
    place_bid,
    read_auction_state,
    end_auction,
)


# ── Helpers ──────────────────────────────────────────────────────

def _make_auction(**overrides) -> Auction:
    """Build an Auction ORM object with sensible defaults."""
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=str(uuid4()),
        listing_id=str(uuid4()),
        status=AuctionStatus.SCHEDULED.value,
        starts_at=now.isoformat(),
        ends_at=(now + timedelta(hours=2)).isoformat(),
        current_price=100.0,
        min_increment=25.0,
        bid_count=0,
        extension_count=0,
        winner_id=None,
        final_price=None,
        reserve_met=None,
        redis_synced_at=None,
    )
    defaults.update(overrides)
    auction = Auction(**defaults)
    return auction


SELLER_ID = str(uuid4())
BIDDER_ID = str(uuid4())


# ═══════════════════════════════════════════════════════════════════
# 1. Initialize auction state in Redis
# ═══════════════════════════════════════════════════════════════════

class TestInitializeAuction:
    @pytest.mark.asyncio
    async def test_initializes_all_fields(self, fake_redis):
        auction = _make_auction(current_price=500.0, min_increment=50.0)
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=7200)

        key = f"auction:{auction.id}"
        state = await fake_redis.hgetall(key)

        assert state["current_price"] == "500.0"
        assert state["status"] == "ACTIVE"
        assert state["seller_id"] == SELLER_ID
        assert state["last_bidder"] == ""
        assert state["bid_count"] == "0"
        assert state["extension_count"] == "0"
        assert state["watcher_count"] == "0"
        assert state["min_increment"] == "50.0"

    @pytest.mark.asyncio
    async def test_sets_ttl(self, fake_redis):
        auction = _make_auction()
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=3600)

        ttl = await fake_redis.ttl(f"auction:{auction.id}")
        assert ttl == 3600

    @pytest.mark.asyncio
    async def test_overwrites_existing_state(self, fake_redis):
        auction = _make_auction(current_price=100.0)
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=7200)

        # Re-init with different price
        auction.current_price = 200.0
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=3600)

        state = await fake_redis.hgetall(f"auction:{auction.id}")
        assert state["current_price"] == "200.0"


# ═══════════════════════════════════════════════════════════════════
# 2. Read auction state
# ═══════════════════════════════════════════════════════════════════

class TestReadAuctionState:
    @pytest.mark.asyncio
    async def test_returns_state_dict(self, fake_redis):
        auction = _make_auction()
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=7200)

        state = await read_auction_state(auction.id, fake_redis)
        assert state is not None
        assert state["status"] == "ACTIVE"
        assert "current_price" in state

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_key(self, fake_redis):
        state = await read_auction_state("nonexistent-id", fake_redis)
        assert state is None


# ═══════════════════════════════════════════════════════════════════
# 3. Anti-snipe extension
# ═══════════════════════════════════════════════════════════════════

class TestAntiSnipe:
    @pytest.mark.asyncio
    async def test_extends_when_ttl_within_window(self, fake_redis):
        """TTL <= 120s (ANTI_SNIPE_WINDOW_SECONDS) → extend by 120s."""
        auction = _make_auction()
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=100)

        extended = await check_anti_snipe(auction.id, fake_redis)
        assert extended is True

        # TTL should be 100 + 120 = 220
        new_ttl = await fake_redis.ttl(f"auction:{auction.id}")
        assert new_ttl == 220

        # extension_count should be 1
        ext = await fake_redis.hget(f"auction:{auction.id}", "extension_count")
        assert ext == "1"

    @pytest.mark.asyncio
    async def test_no_extend_when_ttl_above_window(self, fake_redis):
        """TTL > 120s → no extension."""
        auction = _make_auction()
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=300)

        extended = await check_anti_snipe(auction.id, fake_redis)
        assert extended is False

        ttl = await fake_redis.ttl(f"auction:{auction.id}")
        assert ttl == 300

    @pytest.mark.asyncio
    async def test_respects_max_extensions(self, fake_redis):
        """After MAX_ANTI_SNIPE_EXTENSIONS (5), no more extensions."""
        auction = _make_auction()
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=60)

        # Set extension_count to max (5)
        await fake_redis.hset(f"auction:{auction.id}", mapping={"extension_count": "5"})

        extended = await check_anti_snipe(auction.id, fake_redis)
        assert extended is False

    @pytest.mark.asyncio
    async def test_multiple_extensions_increment(self, fake_redis):
        """Multiple anti-snipe triggers increment extension_count."""
        auction = _make_auction()
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=50)

        await check_anti_snipe(auction.id, fake_redis)
        # After first: TTL=170, ext=1
        # Set TTL back to within window for next test
        await fake_redis.expire(f"auction:{auction.id}", 80)

        await check_anti_snipe(auction.id, fake_redis)
        ext = await fake_redis.hget(f"auction:{auction.id}", "extension_count")
        assert ext == "2"

    @pytest.mark.asyncio
    async def test_no_extend_for_missing_key(self, fake_redis):
        """Missing auction key → no extension."""
        extended = await check_anti_snipe("nonexistent", fake_redis)
        assert extended is False


# ═══════════════════════════════════════════════════════════════════
# 4. Bid + anti-snipe integration
# ═══════════════════════════════════════════════════════════════════

class TestBidAntiSnipeIntegration:
    @pytest.mark.asyncio
    async def test_bid_accepted_triggers_anti_snipe(self, fake_redis):
        """Accepted bid near end of auction triggers anti-snipe extension."""
        auction = _make_auction(current_price=100.0, min_increment=25.0)
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=90)

        # Place a valid bid
        status, reason = await place_bid(auction.id, BIDDER_ID, 200.0, fake_redis)
        assert status == "ACCEPTED"
        assert reason is None

        # Now check anti-snipe (normally called in the router)
        extended = await check_anti_snipe(auction.id, fake_redis)
        assert extended is True

        # Verify state updated correctly
        state = await fake_redis.hgetall(f"auction:{auction.id}")
        assert state["current_price"] == "200.0"
        assert state["last_bidder"] == BIDDER_ID
        assert state["bid_count"] == "1"
        assert state["extension_count"] == "1"

    @pytest.mark.asyncio
    async def test_rejected_bid_no_state_change(self, fake_redis):
        """Rejected bid (too low) doesn't change state."""
        auction = _make_auction(current_price=100.0, min_increment=25.0)
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=90)

        status, reason = await place_bid(auction.id, BIDDER_ID, 110.0, fake_redis)
        assert status == "REJECTED"
        assert reason == "BID_TOO_LOW"

        state = await fake_redis.hgetall(f"auction:{auction.id}")
        assert state["current_price"] == "100.0"
        assert state["bid_count"] == "0"

    @pytest.mark.asyncio
    async def test_seller_cannot_bid(self, fake_redis):
        auction = _make_auction(current_price=100.0, min_increment=25.0)
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=7200)

        status, reason = await place_bid(auction.id, SELLER_ID, 200.0, fake_redis)
        assert status == "REJECTED"
        assert reason == "SELLER_CANNOT_BID"

    @pytest.mark.asyncio
    async def test_bid_on_ended_auction(self, fake_redis):
        auction = _make_auction()
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=7200)
        # Manually set status to ended
        await fake_redis.hset(f"auction:{auction.id}", mapping={"status": "ENDED"})

        status, reason = await place_bid(auction.id, BIDDER_ID, 200.0, fake_redis)
        assert status == "REJECTED"
        assert reason == "AUCTION_ENDED"

    @pytest.mark.asyncio
    async def test_banned_user_rejected(self, fake_redis):
        banned_id = str(uuid4())
        await fake_redis.sadd("banned_users", banned_id)

        auction = _make_auction(current_price=100.0, min_increment=25.0)
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=7200)

        status, reason = await place_bid(auction.id, banned_id, 200.0, fake_redis)
        assert status == "REJECTED"
        assert reason == "USER_BANNED"


# ═══════════════════════════════════════════════════════════════════
# 5. End auction — Redis → PostgreSQL sync
# ═══════════════════════════════════════════════════════════════════

class TestEndAuction:
    @pytest.mark.asyncio
    async def test_syncs_state_to_postgres(self, fake_redis, db_session):
        """end_auction reads Redis state and writes to PostgreSQL."""
        auction = _make_auction(current_price=100.0)
        db_session.add(auction)
        await db_session.commit()

        # Initialize in Redis with some bids
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=7200)
        await place_bid(auction.id, BIDDER_ID, 200.0, fake_redis)
        await place_bid(auction.id, BIDDER_ID, 300.0, fake_redis)

        result = await end_auction(auction.id, fake_redis, db_session)

        assert result is not None
        assert result.status == AuctionStatus.ENDED
        assert float(result.current_price) == 300.0
        assert result.bid_count == 2
        assert result.winner_id == BIDDER_ID
        assert float(result.final_price) == 300.0

    @pytest.mark.asyncio
    async def test_deletes_redis_key_after_sync(self, fake_redis, db_session):
        auction = _make_auction()
        db_session.add(auction)
        await db_session.commit()

        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=7200)
        await end_auction(auction.id, fake_redis, db_session)

        exists = await fake_redis.exists(f"auction:{auction.id}")
        assert exists == 0

    @pytest.mark.asyncio
    async def test_end_auction_no_bids(self, fake_redis, db_session):
        """Auction with no bids — winner_id stays None."""
        auction = _make_auction(current_price=100.0)
        db_session.add(auction)
        await db_session.commit()

        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=7200)
        result = await end_auction(auction.id, fake_redis, db_session)

        assert result.status == AuctionStatus.ENDED
        assert result.winner_id is None
        assert result.bid_count == 0

    @pytest.mark.asyncio
    async def test_end_auction_missing_redis_key(self, fake_redis, db_session):
        """Redis key already expired — returns None."""
        auction = _make_auction()
        db_session.add(auction)
        await db_session.commit()

        # Don't initialize in Redis
        result = await end_auction(auction.id, fake_redis, db_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_end_auction_missing_in_postgres(self, fake_redis, db_session):
        """Auction not in PostgreSQL — returns None."""
        fake_id = str(uuid4())
        # Create Redis state for non-existent PG auction
        await fake_redis.hset(f"auction:{fake_id}", mapping={
            "current_price": "100", "status": "ACTIVE",
            "seller_id": SELLER_ID, "last_bidder": "",
            "bid_count": "0", "extension_count": "0",
            "watcher_count": "0", "min_increment": "25",
        })

        result = await end_auction(fake_id, fake_redis, db_session)
        assert result is None


# ═══════════════════════════════════════════════════════════════════
# 6. Handle auction expiry (Celery task)
# ═══════════════════════════════════════════════════════════════════

class TestHandleAuctionExpiry:
    @pytest.mark.asyncio
    async def test_expiry_syncs_to_postgres_and_creates_escrow(self, fake_redis, db_session):
        """Simulates key expiry: reads Redis state, updates PG, creates escrow."""
        from app.services.auction.lifecycle import handle_auction_expiry_async
        from app.services.listing.models import Listing

        listing = Listing(
            id=str(uuid4()),
            seller_id=SELLER_ID,
            title_ar="اختبار",
            description_ar="وصف",
            category_id=1,
            condition="good",
            starting_price=100.0,
            status="active",
        )
        db_session.add(listing)
        await db_session.flush()

        auction = _make_auction(
            listing_id=listing.id,
            current_price=100.0,
            status=AuctionStatus.ACTIVE.value,
        )
        db_session.add(auction)
        await db_session.commit()

        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=7200)
        await place_bid(auction.id, BIDDER_ID, 500.0, fake_redis)

        # Mock create_escrow since Escrow table doesn't exist in SQLite
        with patch("app.services.escrow.service.create_escrow", new_callable=AsyncMock) as mock_escrow:
            mock_escrow.return_value = MagicMock(id=str(uuid4()), amount=500.0)
            await handle_auction_expiry_async(auction.id, fake_redis, db_session)

            mock_escrow.assert_called_once()
            call_kwargs = mock_escrow.call_args
            assert call_kwargs[1]["winner_id"] == BIDDER_ID
            assert call_kwargs[1]["seller_id"] == SELLER_ID
            assert call_kwargs[1]["amount"] == 500.0

        await db_session.refresh(auction)
        assert auction.status == AuctionStatus.ENDED.value

    @pytest.mark.asyncio
    async def test_expiry_no_bids_no_escrow(self, fake_redis, db_session):
        """Auction with no bids → no escrow created."""
        from app.services.auction.lifecycle import handle_auction_expiry_async
        from app.services.listing.models import Listing

        listing = Listing(
            id=str(uuid4()),
            seller_id=SELLER_ID,
            title_ar="اختبار",
            description_ar="وصف",
            category_id=1,
            condition="good",
            starting_price=100.0,
            status="active",
        )
        db_session.add(listing)
        await db_session.flush()

        auction = _make_auction(
            listing_id=listing.id,
            current_price=100.0,
            status=AuctionStatus.ACTIVE.value,
        )
        db_session.add(auction)
        await db_session.commit()

        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=7200)

        with patch("app.services.escrow.service.create_escrow", new_callable=AsyncMock) as mock_escrow:
            await handle_auction_expiry_async(auction.id, fake_redis, db_session)
            mock_escrow.assert_not_called()

        await db_session.refresh(auction)
        assert auction.status == AuctionStatus.ENDED.value
        assert auction.winner_id is None

    @pytest.mark.asyncio
    async def test_expiry_already_ended_skips(self, fake_redis, db_session):
        """Already-ended auction is skipped."""
        from app.services.auction.lifecycle import handle_auction_expiry_async

        auction = _make_auction(status=AuctionStatus.ENDED.value)
        db_session.add(auction)
        await db_session.commit()

        await handle_auction_expiry_async(auction.id, fake_redis, db_session)

        await db_session.refresh(auction)
        assert auction.status == AuctionStatus.ENDED.value


# ═══════════════════════════════════════════════════════════════════
# 7. Activate scheduled auctions (Celery Beat task)
# ═══════════════════════════════════════════════════════════════════

class TestActivateScheduledAuctions:
    @pytest.mark.asyncio
    async def test_activates_due_auction(self, fake_redis, db_session):
        """Scheduled auction whose starts_at has passed gets activated."""
        from app.services.auction.lifecycle import activate_scheduled_auctions_async
        from app.services.listing.models import Listing

        listing = Listing(
            id=str(uuid4()),
            seller_id=SELLER_ID,
            title_ar="اختبار",
            description_ar="وصف",
            category_id=1,
            condition="good",
            starting_price=100.0,
            status="active",
        )
        db_session.add(listing)
        await db_session.flush()

        now = datetime.now(timezone.utc)
        auction = _make_auction(
            listing_id=listing.id,
            status=AuctionStatus.SCHEDULED.value,
            starts_at=(now - timedelta(minutes=1)).isoformat(),
            ends_at=(now + timedelta(hours=2)).isoformat(),
            current_price=100.0,
        )
        db_session.add(auction)
        await db_session.commit()

        count = await activate_scheduled_auctions_async(fake_redis, db_session)
        assert count == 1

        await db_session.refresh(auction)
        assert auction.status == AuctionStatus.ACTIVE.value
        assert auction.redis_synced_at is not None

        state = await fake_redis.hgetall(f"auction:{auction.id}")
        assert state["status"] == "ACTIVE"
        assert state["current_price"] == "100.0"
        assert state["seller_id"] == SELLER_ID

    @pytest.mark.asyncio
    async def test_skips_future_auction(self, fake_redis, db_session):
        """Auction with future starts_at is not activated."""
        from app.services.auction.lifecycle import activate_scheduled_auctions_async
        from app.services.listing.models import Listing

        listing = Listing(
            id=str(uuid4()),
            seller_id=SELLER_ID,
            title_ar="اختبار",
            description_ar="وصف",
            category_id=1,
            condition="good",
            starting_price=100.0,
            status="active",
        )
        db_session.add(listing)
        await db_session.flush()

        now = datetime.now(timezone.utc)
        auction = _make_auction(
            listing_id=listing.id,
            status=AuctionStatus.SCHEDULED.value,
            starts_at=(now + timedelta(hours=1)).isoformat(),
            ends_at=(now + timedelta(hours=3)).isoformat(),
        )
        db_session.add(auction)
        await db_session.commit()

        count = await activate_scheduled_auctions_async(fake_redis, db_session)
        assert count == 0

        await db_session.refresh(auction)
        assert auction.status == AuctionStatus.SCHEDULED.value

    @pytest.mark.asyncio
    async def test_marks_expired_auction_as_ended(self, fake_redis, db_session):
        """Auction whose ends_at is already past gets marked ENDED."""
        from app.services.auction.lifecycle import activate_scheduled_auctions_async
        from app.services.listing.models import Listing

        listing = Listing(
            id=str(uuid4()),
            seller_id=SELLER_ID,
            title_ar="اختبار",
            description_ar="وصف",
            category_id=1,
            condition="good",
            starting_price=100.0,
            status="active",
        )
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

        await activate_scheduled_auctions_async(fake_redis, db_session)

        await db_session.refresh(auction)
        assert auction.status == AuctionStatus.ENDED.value


# ═══════════════════════════════════════════════════════════════════
# 8. Celery Beat schedule verification
# ═══════════════════════════════════════════════════════════════════

class TestCeleryBeatSchedule:
    @pytest.mark.skipif(
        not _has_celery(), reason="celery not installed",
    )
    def test_auction_activation_in_beat_schedule(self):
        from app.core.celery import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "activate-scheduled-auctions" in schedule

        entry = schedule["activate-scheduled-auctions"]
        assert entry["task"] == "app.tasks.auction.activate_scheduled_auctions"
        assert entry["schedule"] == 30.0

    @pytest.mark.skipif(
        not _has_celery(), reason="celery not installed",
    )
    def test_escrow_deadline_check_still_exists(self):
        from app.core.celery import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "check-escrow-deadlines" in schedule


# ═══════════════════════════════════════════════════════════════════
# 9. Edge cases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_concurrent_bids_sequential_state(self, fake_redis):
        """Multiple bids update state correctly in sequence."""
        auction = _make_auction(current_price=100.0, min_increment=10.0)
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=7200)

        bidder_a = str(uuid4())
        bidder_b = str(uuid4())

        s1, _ = await place_bid(auction.id, bidder_a, 150.0, fake_redis)
        assert s1 == "ACCEPTED"

        s2, _ = await place_bid(auction.id, bidder_b, 200.0, fake_redis)
        assert s2 == "ACCEPTED"

        # bidder_a can't bid below current+increment
        s3, r3 = await place_bid(auction.id, bidder_a, 205.0, fake_redis)
        assert s3 == "REJECTED"
        assert r3 == "BID_TOO_LOW"

        state = await fake_redis.hgetall(f"auction:{auction.id}")
        assert state["current_price"] == "200.0"
        assert state["last_bidder"] == bidder_b
        assert state["bid_count"] == "2"

    @pytest.mark.asyncio
    async def test_anti_snipe_at_boundary(self, fake_redis):
        """TTL exactly at ANTI_SNIPE_WINDOW_SECONDS (120) triggers extension."""
        auction = _make_auction()
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=120)

        extended = await check_anti_snipe(auction.id, fake_redis)
        assert extended is True

    @pytest.mark.asyncio
    async def test_anti_snipe_at_boundary_plus_one(self, fake_redis):
        """TTL at 121 (just above window) → no extension."""
        auction = _make_auction()
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=121)

        extended = await check_anti_snipe(auction.id, fake_redis)
        assert extended is False

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, fake_redis, db_session):
        """Full lifecycle: init → bids → anti-snipe → end → verify PG."""
        auction = _make_auction(current_price=50.0, min_increment=10.0)
        db_session.add(auction)
        await db_session.commit()

        # Init
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=100)

        # Bid 1
        s, _ = await place_bid(auction.id, BIDDER_ID, 100.0, fake_redis)
        assert s == "ACCEPTED"

        # Anti-snipe (TTL=100 <= 120)
        ext = await check_anti_snipe(auction.id, fake_redis)
        assert ext is True

        # Bid 2
        bidder2 = str(uuid4())
        s, _ = await place_bid(auction.id, bidder2, 200.0, fake_redis)
        assert s == "ACCEPTED"

        # End auction
        result = await end_auction(auction.id, fake_redis, db_session)
        assert result.status == AuctionStatus.ENDED
        assert float(result.final_price) == 200.0
        assert result.winner_id == bidder2
        assert result.bid_count == 2
        assert result.extension_count == 1
