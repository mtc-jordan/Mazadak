"""Fraud scoring service — rule-based MVP heuristics.

Returns a risk score 0-100 with explanatory risk factors.
"""

from __future__ import annotations

import logging

from app.models.schemas import FraudScoreResponse

logger = logging.getLogger(__name__)

# Thresholds (JOD cents)
HIGH_BID_THRESHOLD = 1_000_000    # 10,000 JOD — unusually high bid
VERY_HIGH_BID_THRESHOLD = 5_000_000  # 50,000 JOD — very high bid


async def score_fraud(
    user_id: str,
    auction_id: str,
    bid_amount: float,
) -> FraudScoreResponse:
    """Compute a fraud risk score based on rule-based heuristics.

    MVP implementation: primarily checks bid amount anomalies.
    Future: integrate user history, bidding patterns, device fingerprinting.
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

    # ---- Placeholder for future enrichment --------------------------------
    # In production these would query user history from the backend:
    # - New account age < 24h
    # - Multiple rapid bids on same auction
    # - Bid significantly above current price
    # - Device/IP anomalies

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
