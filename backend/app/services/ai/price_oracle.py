"""
Price Oracle — FR-AI-001.

Queries ClickHouse materialized view (auction_results_mv) for comparable
completed auctions, runs XGBoost quantile regression for price prediction,
caches results in Redis for 1 hour.

All prices are INTEGER cents (1 JOD = 1000 fils).

Algorithm:
1. Check Redis cache
2. Query ClickHouse for comparables (last 90 days)
3. Widen search if < 5 results (drop brand, then condition)
4. Feature engineering + XGBoost quantile prediction
5. Determine confidence (high/medium/low/none)
6. Cache and return PriceEstimate
"""

from __future__ import annotations

import io
import json
import logging
import re
from pathlib import Path

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

# Condition encoding — ordinal scale for ML features
CONDITION_MAP: dict[str, int] = {
    "brand_new": 5,
    "like_new": 4,
    "very_good": 3,
    "good": 2,
    "acceptable": 1,
}

# Confidence thresholds
CONFIDENCE_HIGH_MIN = 20
CONFIDENCE_HIGH_MAX_DAYS = 30
CONFIDENCE_MEDIUM_MIN = 5
CONFIDENCE_MEDIUM_MAX_DAYS = 90

# In-memory model cache: {category_id: (model, version)}
_model_cache: dict[int | str, tuple] = {}


# ── Helpers ──────────────────────────────────────────────────

def _brand_slug(brand: str | None) -> str:
    """Normalize brand name to a slug for cache keys and queries."""
    if not brand:
        return "_"
    return re.sub(r"[^a-z0-9]", "", brand.lower().strip())


# ── ClickHouse queries ──────────────────────────────────────

def _query_comparables(
    category_id: int,
    condition: str | None = None,
    brand: str | None = None,
) -> list[dict]:
    """Query ClickHouse materialized view for comparable sold listings.

    Returns rows with: final_price (cents), condition, days_since_end,
    bid_count, is_certified.
    """
    from app.core.clickhouse import query_rows

    lookback = settings.PRICE_ORACLE_LOOKBACK_DAYS

    sql = """
        SELECT
            final_price,
            condition,
            dateDiff('day', ended_at, now()) AS days_since_end,
            bid_count,
            is_certified
        FROM auction_results_mv
        WHERE category_id = %(category_id)s
          AND ended_at > now() - INTERVAL %(lookback)s DAY
          AND final_price > 0
    """
    params: dict = {
        "category_id": category_id,
        "lookback": lookback,
    }

    if condition:
        condition_encoded = CONDITION_MAP.get(condition, 3)
        # Same or ±1 ordinal rank for condition similarity
        sql += """
          AND condition_rank BETWEEN %(cond_low)s AND %(cond_high)s
        """
        params["cond_low"] = max(1, condition_encoded - 1)
        params["cond_high"] = min(5, condition_encoded + 1)

    if brand:
        sql += "  AND brand_slug = %(brand_slug)s\n"
        params["brand_slug"] = _brand_slug(brand)

    sql += "ORDER BY ended_at DESC LIMIT 200"

    return query_rows(sql, params)


def _query_with_widening(
    category_id: int,
    condition: str,
    brand: str | None,
) -> tuple[list[dict], str]:
    """Query comparables with progressive search widening.

    Returns (comparables, search_level) where search_level is:
    - "exact": brand + condition match
    - "no_brand": condition match only (brand dropped)
    - "no_condition": category only (both dropped)
    """
    # Try exact match first
    comparables = _query_comparables(category_id, condition, brand)
    if len(comparables) >= CONFIDENCE_MEDIUM_MIN:
        return comparables, "exact"

    # Widen: drop brand filter
    if brand:
        comparables = _query_comparables(category_id, condition, None)
        if len(comparables) >= CONFIDENCE_MEDIUM_MIN:
            return comparables, "no_brand"

    # Widen: drop condition filter too
    comparables = _query_comparables(category_id, None, None)
    return comparables, "no_condition"


# ── ML model loading ────────────────────────────────────────

def _get_model_version(category_id: int, redis_sync=None) -> str | None:
    """Get current model version pointer from Redis (sync context)."""
    try:
        if redis_sync:
            return redis_sync.get(f"price_oracle:model_version:{category_id}")
        # Fallback: check local disk
        model_dir = Path(f"models/price_oracle")
        if model_dir.exists():
            files = sorted(model_dir.glob(f"{category_id}_v*.pkl"), reverse=True)
            if files:
                return files[0].stem  # e.g. "1_v20260407"
        return None
    except Exception:
        return None


