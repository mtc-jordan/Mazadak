"""
Lua bid validation engine tests — SDD §3.2.2.

The most critical code path in the platform: every bid in every auction
runs through this single Lua script executed atomically inside Redis.
Zero race conditions allowed.

Tests (7 required by spec):
  1. test_concurrent_bids_exactly_one_accepted
  2. test_bid_rejected_seller_cannot_bid
  3. test_bid_rejected_auction_not_active
  4. test_bid_rejected_too_low
  5. test_bid_accepted_triggers_anti_snipe_when_under_180s
  6. test_bid_accepted_no_extension_when_over_180s
  7. test_script_reloads_on_noscript_error

Uses individual Redis keys (not Hash) per SDD §3.2 key schema.
"""

from __future__ import annotations

import asyncio
import threading
from uuid import uuid4

import pytest

from app.services.auction.lua_scripts import BidLuaScripts, BidResult
from app.services.auction.service import _k, _root, place_bid


# ── Helpers ──────────────────────────────────────────────────────

SELLER_ID = str(uuid4())


async def _setup_auction(
    fake_redis,
    *,
    current_price: int = 10000,
    min_increment: int = 2500,
    status: str = "ACTIVE",
    seller_id: str = SELLER_ID,
    ttl: int = 7200,
) -> str:
    """Create auction state using individual Redis keys. Returns auction_id."""
    auction_id = str(uuid4())
    await fake_redis.set(_k(auction_id, "price"), str(current_price))
    await fake_redis.set(_k(auction_id, "status"), status)
    await fake_redis.set(_k(auction_id, "seller"), seller_id)
    await fake_redis.set(_k(auction_id, "last_bidder"), "")
    await fake_redis.set(_k(auction_id, "bid_count"), "0")
    await fake_redis.set(_k(auction_id, "extension_ct"), "0")
    await fake_redis.set(_k(auction_id, "watcher_ct"), "0")
    await fake_redis.set(_k(auction_id, "min_increment"), str(min_increment))
    await fake_redis.set(_k(auction_id, "reserve"), "0")
    await fake_redis.set(_root(auction_id), "active", ex=ttl)
    return auction_id


# ═══════════════════════════════════════════════════════════════════
# 1. test_concurrent_bids_exactly_one_accepted
# ═══════════════════════════════════════════════════════════════════

class TestConcurrentBids:
    @pytest.mark.asyncio
    async def test_concurrent_bids_exactly_one_accepted(self, fake_redis):
        """Fire 100 bid requests at identical amount simultaneously.

        Exactly 1 must be ACCEPTED (the first to acquire the lock).
        The other 99 must be REJECTED with BID_TOO_LOW.
        bid_count in Redis == 1.
        price in Redis == bid_amount.
        """
        BidLuaScripts.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=10000, min_increment=2500,
        )

        NUM_BIDDERS = 100
        BID_AMOUNT = 20000  # Valid: >= 10000 + 2500

        await BidLuaScripts.load(fake_redis)

        results: list[BidResult | None] = [None] * NUM_BIDDERS
        barrier = threading.Barrier(NUM_BIDDERS)

        def _bid_worker(idx: int, bidder_id: str):
            barrier.wait()
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

        accepted = [r for r in results if r and r.accepted]
        rejected = [r for r in results if r and not r.accepted]

        # Exactly 1 winner
        assert len(accepted) == 1, f"Expected exactly 1 ACCEPTED, got {len(accepted)}"
        assert len(rejected) == 99, f"Expected exactly 99 REJECTED, got {len(rejected)}"

        # All 99 losers hit BID_TOO_LOW (price moved past their amount)
        for r in rejected:
            assert r.rejection_reason == "BID_TOO_LOW"

        # Winner got correct new_price back
        assert accepted[0].new_price == BID_AMOUNT

        # Redis state: exactly 1 bid recorded
        assert await fake_redis.get(_k(auction_id, "bid_count")) == "1"
        assert await fake_redis.get(_k(auction_id, "price")) == str(BID_AMOUNT)
        assert await fake_redis.get(_k(auction_id, "last_bidder")) in bidders


# ═══════════════════════════════════════════════════════════════════
# 2. test_bid_rejected_seller_cannot_bid
# ═══════════════════════════════════════════════════════════════════

