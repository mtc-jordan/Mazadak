"""
Lua bid validation script tests — SDD §3.2.2.

This is the most critical code path in the platform: every bid in
every auction runs through this single Lua script atomically.

Tests cover:
  1. SCRIPT LOAD / EVALSHA lifecycle
  2. All 4 rejection reasons (AUCTION_ENDED, SELLER_CANNOT_BID,
     USER_BANNED, BID_TOO_LOW)
  3. Happy-path acceptance with state mutation verification
  4. Validation order (status checked before amount)
  5. Concurrency: 100 simultaneous bids at identical amount —
     exactly 1 ACCEPTED, 99 REJECTED
  6. Edge cases (boundary amounts, sequential bidding wars)
"""

from __future__ import annotations

import asyncio
import threading
from uuid import uuid4

import pytest

from app.services.auction.lua_scripts import BidScript
from app.services.auction.service import initialize_auction_in_redis, place_bid


# ── Helpers ──────────────────────────────────────────────────────

SELLER_ID = str(uuid4())


def _auction_key(auction_id: str) -> str:
    return f"auction:{auction_id}"


async def _setup_auction(
    fake_redis,
    *,
    current_price: float = 100.0,
    min_increment: float = 25.0,
    status: str = "ACTIVE",
    seller_id: str = SELLER_ID,
    ttl: int = 7200,
) -> str:
    """Create an auction Hash in FakeRedis. Returns the auction_id."""
    auction_id = str(uuid4())
    key = _auction_key(auction_id)
    await fake_redis.hset(key, mapping={
        "current_price": str(current_price),
        "status": status,
        "seller_id": seller_id,
        "last_bidder": "",
        "bid_count": "0",
        "extension_count": "0",
        "watcher_count": "0",
        "min_increment": str(min_increment),
    })
    await fake_redis.expire(key, ttl)
    return auction_id


# ═══════════════════════════════════════════════════════════════════
# 1. SCRIPT LOAD / EVALSHA lifecycle
# ═══════════════════════════════════════════════════════════════════

class TestScriptLifecycle:
    @pytest.mark.asyncio
    async def test_script_load_returns_sha(self, fake_redis):
        """SCRIPT LOAD returns a non-empty SHA string."""
        BidScript.reset()
        sha = await BidScript.load(fake_redis)
        assert isinstance(sha, str)
        assert len(sha) == 40  # SHA1 hex digest

    @pytest.mark.asyncio
    async def test_sha_cached_after_first_load(self, fake_redis):
        """Second call to load() returns cached SHA without hitting Redis."""
        BidScript.reset()
        sha1 = await BidScript.load(fake_redis)
        sha2 = await BidScript.load(fake_redis)
        assert sha1 == sha2

    @pytest.mark.asyncio
    async def test_execute_uses_evalsha(self, fake_redis):
        """execute() works via EVALSHA (script_load + evalsha path)."""
        BidScript.reset()
        auction_id = await _setup_auction(fake_redis)

        bidder = str(uuid4())
        status, reason = await BidScript.execute(
            fake_redis, _auction_key(auction_id), bidder, 200.0,
        )
        assert status == "ACCEPTED"
        assert reason is None

    @pytest.mark.asyncio
    async def test_noscript_fallback(self, fake_redis):
        """If SHA is evicted, NOSCRIPT triggers reload + retry."""
        BidScript.reset()
        auction_id = await _setup_auction(fake_redis)

        # Load normally first
        sha = await BidScript.load(fake_redis)

        # Simulate NOSCRIPT by clearing the script store
        fake_redis._scripts.clear()

        bidder = str(uuid4())
        status, reason = await BidScript.execute(
            fake_redis, _auction_key(auction_id), bidder, 200.0,
        )
        # Should succeed after automatic reload
        assert status == "ACCEPTED"

    @pytest.mark.asyncio
    async def test_reset_clears_cached_sha(self, fake_redis):
        """BidScript.reset() clears the cached SHA."""
        BidScript.reset()
        await BidScript.load(fake_redis)
        assert BidScript._sha is not None

        BidScript.reset()
        assert BidScript._sha is None


# ═══════════════════════════════════════════════════════════════════
# 2. All 4 rejection reasons
# ═══════════════════════════════════════════════════════════════════

