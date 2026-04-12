"""Fraud scoring service — rule-based MVP heuristics.

Returns a risk score 0-100 with explanatory risk factors.
Rules: rapid bidding, new account, high-value, round numbers.
"""

from __future__ import annotations

import logging

import redis.asyncio as redis

from app.core.config import settings
from app.models.schemas import FraudScoreResponse

logger = logging.getLogger(__name__)

# Thresholds (JOD cents)
HIGH_BID_THRESHOLD = 1_000_000      # 10,000 JOD — unusually high bid
VERY_HIGH_BID_THRESHOLD = 5_000_000  # 50,000 JOD — very high bid

# Rapid bidding: max bids in a sliding window
RAPID_BID_WINDOW_SECONDS = 60
RAPID_BID_MAX = 5  # More than 5 bids per minute is suspicious

_redis_pool: redis.Redis | None = None


async def _get_redis() -> redis.Redis | None:
    global _redis_pool
    if _redis_pool is None:
        try:
            _redis_pool = redis.from_url(settings.REDIS_URL, decode_responses=True)
        except Exception:
            return None
    return _redis_pool


async def _check_rapid_bidding(user_id: str, auction_id: str) -> bool:
    """Check if user is bidding too rapidly on the same auction.

    Uses a Redis sorted set with timestamps to track recent bids.
    Returns True if rapid bidding is detected.
    """
    try:
        r = await _get_redis()
        if r is None:
            return False

        import time
        now = time.time()
        key = f"fraud:bids:{user_id}:{auction_id}"

        # Add current bid timestamp
        await r.zadd(key, {str(now): now})
        # Remove entries older than the window
        await r.zremrangebyscore(key, 0, now - RAPID_BID_WINDOW_SECONDS)
        # Set expiry so keys don't linger forever
        await r.expire(key, RAPID_BID_WINDOW_SECONDS * 2)
        # Count recent bids
        count = await r.zcard(key)
        return count > RAPID_BID_MAX
    except Exception:
        logger.debug("Redis unavailable for rapid bidding check")
        return False


async def _check_new_account(user_id: str) -> bool:
    """Check if the user account is very new (< 24 hours).

    Attempts to query the backend for account creation date.
    Returns False if the check cannot be performed (graceful degradation).
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"{settings.BACKEND_URL}/api/v1/admin/users/{user_id}",
            )
            if resp.status_code != 200:
                return False
            data = resp.json()
            created_at = data.get("created_at")
            if not created_at:
                return False

            from datetime import datetime, timezone
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
            return age_hours < 24
    except Exception:
        logger.debug("Could not check account age for user %s", user_id)
        return False


async def score_fraud(
    user_id: str,
    auction_id: str,
    bid_amount: float,
) -> FraudScoreResponse:
    """Compute a fraud risk score based on rule-based heuristics.

    MVP implementation checks:
    - Bid amount anomalies (high/very high values)
    - Round-number bids (automated bidding signal)
    - Rapid bidding (too many bids in a short window)
    - New account age (< 24 hours)

    Future: device fingerprinting, IP analysis, ML model.
    """
    score = 0.0
    risk_factors: list[str] = []

    # ---- Bid amount heuristics -------------------------------------------

    if bid_amount >= VERY_HIGH_BID_THRESHOLD:
        score += 40
        risk_factors.append(
            f"very_high_bid_amount:{bid_amount / 100:.0f}_JOD"
        )
    elif bid_amount >= HIGH_BID_THRESHOLD:
        score += 20
        risk_factors.append(
            f"high_bid_amount:{bid_amount / 100:.0f}_JOD"
        )

    if bid_amount <= 0:
        score += 50
        risk_factors.append("invalid_bid_amount:non_positive")

    # ---- Round-number heuristic ------------------------------------------
    # Bids that are exactly round numbers (multiples of 10,000 cents / 100 JOD)
    # can indicate automated bidding
    if bid_amount > 0 and bid_amount % 10_000 == 0:
        score += 5
        risk_factors.append("round_number_bid")

    # ---- Rapid bidding check ---------------------------------------------
    try:
        is_rapid = await _check_rapid_bidding(user_id, auction_id)
        if is_rapid:
            score += 25
            risk_factors.append(
                f"rapid_bidding:>{RAPID_BID_MAX}_bids_in_{RAPID_BID_WINDOW_SECONDS}s"
            )
    except Exception:
        logger.debug("Rapid bidding check failed — skipping")

    # ---- New account check -----------------------------------------------
    try:
        is_new = await _check_new_account(user_id)
        if is_new:
            score += 15
            risk_factors.append("new_account:<24h")
    except Exception:
        logger.debug("New account check failed — skipping")

    # Clamp
    score = min(100.0, max(0.0, score))

    logger.info(
        "Fraud score for user=%s auction=%s bid=%d: score=%.1f factors=%s",
        user_id,
        auction_id,
        bid_amount,
        score,
        risk_factors,
    )

    return FraudScoreResponse(
        score=score,
        risk_factors=risk_factors,
    )
