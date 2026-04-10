"""
AI Celery tasks — FR-AI-001 model retraining.

Weekly retrain of per-category Price Oracle XGBoost models.
Scheduled via Celery Beat: every Monday 3am Amman time (UTC+3 → 00:00 UTC).
"""

from __future__ import annotations

import logging

from app.core.celery import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.retrain_price_model", bind=True, max_retries=2)
def retrain_price_model(self, category_id: int | None = None) -> dict:
    """Weekly retraining of Price Oracle XGBoost models.

    For each category with >= 50 completed auctions:
    - Pull training data from ClickHouse (all time, up to 100k rows)
    - Train XGBRegressor (quantile objective)
    - Save to S3 as models/price_oracle/{category_id}_v{timestamp}.pkl
    - Update version pointer in Redis

    If category_id is provided, only trains that specific category.
    """
    logger.info(
        "Starting price oracle model retrain%s",
        f" for category {category_id}" if category_id else " (all categories)",
    )

    try:
        from app.services.ai.price_oracle import train_price_model
        metrics = train_price_model(target_category_id=category_id)
        logger.info("Price oracle retrain complete: %s", metrics)
        return metrics
    except Exception as exc:
        logger.exception("Price oracle retrain failed")
        raise self.retry(exc=exc, countdown=600)  # retry in 10 min