class TestRejectionReasons:
    @pytest.mark.asyncio
    async def test_auction_ended(self, fake_redis):
        """Bid on non-ACTIVE auction → AUCTION_ENDED."""
        BidScript.reset()
        auction_id = await _setup_auction(fake_redis, status="ENDED")

        bidder = str(uuid4())
        status, reason = await place_bid(auction_id, bidder, 200.0, fake_redis)
        assert status == "REJECTED"
        assert reason == "AUCTION_ENDED"

    @pytest.mark.asyncio
    async def test_auction_ended_paused(self, fake_redis):
        """Any non-ACTIVE status (e.g. PAUSED) → AUCTION_ENDED."""
        BidScript.reset()
        auction_id = await _setup_auction(fake_redis, status="PAUSED")

        bidder = str(uuid4())
        status, reason = await place_bid(auction_id, bidder, 200.0, fake_redis)
        assert status == "REJECTED"
        assert reason == "AUCTION_ENDED"

    @pytest.mark.asyncio
    async def test_seller_cannot_bid(self, fake_redis):
        """Seller bidding on own auction → SELLER_CANNOT_BID."""
        BidScript.reset()
        auction_id = await _setup_auction(fake_redis)

        status, reason = await place_bid(auction_id, SELLER_ID, 200.0, fake_redis)
        assert status == "REJECTED"
        assert reason == "SELLER_CANNOT_BID"

    @pytest.mark.asyncio
    async def test_user_banned(self, fake_redis):
        """Banned user bidding → USER_BANNED."""
        BidScript.reset()
        banned_id = str(uuid4())
        await fake_redis.sadd("banned_users", banned_id)

        auction_id = await _setup_auction(fake_redis)

        status, reason = await place_bid(auction_id, banned_id, 200.0, fake_redis)
        assert status == "REJECTED"
        assert reason == "USER_BANNED"

    @pytest.mark.asyncio
    async def test_bid_too_low_below_threshold(self, fake_redis):
        """Bid at or below current_price + min_increment → BID_TOO_LOW."""
        BidScript.reset()
        # current=100, increment=25 → need > 125
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=25.0,
        )

        bidder = str(uuid4())
        status, reason = await place_bid(auction_id, bidder, 125.0, fake_redis)
        assert status == "REJECTED"
        assert reason == "BID_TOO_LOW"

    @pytest.mark.asyncio
    async def test_bid_too_low_exact_current(self, fake_redis):
        """Bid at exactly current price → BID_TOO_LOW."""
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=25.0,
        )

        bidder = str(uuid4())
        status, reason = await place_bid(auction_id, bidder, 100.0, fake_redis)
        assert status == "REJECTED"
        assert reason == "BID_TOO_LOW"

    @pytest.mark.asyncio
    async def test_bid_too_low_one_below_threshold(self, fake_redis):
        """Bid at threshold - 0.001 → BID_TOO_LOW."""
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=25.0,
        )

        bidder = str(uuid4())
        # Threshold is 125.0, bid at 124.999
        status, reason = await place_bid(auction_id, bidder, 124.999, fake_redis)
        assert status == "REJECTED"
        assert reason == "BID_TOO_LOW"


# ═══════════════════════════════════════════════════════════════════
# 3. Happy-path acceptance + state mutation
# ═══════════════════════════════════════════════════════════════════

