"""
Price Oracle — FR-AI-001.

Queries ClickHouse for comparable completed auctions (same category,
similar condition, sold in last 90 days), runs scikit-learn model
for price prediction, caches results in Redis for 1 hour.

Phase 1: GradientBoostingRegressor (scikit-learn)
Phase 2: XGBoost
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

# Condition encoding — ordinal scale for ML features
CONDITION_MAP: dict[str, int] = {
    "new": 5,
    "like_new": 4,
    "good": 3,
    "fair": 2,
    "for_parts": 1,
}

# Confidence thresholds based on comparable count
CONFIDENCE_HIGH_MIN = 20
CONFIDENCE_MEDIUM_MIN = 10


# ── ClickHouse queries ────────────────────────────────────────

def _query_comparables(
    category_id: int,
    condition: str,
    brand: str | None = None,
) -> list[dict]:
    """Query ClickHouse for comparable completed auctions.

    Returns rows with: final_price, condition, brand_id, days_since_sold.
    Falls back to empty list if ClickHouse is unavailable.
    """
    from app.core.clickhouse import query_rows

    condition_encoded = CONDITION_MAP.get(condition, 3)
    lookback = settings.PRICE_ORACLE_LOOKBACK_DAYS

    # Base query: same category, sold in last N days
    sql = """
        SELECT
            final_price,
            condition,
            brand_id,
            dateDiff('day', sold_at, now()) AS days_since_sold
        FROM completed_auctions
        WHERE category_id = %(category_id)s
          AND sold_at >= now() - INTERVAL %(lookback)s DAY
          AND final_price > 0
    """
    params: dict = {
        "category_id": category_id,
        "lookback": lookback,
    }

    # Condition similarity: same or ±1 ordinal rank
    sql += """
          AND condition_rank BETWEEN %(cond_low)s AND %(cond_high)s
    """
    params["cond_low"] = max(1, condition_encoded - 1)
    params["cond_high"] = min(5, condition_encoded + 1)

    if brand:
        sql += "  AND brand = %(brand)s\n"
        params["brand"] = brand

    sql += "ORDER BY sold_at DESC LIMIT 200"

    return query_rows(sql, params)


# ── ML model ──────────────────────────────────────────────────

def _load_model():
    """Load the trained scikit-learn model from disk, or return None."""
    model_path = settings.PRICE_ORACLE_MODEL_PATH
    if not os.path.exists(model_path):
        return None
    try:
        import joblib
        return joblib.load(model_path)
    except Exception:
        logger.warning("Failed to load price oracle model from %s", model_path)
        return None


def _predict_with_model(
    model,
    category_id: int,
    condition: str,
    brand_id: int,
    days_since_sold_median: float,
) -> dict | None:
    """Run the ML model and return price predictions."""
    try:
        condition_encoded = CONDITION_MAP.get(condition, 3)
        features = np.array([[
            category_id,
            condition_encoded,
            brand_id,
            days_since_sold_median,
        ]])
        predicted = model.predict(features)[0]
        return {"predicted_price": float(predicted)}
    except Exception:
        logger.exception("Model prediction failed")
        return None


def _compute_statistics(comparables: list[dict]) -> dict:
    """Compute price statistics from comparable sales."""
    prices = [float(c["final_price"]) for c in comparables]
    prices_arr = np.array(prices)

    return {
        "median": float(np.median(prices_arr)),
        "mean": float(np.mean(prices_arr)),
        "p10": float(np.percentile(prices_arr, 10)),
        "p90": float(np.percentile(prices_arr, 90)),
        "std": float(np.std(prices_arr)),
        "min": float(np.min(prices_arr)),
        "max": float(np.max(prices_arr)),
    }


def _determine_confidence(comparable_count: int) -> str:
    """Map comparable count to confidence level."""
    if comparable_count >= CONFIDENCE_HIGH_MIN:
        return "high"
    if comparable_count >= CONFIDENCE_MEDIUM_MIN:
        return "medium"
    if comparable_count >= settings.PRICE_ORACLE_MIN_COMPARABLES:
        return "low"
    return "none"


# ── Redis cache ───────────────────────────────────────────────

def _cache_key(category_id: int, condition: str, brand: str | None) -> str:
    """Build Redis cache key for price oracle result."""
    brand_part = brand or "_"
    return f"price_oracle:{category_id}:{condition}:{brand_part}"


async def _get_cached(redis, key: str) -> dict | None:
    """Retrieve cached price oracle result from Redis."""
    raw = await redis.get(key)
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return None


async def _set_cached(redis, key: str, data: dict) -> None:
    """Cache price oracle result in Redis with TTL."""
    await redis.setex(
        key,
        settings.PRICE_ORACLE_CACHE_TTL,
        json.dumps(data),
    )


# ── Main entry point ──────────────────────────────────────────

async def get_price_estimate(
    category_id: int,
    condition: str,
    brand: str | None,
    redis,
) -> dict:
    """Get price estimate for a category/condition/brand combination.

    Flow:
    1. Check Redis cache (1h TTL)
    2. Query ClickHouse for comparables (last 90 days)
    3. If enough comparables: compute statistics + optional ML prediction
    4. Return price range, suggested start, confidence level
    5. Cache result in Redis

    Returns dict with: price_low, price_high, median, suggested_start,
    confidence, comparable_count. Nullable prices if no comparables.
    """
    # 1. Check cache
    cache_key = _cache_key(category_id, condition, brand)
    cached = await _get_cached(redis, cache_key)
    if cached is not None:
        return cached

    # 2. Query ClickHouse
    comparables = _query_comparables(category_id, condition, brand)
    comparable_count = len(comparables)
    confidence = _determine_confidence(comparable_count)

    # 3. Not enough data → return nulls
    if confidence == "none":
        result = {
            "price_low": None,
            "price_high": None,
            "median": None,
            "suggested_start": None,
            "confidence": "none",
            "comparable_count": comparable_count,
        }
        await _set_cached(redis, cache_key, result)
        return result

    # 4. Compute statistics from comparables
    stats = _compute_statistics(comparables)

    # Use P10/P90 as price range
    price_low = round(stats["p10"], 3)
    price_high = round(stats["p90"], 3)
    median = round(stats["median"], 3)

    # Try ML model for suggested_start
    suggested_start = median  # Default fallback
    model = _load_model()
    if model is not None:
        days_since_sold_values = [
            c.get("days_since_sold", 0) for c in comparables
        ]
        days_median = float(np.median(days_since_sold_values)) if days_since_sold_values else 0.0
        brand_id = hash(brand or "") % 10000  # Simple brand encoding
        prediction = _predict_with_model(
            model, category_id, condition, brand_id, days_median,
        )
        if prediction:
            # Use ML prediction as suggested_start, clamped to price range
            suggested_start = round(
                max(price_low, min(price_high, prediction["predicted_price"])),
                3,
            )

    result = {
        "price_low": price_low,
        "price_high": price_high,
        "median": median,
        "suggested_start": round(suggested_start, 3),
        "confidence": confidence,
        "comparable_count": comparable_count,
    }

    # 5. Cache
    await _set_cached(redis, cache_key, result)
    return result


# ── Model training ────────────────────────────────────────────

def train_price_model() -> dict:
    """Train (or retrain) the price oracle model from ClickHouse data.

    Called weekly by Celery Beat task.
    Phase 1: GradientBoostingRegressor (scikit-learn)
    Phase 2: XGBoost

    Returns training metrics dict.
    """
    from app.core.clickhouse import query_rows

    logger.info("Starting price oracle model training")

    # Fetch all completed auctions from ClickHouse
    rows = query_rows("""
        SELECT
            category_id,
            condition_rank,
            brand_id,
            dateDiff('day', sold_at, now()) AS days_since_sold,
            final_price
        FROM completed_auctions
        WHERE sold_at >= now() - INTERVAL 365 DAY
          AND final_price > 0
        LIMIT 100000
    """)

    if len(rows) < 50:
        logger.warning("Not enough training data: %d rows", len(rows))
        return {"status": "skipped", "reason": "insufficient_data", "rows": len(rows)}

    # Build feature matrix
    X = np.array([
        [
            r["category_id"],
            r["condition_rank"],
            r.get("brand_id", 0),
            r["days_since_sold"],
        ]
        for r in rows
    ], dtype=np.float64)
    y = np.array([r["final_price"] for r in rows], dtype=np.float64)

    # Train/test split
    from sklearn.model_selection import train_test_split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42,
    )

    # Phase 1: GradientBoostingRegressor
    from sklearn.ensemble import GradientBoostingRegressor
    model = GradientBoostingRegressor(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.1,
        random_state=42,
    )
    model.fit(X_train, y_train)

    # Evaluate
    from sklearn.metrics import mean_absolute_error, r2_score
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    # Save model
    import joblib
    model_path = settings.PRICE_ORACLE_MODEL_PATH
    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)

    metrics = {
        "status": "trained",
        "training_rows": len(rows),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "mae": round(mae, 3),
        "r2": round(r2, 4),
        "model_path": model_path,
    }
    logger.info("Price oracle model trained: %s", metrics)
    return metrics
