"""
Atomic Lua bid validation engine — SDD §3.2.2.

The most critical file in the platform.  Every bid in every auction
runs through this single Lua script executed atomically inside Redis.
Zero race conditions allowed.

Scripts are loaded once via SCRIPT LOAD and executed via EVALSHA.
NOSCRIPT (e.g. after Redis restart) triggers automatic reload + retry.

Redis key schema (individual keys per auction field):
  KEYS[1] = auction:{id}:price         — current price (integer cents)
  KEYS[2] = auction:{id}:status        — ACTIVE | ENDED | CANCELLED
  KEYS[3] = auction:{id}:seller        — seller_id
  KEYS[4] = auction:{id}:last_bidder   — last bidder user_id
  KEYS[5] = auction:{id}:bid_count     — integer
  KEYS[6] = auction:{id}:banned_set    — SET of banned user_ids
  KEYS[7] = auction:{id}               — root TTL key (keyspace expiry)
  KEYS[8] = auction:{id}:extension_ct  — anti-snipe extension count
  KEYS[9] = auction:{id}:min_increment — min bid increment (integer cents)

  ARGV[1] = bid_amount   (integer cents as string)
  ARGV[2] = bidder_id    (user_id string)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


# ── BidResult dataclass ──────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class BidResult:
    """Typed result from the Lua bid validation script."""
    accepted: bool
    new_price: int = 0
    extended: bool = False
    new_ttl: Optional[int] = None
    rejection_reason: Optional[str] = None
    min_required: Optional[int] = None


# ── Bid validation Lua script ────────────────────────────────────
#
# Validation order (fail-fast, cheapest reads first):
#   1. status == ACTIVE           → AUCTION_NOT_ACTIVE
#   2. bidder != seller           → SELLER_CANNOT_BID
#   3. bidder not in banned_set   → BIDDER_BANNED
#   4. amount >= current + incr   → BID_TOO_LOW (returns min_bid)
#
# On accept: SET price, SET last_bidder, INCR bid_count.
# Anti-snipe: if root key TTL <= 180s, extend by 180s, INCR extension_ct.
#
# Returns:
#   ACCEPTED: {'ACCEPTED', bid_amount, 'EXTENDED'|'NORMAL', ttl}
#   REJECTED: {'REJECTED', reason}  or  {'REJECTED', 'BID_TOO_LOW', min_bid}

BID_VALIDATION_SCRIPT = """
local price_key    = KEYS[1]  -- auction:{id}:price
local status_key   = KEYS[2]  -- auction:{id}:status
local seller_key   = KEYS[3]  -- auction:{id}:seller
local last_key     = KEYS[4]  -- auction:{id}:last_bidder
local bids_key     = KEYS[5]  -- auction:{id}:bid_count
local banned_key   = KEYS[6]  -- auction:{id}:banned_set
local ttl_key      = KEYS[7]  -- auction:{id} (root key with TTL)
local ext_key      = KEYS[8]  -- auction:{id}:extension_ct

local bid_amount  = tonumber(ARGV[1])
local bidder_id   = ARGV[2]
local increment   = tonumber(redis.call('GET', KEYS[9]))  -- min_increment key

-- Check 1: Auction must be ACTIVE
local status = redis.call('GET', status_key)
if status ~= 'ACTIVE' then
  return {'REJECTED', 'AUCTION_NOT_ACTIVE'}
end

-- Check 2: Bidder cannot be the seller
local seller = redis.call('GET', seller_key)
if seller == bidder_id then
  return {'REJECTED', 'SELLER_CANNOT_BID'}
end

-- Check 3: Bidder not in banned set
local is_banned = redis.call('SISMEMBER', banned_key, bidder_id)
if is_banned == 1 then
  return {'REJECTED', 'BIDDER_BANNED'}
end

-- Check 4: Bid amount must exceed current price + min increment
local current_price = tonumber(redis.call('GET', price_key))
local min_bid = current_price + increment
if bid_amount < min_bid then
  return {'REJECTED', 'BID_TOO_LOW', tostring(min_bid)}
end

-- All checks passed — update atomically
redis.call('SET', price_key, bid_amount)
redis.call('SET', last_key, bidder_id)
redis.call('INCR', bids_key)