class TestSellerCannotBid:
    @pytest.mark.asyncio
    async def test_bid_rejected_seller_cannot_bid(self, fake_redis):
        """Seller bidding on own auction → SELLER_CANNOT_BID.
        No min_required returned (only BID_TOO_LOW returns that)."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(fake_redis)

        result = await place_bid(auction_id, SELLER_ID, 20000, fake_redis)

        assert not result.accepted
        assert result.rejection_reason == "SELLER_CANNOT_BID"
        assert result.min_required is None
        assert result.new_price == 0

    @pytest.mark.asyncio
    async def test_seller_bid_priority_over_bid_too_low(self, fake_redis):
        """Seller bidding low → SELLER_CANNOT_BID, not BID_TOO_LOW.
        Seller check (2) runs before amount check (4)."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(fake_redis)

        result = await place_bid(auction_id, SELLER_ID, 100, fake_redis)
        assert result.rejection_reason == "SELLER_CANNOT_BID"


# ═══════════════════════════════════════════════════════════════════
# 3. test_bid_rejected_auction_not_active
# ═══════════════════════════════════════════════════════════════════

class TestAuctionNotActive:
    @pytest.mark.asyncio
    async def test_bid_rejected_auction_not_active(self, fake_redis):
        """Bid on ENDED auction → AUCTION_NOT_ACTIVE.
        No min_required returned."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(fake_redis, status="ENDED")

        bidder = str(uuid4())
        result = await place_bid(auction_id, bidder, 20000, fake_redis)

        assert not result.accepted
        assert result.rejection_reason == "AUCTION_NOT_ACTIVE"
        assert result.min_required is None

    @pytest.mark.asyncio
    async def test_paused_auction(self, fake_redis):
        """Any non-ACTIVE status (PAUSED) → AUCTION_NOT_ACTIVE."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(fake_redis, status="PAUSED")

        bidder = str(uuid4())
        result = await place_bid(auction_id, bidder, 20000, fake_redis)
        assert result.rejection_reason == "AUCTION_NOT_ACTIVE"

    @pytest.mark.asyncio
    async def test_nonexistent_auction(self, fake_redis):
        """Bid on missing auction → AUCTION_NOT_ACTIVE (status is empty)."""
        BidLuaScripts.reset()
        bidder = str(uuid4())
        result = await place_bid("nonexistent", bidder, 20000, fake_redis)
        assert result.rejection_reason == "AUCTION_NOT_ACTIVE"

    @pytest.mark.asyncio
    async def test_status_check_runs_before_amount_check(self, fake_redis):
        """ENDED auction + low bid → AUCTION_NOT_ACTIVE, not BID_TOO_LOW.
        Check 1 (status) runs before Check 4 (amount)."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(fake_redis, status="ENDED")

        bidder = str(uuid4())
        result = await place_bid(auction_id, bidder, 100, fake_redis)
        assert result.rejection_reason == "AUCTION_NOT_ACTIVE"


# ═══════════════════════════════════════════════════════════════════
# 4. test_bid_rejected_too_low
# ═══════════════════════════════════════════════════════════════════

class TestBidTooLow:
    @pytest.mark.asyncio
    async def test_bid_rejected_too_low(self, fake_redis):
        """Bid below current_price + min_increment → BID_TOO_LOW.
        min_required IS returned (only rejection that includes it)."""
        BidLuaScripts.reset()
        # current=10000, increment=2500 → need >= 12500
        auction_id = await _setup_auction(
            fake_redis, current_price=10000, min_increment=2500,
        )

        bidder = str(uuid4())
        result = await place_bid(auction_id, bidder, 12000, fake_redis)

        assert not result.accepted
        assert result.rejection_reason == "BID_TOO_LOW"
        assert result.min_required == 12500

    @pytest.mark.asyncio
    async def test_bid_at_exact_current_price(self, fake_redis):
        """Bid at exactly current price → BID_TOO_LOW."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=10000, min_increment=2500,
        )

        bidder = str(uuid4())
        result = await place_bid(auction_id, bidder, 10000, fake_redis)
        assert result.rejection_reason == "BID_TOO_LOW"
        assert result.min_required == 12500

    @pytest.mark.asyncio
    async def test_bid_at_exact_threshold_accepted(self, fake_redis):
        """Bid at exactly current_price + min_increment IS accepted
        (the Lua uses < not <=)."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=10000, min_increment=2500,
        )

        bidder = str(uuid4())
        result = await place_bid(auction_id, bidder, 12500, fake_redis)

        assert result.accepted
        assert result.new_price == 12500

    @pytest.mark.asyncio
    async def test_rejected_bid_does_not_mutate_state(self, fake_redis):
        """Rejected bid leaves all Redis keys unchanged."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=10000, min_increment=2500,
        )

        price_before = await fake_redis.get(_k(auction_id, "price"))
        count_before = await fake_redis.get(_k(auction_id, "bid_count"))

        bidder = str(uuid4())
        await place_bid(auction_id, bidder, 5000, fake_redis)

        assert await fake_redis.get(_k(auction_id, "price")) == price_before
        assert await fake_redis.get(_k(auction_id, "bid_count")) == count_before

    @pytest.mark.asyncio
    async def test_min_required_rises_after_accepted_bid(self, fake_redis):
        """After an accepted bid raises the price, the next rejection
        returns the updated min_required."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=10000, min_increment=2500,
        )

        b1 = str(uuid4())
        r1 = await place_bid(auction_id, b1, 15000, fake_redis)
        assert r1.accepted

        b2 = str(uuid4())
        r2 = await place_bid(auction_id, b2, 16000, fake_redis)
        assert not r2.accepted
        assert r2.min_required == 17500  # 15000 + 2500

    @pytest.mark.asyncio
    async def test_banned_user_rejected(self, fake_redis):
        """Banned user → BIDDER_BANNED, no min_required."""
        BidLuaScripts.reset()
        banned_id = str(uuid4())
        auction_id = await _setup_auction(fake_redis)
        await fake_redis.sadd(_k(auction_id, "banned_set"), banned_id)

        result = await place_bid(auction_id, banned_id, 20000, fake_redis)

        assert not result.accepted
        assert result.rejection_reason == "BIDDER_BANNED"
        assert result.min_required is None


# ═══════════════════════════════════════════════════════════════════
# 5. test_bid_accepted_triggers_anti_snipe_when_under_180s
# ═══════════════════════════════════════════════════════════════════

class TestAntiSnipeUnder180:
    @pytest.mark.asyncio
    async def test_bid_accepted_triggers_anti_snipe_when_under_180s(self, fake_redis):
        """When root key TTL <= 180s, accepted bid triggers anti-snipe:
        - result.extended == True
        - result.new_ttl == original_ttl + 180
        - extension_ct incremented in Redis
        """
        BidLuaScripts.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=10000, min_increment=2500, ttl=120,
        )

        bidder = str(uuid4())
        result = await place_bid(auction_id, bidder, 15000, fake_redis)

        assert result.accepted
        assert result.extended is True
        assert result.new_ttl == 300  # 120 + 180

        ext_ct = await fake_redis.get(_k(auction_id, "extension_ct"))
        assert ext_ct == "1"

    @pytest.mark.asyncio
    async def test_anti_snipe_at_exactly_180s(self, fake_redis):
        """TTL == 180s still triggers anti-snipe (Lua uses <= 180)."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=10000, min_increment=2500, ttl=180,
        )

        bidder = str(uuid4())
        result = await place_bid(auction_id, bidder, 15000, fake_redis)

        assert result.extended is True
        assert result.new_ttl == 360  # 180 + 180

    @pytest.mark.asyncio
    async def test_extensions_stack_then_stop(self, fake_redis):
        """First bid under threshold extends (TTL 100→280).
        Second bid at TTL 280 > 180 → no extension."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=10000, min_increment=1000, ttl=100,
        )

        b1 = str(uuid4())
        r1 = await place_bid(auction_id, b1, 12000, fake_redis)
        assert r1.extended is True
        assert r1.new_ttl == 280  # 100 + 180

        # TTL is now 280 which is > 180 — next bid should NOT extend
        b2 = str(uuid4())
        r2 = await place_bid(auction_id, b2, 14000, fake_redis)
        assert r2.extended is False

        ext_ct = await fake_redis.get(_k(auction_id, "extension_ct"))
        assert ext_ct == "1"


# ═══════════════════════════════════════════════════════════════════
# 6. test_bid_accepted_no_extension_when_over_180s
# ═══════════════════════════════════════════════════════════════════

class TestNoExtensionOver180:
    @pytest.mark.asyncio
    async def test_bid_accepted_no_extension_when_over_180s(self, fake_redis):
        """When root key TTL > 180s, bid does NOT trigger anti-snipe:
        - result.extended == False
        - result.new_ttl == original_ttl (unchanged)
        - extension_ct == 0
        """
        BidLuaScripts.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=10000, min_increment=2500, ttl=7200,
        )

        bidder = str(uuid4())
        result = await place_bid(auction_id, bidder, 15000, fake_redis)

        assert result.accepted
        assert result.extended is False
        assert result.new_ttl == 7200

        ext_ct = await fake_redis.get(_k(auction_id, "extension_ct"))
        assert ext_ct == "0"

    @pytest.mark.asyncio
    async def test_ttl_181_no_extension(self, fake_redis):
        """TTL == 181s is above the 180s threshold → no extension."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=10000, min_increment=2500, ttl=181,
        )

        bidder = str(uuid4())
        result = await place_bid(auction_id, bidder, 15000, fake_redis)

        assert result.extended is False
        assert result.new_ttl == 181


