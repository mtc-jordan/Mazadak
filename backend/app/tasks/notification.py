"""Notification Celery tasks — dispatch + FCM token cleanup."""

import asyncio
import logging

from app.core.celery import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.notification.dispatch_notification",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def dispatch_notification(self, notification_id: str):
    """Dispatch a persisted notification to all resolved channels.

    Called by queue_notification() after DB persistence.
    """
    asyncio.run(_dispatch_notification_async(notification_id))


async def _dispatch_notification_async(notification_id: str) -> None:
    from app.services.notification.service import dispatch_notification_impl
    await dispatch_notification_impl(notification_id)


@celery_app.task(
    name="app.tasks.notification.remove_fcm_token",
    bind=True,
    max_retries=2,
    default_retry_delay=5,
)
def remove_fcm_token(self, user_id: str, stale_token: str):
    """Remove a stale FCM token from the user's fcm_tokens array."""
    asyncio.run(_remove_fcm_token_async(user_id, stale_token))


async def _remove_fcm_token_async(user_id: str, stale_token: str) -> None:
    from app.core.database import async_session_factory
    from app.services.auth.models import User

    async with async_session_factory() as db:
        user = await db.get(User, user_id)
        if not user:
            return

        tokens = user.fcm_tokens or []
        if stale_token in tokens:
            tokens = [t for t in tokens if t != stale_token]
            user.fcm_tokens = tokens
            await db.commit()
            logger.info("Removed stale FCM token for user %s", user_id)
