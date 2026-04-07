"""
AI Celery tasks — FR-AI-001 model retraining.

Weekly retrain of the Price Oracle model from ClickHouse data.
"""

from __future__ import annotations

import logging

from app.core.celery import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.retrain_price_model", bind=True, max_retries=2)
def retrain_price_model(self) -> dict:
    """Weekly retraining of the Price Oracle scikit-learn model.

    Fetches completed auction data from ClickHouse (last 365 days),
    trains a GradientBoostingRegressor, saves to disk.

    Phase 1: scikit-learn GradientBoostingRegressor
    Phase 2: XGBoost
    """
    logger.info("Starting weekly price oracle model retrain")

    try:
        from app.services.ai.price_oracle import train_price_model
        metrics = train_price_model()
        logger.info("Price oracle retrain complete: %s", metrics)
        return metrics
    except Exception as exc:
        logger.exception("Price oracle retrain failed")
        raise self.retry(exc=exc, countdown=600)  # retry in 10 min