-- Anti-snipe: if TTL <= 180s, extend by 180s
local ttl = redis.call('TTL', ttl_key)
local extended = false
if ttl > 0 and ttl <= 180 then
  redis.call('EXPIRE', ttl_key, ttl + 180)
  redis.call('INCR', ext_key)
  extended = true
end

if extended then
  return {'ACCEPTED', tostring(bid_amount), 'EXTENDED', tostring(ttl + 180)}
else
  return {'ACCEPTED', tostring(bid_amount), 'NORMAL', tostring(ttl)}
end
"""


def _decode(value) -> str:
    """Decode bytes to str (real Redis returns bytes, FakeRedis returns str)."""
    return value.decode() if isinstance(value, bytes) else str(value)


class BidLuaScripts:
    """Manages the bid validation Lua script lifecycle.

    - load():         SCRIPT LOAD once at startup, caches SHA in-process.
    - validate_bid(): EVALSHA with automatic NOSCRIPT retry.
                      Returns a typed BidResult.

    Thread-safe: worst case two threads both call load() and get
    the same SHA back — harmless idempotent operation.
    """

    _script_sha: Optional[str] = None

    @classmethod
    async def load(cls, redis_client: Redis) -> None:
        """Load Lua script at startup using SCRIPT LOAD for EVALSHA."""
        cls._script_sha = await redis_client.script_load(BID_VALIDATION_SCRIPT)
        logger.info("bid_lua_script_loaded", extra={"sha": cls._script_sha})

    @classmethod
    async def validate_bid(
        cls,
        redis_client: Redis,
        auction_id: str,
        bid_amount: int,
        bidder_id: str,
    ) -> BidResult:
        """Execute atomic bid validation via EVALSHA.

        Returns a BidResult with acceptance status, new price, anti-snipe
        extension info, or rejection reason with minimum required bid.
        """
        keys = [
            f"auction:{auction_id}:price",         # KEYS[1]
            f"auction:{auction_id}:status",        # KEYS[2]
            f"auction:{auction_id}:seller",        # KEYS[3]
            f"auction:{auction_id}:last_bidder",   # KEYS[4]
            f"auction:{auction_id}:bid_count",     # KEYS[5]
            f"auction:{auction_id}:banned_set",    # KEYS[6]
            f"auction:{auction_id}",               # KEYS[7] — root TTL key
            f"auction:{auction_id}:extension_ct",  # KEYS[8]
            f"auction:{auction_id}:min_increment", # KEYS[9]
        ]
        args = [str(bid_amount), bidder_id]

        try:
            result = await redis_client.evalsha(
                cls._script_sha, len(keys), *keys, *args,
            )
        except Exception as exc:
            if "NOSCRIPT" in str(exc):
                # Script evicted from Redis — reload and retry once
                logger.warning("NOSCRIPT — reloading bid Lua script")
                await cls.load(redis_client)
                result = await redis_client.evalsha(
                    cls._script_sha, len(keys), *keys, *args,
                )
            else:
                raise

        return cls._parse_result(result)

    @classmethod
    def _parse_result(cls, result: list) -> BidResult:
        """Parse raw Lua return array into a typed BidResult.

        Real Redis returns bytes; FakeRedis returns str — _decode() handles both.
        """
        if not result:
            return BidResult(
                accepted=False,
                rejection_reason="UNKNOWN",
            )

        status = _decode(result[0])

        if status == "ACCEPTED":
            return BidResult(
                accepted=True,
                new_price=int(result[1]),
                extended=_decode(result[2]) == "EXTENDED",
                new_ttl=int(result[3]) if len(result) > 3 else None,
            )
        else:
            # REJECTED — only BID_TOO_LOW has a 3rd element (min_bid)
            return BidResult(
                accepted=False,
                rejection_reason=_decode(result[1]) if len(result) > 1 else "UNKNOWN",
                min_required=int(result[2]) if len(result) > 2 else None,
            )

    @classmethod
    def reset(cls) -> None:
        """Clear cached SHA — for testing or after Redis failover."""
        cls._script_sha = None