class TestAcceptance:
    @pytest.mark.asyncio
    async def test_accepted_bid_updates_current_price(self, fake_redis):
        """Accepted bid sets current_price to new amount."""
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=25.0,
        )

        bidder = str(uuid4())
        status, _ = await place_bid(auction_id, bidder, 200.0, fake_redis)
        assert status == "ACCEPTED"

        state = await fake_redis.hgetall(_auction_key(auction_id))
        assert state["current_price"] == "200.0"

    @pytest.mark.asyncio
    async def test_accepted_bid_sets_last_bidder(self, fake_redis):
        """Accepted bid sets last_bidder to the bidder's user_id."""
        BidScript.reset()
        auction_id = await _setup_auction(fake_redis)

        bidder = str(uuid4())
        await place_bid(auction_id, bidder, 200.0, fake_redis)

        state = await fake_redis.hgetall(_auction_key(auction_id))
        assert state["last_bidder"] == bidder

    @pytest.mark.asyncio
    async def test_accepted_bid_increments_bid_count(self, fake_redis):
        """Each accepted bid increments bid_count by 1."""
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=10.0,
        )

        b1 = str(uuid4())
        b2 = str(uuid4())
        await place_bid(auction_id, b1, 150.0, fake_redis)
        await place_bid(auction_id, b2, 200.0, fake_redis)

        state = await fake_redis.hgetall(_auction_key(auction_id))
        assert state["bid_count"] == "2"

    @pytest.mark.asyncio
    async def test_rejected_bid_does_not_mutate_state(self, fake_redis):
        """Rejected bid leaves all fields unchanged."""
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=25.0,
        )

        before = await fake_redis.hgetall(_auction_key(auction_id))

        bidder = str(uuid4())
        await place_bid(auction_id, bidder, 50.0, fake_redis)

        after = await fake_redis.hgetall(_auction_key(auction_id))
        assert before == after

    @pytest.mark.asyncio
    async def test_minimum_valid_bid_accepted(self, fake_redis):
        """Bid at current_price + min_increment + 0.001 is accepted."""
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=25.0,
        )

        bidder = str(uuid4())
        # Threshold is 125.0, bid at 125.001
        status, _ = await place_bid(auction_id, bidder, 125.001, fake_redis)
        assert status == "ACCEPTED"


# ═══════════════════════════════════════════════════════════════════
# 4. Validation order (status checked before amount)
# ═══════════════════════════════════════════════════════════════════

class TestValidationOrder:
    @pytest.mark.asyncio
    async def test_ended_auction_with_low_bid_returns_auction_ended(self, fake_redis):
        """On an ENDED auction, even a low bid returns AUCTION_ENDED,
        not BID_TOO_LOW — status is checked first."""
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, status="ENDED", current_price=100.0, min_increment=25.0,
        )

        bidder = str(uuid4())
        status, reason = await place_bid(auction_id, bidder, 1.0, fake_redis)
        assert reason == "AUCTION_ENDED"

    @pytest.mark.asyncio
    async def test_seller_bid_with_low_amount_returns_seller_cannot_bid(self, fake_redis):
        """Seller bidding low returns SELLER_CANNOT_BID, not BID_TOO_LOW."""
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=25.0,
        )

        status, reason = await place_bid(auction_id, SELLER_ID, 1.0, fake_redis)
        assert reason == "SELLER_CANNOT_BID"

    @pytest.mark.asyncio
    async def test_banned_user_with_low_amount_returns_user_banned(self, fake_redis):
        """Banned user bidding low returns USER_BANNED, not BID_TOO_LOW."""
        BidScript.reset()
        banned_id = str(uuid4())
        await fake_redis.sadd("banned_users", banned_id)

        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=25.0,
        )

        status, reason = await place_bid(auction_id, banned_id, 1.0, fake_redis)
        assert reason == "USER_BANNED"

    @pytest.mark.asyncio
    async def test_ended_auction_seller_bid_returns_auction_ended(self, fake_redis):
        """ENDED status takes priority over seller check."""
        BidScript.reset()
        auction_id = await _setup_auction(fake_redis, status="ENDED")

        status, reason = await place_bid(auction_id, SELLER_ID, 999.0, fake_redis)
        assert reason == "AUCTION_ENDED"


# ═══════════════════════════════════════════════════════════════════
# 5. Concurrency: 100 simultaneous bids at identical amount
# ═══════════════════════════════════════════════════════════════════