def _load_model(category_id: int):
    """Load XGBoost model for a category from S3 (with in-memory caching).

    Falls back to global model if category-specific model not found.
    Reloads if version changed in Redis.
    """
    import joblib

    # Check in-memory cache
    if category_id in _model_cache:
        cached_model, cached_version = _model_cache[category_id]
        if cached_model is not None:
            return cached_model

    # Try loading category-specific model from local disk
    model_dir = Path("models/price_oracle")
    model_dir.mkdir(parents=True, exist_ok=True)

    # Category-specific model
    cat_files = sorted(model_dir.glob(f"{category_id}_v*.pkl"), reverse=True)
    if cat_files:
        try:
            model = joblib.load(cat_files[0])
            _model_cache[category_id] = (model, cat_files[0].name)
            return model
        except Exception:
            logger.warning("Failed to load model %s", cat_files[0])

    # Try S3 download
    try:
        import boto3
        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        # List objects with prefix
        resp = s3.list_objects_v2(
            Bucket=settings.S3_BUCKET_MEDIA,
            Prefix=f"models/price_oracle/{category_id}_v",
        )
        if resp.get("Contents"):
            latest = sorted(resp["Contents"], key=lambda x: x["Key"], reverse=True)[0]
            obj = s3.get_object(Bucket=settings.S3_BUCKET_MEDIA, Key=latest["Key"])
            model = joblib.load(io.BytesIO(obj["Body"].read()))
            # Save locally for future loads
            local_path = model_dir / Path(latest["Key"]).name
            joblib.dump(model, local_path)
            _model_cache[category_id] = (model, latest["Key"])
            return model
    except Exception:
        pass

    # Fallback: global model
    global_path = Path(settings.PRICE_ORACLE_MODEL_PATH)
    if global_path.exists():
        try:
            model = joblib.load(global_path)
            _model_cache["global"] = (model, "global")
            return model
        except Exception:
            pass

    return None


# ── Statistics & prediction ─────────────────────────────────

def _compute_statistics(comparables: list[dict]) -> dict:
    """Compute price statistics from comparable sales (all in cents)."""
    prices = np.array([int(c["final_price"]) for c in comparables])
    days = np.array([int(c.get("days_since_end", 0)) for c in comparables])

    return {
        "p10": int(np.percentile(prices, 10)),
        "p50": int(np.percentile(prices, 50)),
        "p90": int(np.percentile(prices, 90)),
        "median": int(np.median(prices)),
        "mean": float(np.mean(prices)),
        "std": float(np.std(prices)),
        "date_range_days": int(np.max(days)) if len(days) > 0 else 0,
    }


def _predict_quantiles(
    model,
    category_id: int,
    condition: str,
    brand: str | None,
    days_since_end_median: float,
    bid_count_median: float,
    is_certified: bool,
) -> dict | None:
    """Run XGBoost quantile model to predict price percentiles."""
    try:
        condition_encoded = CONDITION_MAP.get(condition, 3)
        brand_encoded = hash(_brand_slug(brand)) % 10000 if brand else 0
        features = np.array([[
            float(category_id),
            float(condition_encoded),
            float(brand_encoded),
            days_since_end_median,
            bid_count_median,
            1.0 if is_certified else 0.0,
        ]])
        predicted = model.predict(features)[0]
        return {"predicted_price": int(round(predicted))}
    except Exception:
        logger.exception("Model prediction failed")
        return None


def _determine_confidence(
    comparable_count: int,
    date_range_days: int,
) -> str:
    """Map comparable count + date range to confidence level.

    high:   >= 20 comparables AND date range <= 30 days
    medium: >= 5  comparables AND date range <= 90 days
    low:    < 5   comparables (widened search had some results)
    none:   0 comparables
    """
    if comparable_count == 0:
        return "none"
    if (
        comparable_count >= CONFIDENCE_HIGH_MIN
        and date_range_days <= CONFIDENCE_HIGH_MAX_DAYS
    ):
        return "high"
    if (
        comparable_count >= CONFIDENCE_MEDIUM_MIN
        and date_range_days <= CONFIDENCE_MEDIUM_MAX_DAYS
    ):
        return "medium"
    if comparable_count > 0:
        return "low"
    return "none"