# ═══════════════════════════════════════════════════════════════════
# 7. test_script_reloads_on_noscript_error
# ═══════════════════════════════════════════════════════════════════

class TestNoscriptReload:
    @pytest.mark.asyncio
    async def test_script_reloads_on_noscript_error(self, fake_redis):
        """If SHA is evicted (Redis restart), NOSCRIPT triggers reload + retry.
        The bid still succeeds — transparent to the caller."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(fake_redis)

        # Load normally first
        await BidLuaScripts.load(fake_redis)
        assert BidLuaScripts._script_sha is not None
        assert len(BidLuaScripts._script_sha) == 40  # SHA1 hex

        # Simulate NOSCRIPT by clearing the script store
        fake_redis._scripts.clear()

        bidder = str(uuid4())
        result = await place_bid(auction_id, bidder, 20000, fake_redis)

        # Should succeed after automatic reload
        assert result.accepted
        assert result.new_price == 20000

        # SHA was re-loaded
        assert BidLuaScripts._script_sha is not None

    @pytest.mark.asyncio
    async def test_sha_cached_after_load(self, fake_redis):
        """load() caches SHA; second call reuses it."""
        BidLuaScripts.reset()
        await BidLuaScripts.load(fake_redis)
        sha1 = BidLuaScripts._script_sha

        await BidLuaScripts.load(fake_redis)
        sha2 = BidLuaScripts._script_sha

        # load() overwrites but SHA is deterministic → same value
        assert sha1 == sha2

    @pytest.mark.asyncio
    async def test_reset_clears_cached_sha(self, fake_redis):
        """reset() clears the cached SHA."""
        BidLuaScripts.reset()
        await BidLuaScripts.load(fake_redis)
        assert BidLuaScripts._script_sha is not None

        BidLuaScripts.reset()
        assert BidLuaScripts._script_sha is None


# ═══════════════════════════════════════════════════════════════════
# Additional: BidResult dataclass + state mutation verification
# ═══════════════════════════════════════════════════════════════════

class TestBidResultFields:
    @pytest.mark.asyncio
    async def test_accepted_result_shape(self, fake_redis):
        """Accepted BidResult has new_price, extended, new_ttl set.
        rejection_reason and min_required are None."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(fake_redis, ttl=7200)

        bidder = str(uuid4())
        result = await place_bid(auction_id, bidder, 20000, fake_redis)

        assert isinstance(result, BidResult)
        assert result.accepted is True
        assert result.new_price == 20000
        assert result.extended is False
        assert result.new_ttl == 7200
        assert result.rejection_reason is None
        assert result.min_required is None

    @pytest.mark.asyncio
    async def test_rejected_result_shape(self, fake_redis):
        """Rejected BidResult has rejection_reason.
        min_required only set for BID_TOO_LOW."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=10000, min_increment=2500,
        )

        bidder = str(uuid4())
        result = await place_bid(auction_id, bidder, 5000, fake_redis)

        assert isinstance(result, BidResult)
        assert result.accepted is False
        assert result.new_price == 0
        assert result.rejection_reason == "BID_TOO_LOW"
        assert result.min_required == 12500


class TestSequentialBidding:
    @pytest.mark.asyncio
    async def test_bidding_war(self, fake_redis):
        """Sequential bids must each meet the new price + increment.
        Validates full state progression across multiple bids."""
        BidLuaScripts.reset()
        auction_id = await _setup_auction(
            fake_redis, current_price=10000, min_increment=1000,
        )

        b1, b2, b3 = str(uuid4()), str(uuid4()), str(uuid4())

        r1 = await place_bid(auction_id, b1, 15000, fake_redis)
        assert r1.accepted

        # b2 at 15999 → too low (need >= 16000)
        r2 = await place_bid(auction_id, b2, 15999, fake_redis)
        assert not r2.accepted
        assert r2.min_required == 16000

        r3 = await place_bid(auction_id, b2, 16000, fake_redis)
        assert r3.accepted

        r4 = await place_bid(auction_id, b3, 20000, fake_redis)
        assert r4.accepted

        assert await fake_redis.get(_k(auction_id, "price")) == "20000"
        assert await fake_redis.get(_k(auction_id, "bid_count")) == "3"
        assert await fake_redis.get(_k(auction_id, "last_bidder")) == b3
