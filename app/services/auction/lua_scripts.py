"""
Atomic Lua scripts for auction engine — SDD §3.2.2.

Scripts are loaded once via SCRIPT LOAD and executed via EVALSHA.
This avoids retransmitting the script body on every bid, saving
bandwidth and parsing time under high concurrency.

Fallback: if Redis returns NOSCRIPT (e.g. after server restart),
the script is automatically reloaded and retried once.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# ── Bid validation Lua script ────────────────────────────────────
#
# KEYS[1] = auction:{id}       (Hash)
# ARGV[1] = user_id            (bidder)
# ARGV[2] = amount             (bid amount, string-encoded float)
#
# Reads min_increment directly from the Hash — no pre-fetch needed.
#
# Validation order (fail-fast, cheapest checks first):
#   1. status == ACTIVE         (single HGET)
#   2. user != seller           (single HGET, already fetched)
#   3. user not in banned_users (SISMEMBER, O(1) on Set)
#   4. amount > current_price + min_increment  (arithmetic)
#
# On accept: atomically SET current_price, SET last_bidder, HINCRBY bid_count.
# Returns: {'ACCEPTED'} or {'REJECTED', reason_code}

BID_VALIDATE_AND_PLACE = """
local key = KEYS[1]
local user_id = ARGV[1]
local amount = tonumber(ARGV[2])

-- Read all needed fields in one round-trip inside the script
local status = redis.call('HGET', key, 'status')
local seller_id = redis.call('HGET', key, 'seller_id')
local current_price = tonumber(redis.call('HGET', key, 'current_price'))
local min_increment = tonumber(redis.call('HGET', key, 'min_increment'))

-- 1. Auction must be ACTIVE
if status ~= 'ACTIVE' then
    return {'REJECTED', 'AUCTION_ENDED'}
end

-- 2. Seller cannot bid on own auction
if user_id == seller_id then
    return {'REJECTED', 'SELLER_CANNOT_BID'}
end

-- 3. Banned users cannot bid
if redis.call('SISMEMBER', 'banned_users', user_id) == 1 then
    return {'REJECTED', 'USER_BANNED'}
end

-- 4. Bid must exceed current price + minimum increment
if amount <= (current_price + min_increment) then
    return {'REJECTED', 'BID_TOO_LOW'}
end

-- All checks passed — atomically update state
redis.call('HSET', key, 'current_price', amount)
redis.call('HSET', key, 'last_bidder', user_id)
redis.call('HINCRBY', key, 'bid_count', 1)

return {'ACCEPTED'}
"""


class BidScript:
    """Manages the bid validation Lua script lifecycle.

    - load():    SCRIPT LOAD once, caches SHA in-process.
    - execute(): EVALSHA with automatic NOSCRIPT retry.

    Thread-safe: worst case two threads both call load() and get
    the same SHA back — harmless idempotent operation.
    """

    _sha: str | None = None

    @classmethod
    async def load(cls, redis: Redis) -> str:
        """Load the Lua script into Redis and cache the SHA1 digest."""
        if cls._sha is None:
            cls._sha = await redis.script_load(BID_VALIDATE_AND_PLACE)
            logger.info("Bid Lua script loaded, SHA=%s", cls._sha)
        return cls._sha

    @classmethod
    async def execute(
        cls,
        redis: Redis,
        auction_key: str,
        user_id: str,
        amount: float,
    ) -> tuple[str, str | None]:
        """Execute atomic bid validation + placement.

        Returns:
            (status, reason) — ('ACCEPTED', None) or ('REJECTED', 'BID_TOO_LOW')
        """
        sha = await cls.load(redis)

        try:
            result = await redis.evalsha(
                sha, 1, auction_key, user_id, str(amount),
            )
        except Exception as exc:
            # Handle NOSCRIPT: script evicted from cache after Redis restart
            if "NOSCRIPT" in str(exc):
                logger.warning("NOSCRIPT — reloading bid Lua script")
                cls._sha = None
                sha = await cls.load(redis)
                result = await redis.evalsha(
                    sha, 1, auction_key, user_id, str(amount),
                )
            else:
                raise

        status = result[0] if result else "REJECTED"
        reason = result[1] if len(result) > 1 else None
        return status, reason

    @classmethod
    def reset(cls) -> None:
        """Clear cached SHA — for testing or after Redis failover."""
        cls._sha = None