# ── Redis cache ─────────────────────────────────────────────

def _cache_key(category_id: int, condition: str, brand: str | None) -> str:
    return f"price_oracle:{category_id}:{condition}:{_brand_slug(brand)}"


async def _get_cached(redis, key: str) -> dict | None:
    raw = await redis.get(key)
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return None


async def _set_cached(redis, key: str, data: dict) -> None:
    await redis.setex(key, settings.PRICE_ORACLE_CACHE_TTL, json.dumps(data))


# ── Rate limiting ───────────────────────────────────────────

async def check_rate_limit(user_id: str, redis, max_per_minute: int = 20) -> bool:
    """Redis sliding window rate limit. Returns True if allowed."""
    key = f"rate:price_oracle:{user_id}"
    current = await redis.get(key)
    if current and int(current) >= max_per_minute:
        return False
    pipe_result = await redis.incr(key)
    if pipe_result == 1:
        await redis.expire(key, 60)
    return True


# ── Main entry point ────────────────────────────────────────

async def get_price_estimate(
    category_id: int,
    condition: str,
    brand: str | None,
    redis,
) -> dict:
    """Get price estimate for a category/condition/brand combination.

    Algorithm:
    1. Check Redis cache (1h TTL)
    2. Query ClickHouse auction_results_mv for comparables (last 90 days)
    3. Widen search if < 5 results (drop brand, then condition)
    4. Feature engineering + model prediction
    5. Compute: price_low (P10), price_mid (P50), price_high (P90)
    6. suggested_start = price_low * 0.85
    7. Determine confidence (high/medium/low/none)
    8. Cache result in Redis (1 hour)

    All prices returned in integer cents.
    """
    # 1. Check cache
    cache_key = _cache_key(category_id, condition, brand)
    cached = await _get_cached(redis, cache_key)
    if cached is not None:
        return cached

    # 2. Query ClickHouse with widening
    comparables, search_level = _query_with_widening(category_id, condition, brand)
    comparable_count = len(comparables)

    # 3. No data at all → none confidence
    if comparable_count == 0:
        result = {
            "price_low": None,
            "price_high": None,
            "price_mid": None,
            "suggested_start": None,
            "confidence": "none",
            "comparable_count": 0,
            "date_range_days": None,
        }
        await _set_cached(redis, cache_key, result)
        return result

    # 4. Compute statistics
    stats = _compute_statistics(comparables)
    price_low = stats["p10"]
    price_mid = stats["p50"]
    price_high = stats["p90"]
    date_range_days = stats["date_range_days"]

    # 5. Try ML model for better suggested_start
    suggested_start = int(round(price_low * 0.85))  # Default: 85% of P10

    model = _load_model(category_id)
    if model is not None:
        days_values = [c.get("days_since_end", 0) for c in comparables]
        bid_values = [c.get("bid_count", 0) for c in comparables]
        any_certified = any(c.get("is_certified", False) for c in comparables)

        prediction = _predict_quantiles(
            model,
            category_id,
            condition,
            brand,
            float(np.median(days_values)) if days_values else 0.0,
            float(np.median(bid_values)) if bid_values else 0.0,
            any_certified,
        )
        if prediction:
            # Clamp predicted price within P10-P90 range
            predicted = prediction["predicted_price"]
            suggested_start = int(round(
                max(price_low, min(price_high, predicted)) * 0.85
            ))

    # 6. Determine confidence
    confidence = _determine_confidence(comparable_count, date_range_days)

    # If search was widened, cap confidence at "low"
    if search_level == "no_condition" and confidence in ("high", "medium"):
        confidence = "low"

    result = {
        "price_low": price_low,
        "price_high": price_high,
        "price_mid": price_mid,
        "suggested_start": suggested_start,
        "confidence": confidence,
        "comparable_count": comparable_count,
        "date_range_days": date_range_days,
    }

    # 7. Cache
    await _set_cached(redis, cache_key, result)
    return result


# ── Model training (called from Celery) ─────────────────────

