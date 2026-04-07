"""Notification Celery task — dispatches multi-channel notifications."""

import asyncio
import logging

from app.core.celery import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.notification.send_notification",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def send_notification(
    self,
    user_id: str,
    event_type: str,
    entity_id: str,
    data: dict,
):
    """Async-to-sync bridge: fetches DB/Redis and calls send_notification_impl."""
    asyncio.run(_run(user_id, event_type, entity_id, data))


async def _run(
    user_id: str, event_type: str, entity_id: str, data: dict,
):
    from app.core.database import async_session_factory
    from app.core.redis import get_redis_client
    from app.services.notification.service import send_notification_impl

    redis = await get_redis_client()
    try:
        async with async_session_factory() as db:
            channels = await send_notification_impl(
                user_id, event_type, entity_id, data, db, redis,
            )
        if channels:
            logger.info(
                "Notification sent: user=%s event=%s channels=%s",
                user_id, event_type, channels,
            )
    finally:
        await redis.aclose()
