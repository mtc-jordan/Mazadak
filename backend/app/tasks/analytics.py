"""Analytics Celery tasks — batch flush and table management."""

import logging

from app.core.celery import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.analytics.flush_analytics",
    bind=True,
    max_retries=0,  # Best-effort, no retries
)
def flush_analytics(self):
    """Flush buffered analytics events to ClickHouse.

    Runs every 30 seconds via beat. Events are dropped if ClickHouse
    is unavailable (analytics is best-effort, never blocks transactions).
    """
    from app.core.analytics import flush_events
    count = flush_events()
    if count:
        logger.info("Flushed %d analytics events", count)


@celery_app.task(
    name="app.tasks.analytics.ensure_tables",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def ensure_analytics_tables(self):
    """Create ClickHouse analytics tables if they don't exist.

    Run once on deployment or manually via CLI.
    """
    from app.core.analytics import ensure_tables
    if not ensure_tables():
        raise self.retry(exc=RuntimeError("ClickHouse table creation failed"))