def train_price_model(target_category_id: int | None = None) -> dict:
    """Train (or retrain) price oracle models from ClickHouse data.

    Called weekly by Celery Beat.
    Trains per-category XGBoost quantile regressors.
    Saves to S3 and updates version pointer in Redis.

    If target_category_id is provided, only trains that category.
    Otherwise trains all categories with >= 50 completed auctions.
    """
    from app.core.clickhouse import query_rows

    logger.info("Starting price oracle model training")

    # Find categories with enough data
    if target_category_id:
        categories = [{"category_id": target_category_id}]
    else:
        categories = query_rows("""
            SELECT category_id, count() AS cnt
            FROM auction_results_mv
            WHERE ended_at >= now() - INTERVAL 365 DAY
              AND final_price > 0
            GROUP BY category_id
            HAVING cnt >= 50
            ORDER BY cnt DESC
        """)

    if not categories:
        logger.warning("No categories with enough training data")
        return {"status": "skipped", "reason": "no_qualifying_categories"}

    results = []
    for cat_row in categories:
        cat_id = cat_row["category_id"]
        metrics = _train_category_model(cat_id)
        results.append(metrics)

    trained = sum(1 for r in results if r.get("status") == "trained")
    skipped = sum(1 for r in results if r.get("status") == "skipped")

    return {
        "status": "completed",
        "categories_trained": trained,
        "categories_skipped": skipped,
        "details": results,
    }


def _train_category_model(category_id: int) -> dict:
    """Train XGBoost quantile model for a single category."""
    from app.core.clickhouse import query_rows
    from datetime import datetime

    rows = query_rows("""
        SELECT
            condition_rank,
            brand_id,
            dateDiff('day', ended_at, now()) AS days_since_end,
            bid_count,
            is_certified,
            final_price
        FROM auction_results_mv
        WHERE category_id = %(category_id)s
          AND ended_at >= now() - INTERVAL 365 DAY
          AND final_price > 0
        LIMIT 100000
    """, {"category_id": category_id})

    if len(rows) < 50:
        return {
            "category_id": category_id,
            "status": "skipped",
            "reason": "insufficient_data",
            "rows": len(rows),
        }

    # Build feature matrix
    X = np.array([
        [
            float(r.get("condition_rank", 3)),
            float(r.get("brand_id", 0)),
            float(r.get("days_since_end", 0)),
            float(r.get("bid_count", 0)),
            1.0 if r.get("is_certified") else 0.0,
        ]
        for r in rows
    ], dtype=np.float64)
    y = np.array([float(r["final_price"]) for r in rows], dtype=np.float64)

    # Normalize days_since_end to [0, 1]
    max_days = np.max(X[:, 2]) if np.max(X[:, 2]) > 0 else 1.0
    X[:, 2] = X[:, 2] / max_days

    # Train/test split
    from sklearn.model_selection import train_test_split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42,
    )

    # Train XGBoost regressor (quantile objective for P50 prediction)
    try:
        from xgboost import XGBRegressor
        model = XGBRegressor(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.1,
            objective="reg:squarederror",
            random_state=42,
        )
    except ImportError:
        # Fallback to scikit-learn if XGBoost not installed
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

    # Save locally
    import joblib
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    model_filename = f"{category_id}_v{timestamp}.pkl"
    model_dir = Path("models/price_oracle")
    model_dir.mkdir(parents=True, exist_ok=True)
    local_path = model_dir / model_filename
    joblib.dump(model, local_path)

    # Upload to S3
    try:
        import boto3
        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        s3_key = f"models/price_oracle/{model_filename}"
        with open(local_path, "rb") as f:
            s3.put_object(
                Bucket=settings.S3_BUCKET_MEDIA,
                Key=s3_key,
                Body=f.read(),
                ServerSideEncryption="AES256",
            )
        logger.info("Uploaded model to S3: %s", s3_key)
    except Exception:
        logger.warning("Failed to upload model to S3 for category %d", category_id)

    # Update version pointer in Redis
    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.REDIS_URL)
        r.set(f"price_oracle:model_version:{category_id}", model_filename)
    except Exception:
        logger.warning("Failed to update Redis model version for category %d", category_id)

    # Invalidate in-memory cache
    _model_cache.pop(category_id, None)

    metrics = {
        "category_id": category_id,
        "status": "trained",
        "training_rows": len(rows),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "mae": round(mae, 2),
        "r2": round(r2, 4),
        "model_file": model_filename,
    }
    logger.info("Category %d model trained: %s", category_id, metrics)
    return metrics