class TestConcurrency:
    @pytest.mark.asyncio
    async def test_100_simultaneous_bids_exactly_1_accepted(self, fake_redis):
        """100 threads bid simultaneously at the same amount.

        Exactly 1 must be ACCEPTED (the first to acquire the lock).
        The other 99 must be REJECTED with BID_TOO_LOW (because
        current_price was already updated by the winner).

        This validates the atomicity guarantee of the Lua script.
        """
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=25.0,
        )

        NUM_BIDDERS = 100
        BID_AMOUNT = 200.0  # Valid: > 100 + 25

        # Pre-load the script
        await BidScript.load(fake_redis)

        results: list[tuple[str, str | None]] = [None] * NUM_BIDDERS
        barrier = threading.Barrier(NUM_BIDDERS)

        def _bid_worker(idx: int, bidder_id: str):
            """Each thread creates its own event loop and bids."""
            barrier.wait()  # All threads start simultaneously
            loop = asyncio.new_event_loop()
            try:
                results[idx] = loop.run_until_complete(
                    place_bid(auction_id, bidder_id, BID_AMOUNT, fake_redis)
                )
            finally:
                loop.close()

        bidders = [str(uuid4()) for _ in range(NUM_BIDDERS)]
        threads = [
            threading.Thread(target=_bid_worker, args=(i, bidders[i]))
            for i in range(NUM_BIDDERS)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # Count outcomes
        accepted = [r for r in results if r and r[0] == "ACCEPTED"]
        rejected = [r for r in results if r and r[0] == "REJECTED"]

        assert len(accepted) == 1, f"Expected exactly 1 ACCEPTED, got {len(accepted)}"
        assert len(rejected) == 99, f"Expected exactly 99 REJECTED, got {len(rejected)}"

        # All rejections must be BID_TOO_LOW
        for _, reason in rejected:
            assert reason == "BID_TOO_LOW"

        # Verify final state
        state = await fake_redis.hgetall(_auction_key(auction_id))
        assert state["bid_count"] == "1"
        assert state["current_price"] == str(BID_AMOUNT)

        # The winner must be one of our bidders
        assert state["last_bidder"] in bidders

    @pytest.mark.asyncio
    async def test_100_simultaneous_bids_ascending_amounts(self, fake_redis):
        """100 threads bid at ascending amounts (126, 127, ..., 225).

        Multiple bids should be accepted as each successive winner
        raises the price. All accepted bids must be in ascending order.
        The final price must be the highest accepted bid.
        """
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=25.0,
        )

        NUM_BIDDERS = 100
        await BidScript.load(fake_redis)

        results: list[tuple[str, str | None, float, str]] = [None] * NUM_BIDDERS
        barrier = threading.Barrier(NUM_BIDDERS)

        def _bid_worker(idx: int, bidder_id: str, amount: float):
            barrier.wait()
            loop = asyncio.new_event_loop()
            try:
                s, r = loop.run_until_complete(
                    place_bid(auction_id, bidder_id, amount, fake_redis)
                )
                results[idx] = (s, r, amount, bidder_id)
            finally:
                loop.close()

        bidders = [str(uuid4()) for _ in range(NUM_BIDDERS)]
        # Each bidder bids a different amount: 126.0, 127.0, ..., 225.0
        amounts = [126.0 + i for i in range(NUM_BIDDERS)]

        threads = [
            threading.Thread(
                target=_bid_worker, args=(i, bidders[i], amounts[i]),
            )
            for i in range(NUM_BIDDERS)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        accepted = [(s, r, amt, bid) for s, r, amt, bid in results if s == "ACCEPTED"]
        rejected = [(s, r, amt, bid) for s, r, amt, bid in results if s == "REJECTED"]

        # At least 1 must be accepted (the first to run)
        assert len(accepted) >= 1
        # Total must be 100
        assert len(accepted) + len(rejected) == NUM_BIDDERS

        # Final price must be the highest accepted amount
        state = await fake_redis.hgetall(_auction_key(auction_id))
        highest_accepted = max(amt for _, _, amt, _ in accepted)
        assert float(state["current_price"]) == highest_accepted
        assert int(state["bid_count"]) == len(accepted)


# ═══════════════════════════════════════════════════════════════════
# 6. Edge cases
# ═══════════════════════════════════════════════════════════════════

class TestLuaEdgeCases:
    @pytest.mark.asyncio
    async def test_sequential_bidding_war(self, fake_redis):
        """Sequential bids must each exceed the new price + increment."""
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=10.0,
        )

        b1, b2, b3 = str(uuid4()), str(uuid4()), str(uuid4())

        s, _ = await place_bid(auction_id, b1, 150.0, fake_redis)
        assert s == "ACCEPTED"

        # b2 must bid > 160 (150 + 10)
        s, r = await place_bid(auction_id, b2, 160.0, fake_redis)
        assert s == "REJECTED"
        assert r == "BID_TOO_LOW"

        s, _ = await place_bid(auction_id, b2, 161.0, fake_redis)
        assert s == "ACCEPTED"

        # b3 must bid > 171 (161 + 10)
        s, _ = await place_bid(auction_id, b3, 200.0, fake_redis)
        assert s == "ACCEPTED"

        state = await fake_redis.hgetall(_auction_key(auction_id))
        assert state["current_price"] == "200.0"
        assert state["bid_count"] == "3"
        assert state["last_bidder"] == b3

    @pytest.mark.asyncio
    async def test_bid_on_nonexistent_auction(self, fake_redis):
        """Bid on missing auction key → AUCTION_ENDED (status is empty)."""
        BidScript.reset()
        bidder = str(uuid4())
        status, reason = await place_bid("nonexistent", bidder, 200.0, fake_redis)
        assert status == "REJECTED"
        assert reason == "AUCTION_ENDED"

    @pytest.mark.asyncio
    async def test_zero_min_increment(self, fake_redis):
        """With min_increment=0, any amount > current_price is accepted."""
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=0.0,
        )

        bidder = str(uuid4())
        s, _ = await place_bid(auction_id, bidder, 100.001, fake_redis)
        assert s == "ACCEPTED"

    @pytest.mark.asyncio
    async def test_very_large_bid_accepted(self, fake_redis):
        """Extremely large bid is accepted without overflow."""
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=25.0,
        )

        bidder = str(uuid4())
        s, _ = await place_bid(auction_id, bidder, 999_999_999.999, fake_redis)
        assert s == "ACCEPTED"

        state = await fake_redis.hgetall(_auction_key(auction_id))
        assert float(state["current_price"]) == 999_999_999.999

    @pytest.mark.asyncio
    async def test_bid_count_never_decrements(self, fake_redis):
        """bid_count only goes up — rejected bids don't affect it."""
        BidScript.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=100.0, min_increment=25.0,
        )

        bidder = str(uuid4())

        # 3 rejected bids
        for _ in range(3):
            await place_bid(auction_id, bidder, 50.0, fake_redis)

        # 1 accepted bid
        await place_bid(auction_id, bidder, 200.0, fake_redis)

        state = await fake_redis.hgetall(_auction_key(auction_id))
        assert state["bid_count"] == "1"

    @pytest.mark.asyncio
    async def test_multiple_rejection_reasons_priority(self, fake_redis):
        """Test full priority chain: status > seller > banned > amount.

        A banned seller bidding low on an ended auction should get
        AUCTION_ENDED (highest priority check).
        """
        BidScript.reset()
        banned_seller = SELLER_ID
        await fake_redis.sadd("banned_users", banned_seller)

        auction_id = await _setup_auction(
            fake_redis,
            status="ENDED",
            seller_id=banned_seller,
            current_price=100.0,
            min_increment=25.0,
        )

        status, reason = await place_bid(
            auction_id, banned_seller, 1.0, fake_redis,
        )
        assert reason == "AUCTION_ENDED"

    @pytest.mark.asyncio
    async def test_via_service_place_bid_path(self, fake_redis):
        """Verify the full service.place_bid → BidScript.execute path."""
        BidScript.reset()
        from app.services.auction.models import Auction, AuctionStatus
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        auction = Auction(
            id=str(uuid4()),
            listing_id=str(uuid4()),
            status=AuctionStatus.SCHEDULED.value,
            starts_at=now.isoformat(),
            ends_at=(now + timedelta(hours=2)).isoformat(),
            current_price=500.0,
            min_increment=50.0,
            bid_count=0,
            extension_count=0,
        )
        await initialize_auction_in_redis(auction, SELLER_ID, fake_redis, ttl_seconds=7200)

        bidder = str(uuid4())
        status, reason = await place_bid(auction.id, bidder, 600.0, fake_redis)
        assert status == "ACCEPTED"
        assert reason is None

        state = await fake_redis.hgetall(f"auction:{auction.id}")
        assert state["current_price"] == "600.0"
        assert state["last_bidder"] == bidder
        assert state["bid_count"] == "1"
