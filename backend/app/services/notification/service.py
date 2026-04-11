"""
Notification service — FR-NOTIF-001 -> FR-NOTIF-012, PM-11.

Public API:
    queue_notification(user_id, event_type, entity_id, entity_type, template_vars, db)
        -> dedup check (Redis nx=True, ex=60)
        -> render template
        -> persist Notification in DB
        -> dispatch_notification.delay(notification.id)

Existing CRUD helpers (get/mark-read) are preserved for the router.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.notification.models import (
    Notification,
    NotificationChannel,
    NotificationPreference,
)
from app.services.notification.templates import (
    FINANCIAL_EVENTS,
    render_template,
)

logger = logging.getLogger(__name__)

DEDUP_TTL = 60  # seconds


# =====================================================================
#  Public entry point -- called from anywhere in the codebase
# =====================================================================

async def queue_notification(
    user_id: str,
    event_type: str,
    entity_id: str | None,
    entity_type: str | None,
    template_vars: dict,
    db: AsyncSession,
) -> None:
    """Deduplicate, render, persist, and dispatch a notification.

    Dedup key: ``notif:dedup:{user_id}:{event_type}:{entity_id}`` with 60s TTL.
    """
    from app.core.redis import get_redis_client

    redis = await get_redis_client()
    try:
        # -- 1. Redis dedup with SET NX EX --
        dedup_key = f"notif:dedup:{user_id}:{event_type}:{entity_id}"
        if await redis.set(dedup_key, 1, nx=True, ex=DEDUP_TTL) is None:
            logger.info(
                "notification_deduplicated user_id=%s event_type=%s",
                user_id, event_type,
            )
            return

        # -- 2. Look up template and render --
        rendered = render_template(event_type, template_vars)
        if rendered is None:
            logger.warning("Unknown notification event_type: %s", event_type)
            return

        # -- 3. Persist notification in DB (flush to get ID) --
        from uuid import uuid4
        notif_id = str(uuid4())
        notification = Notification(
            id=notif_id,
            user_id=user_id,
            event_type=event_type,
            entity_id=entity_id,
            entity_type=entity_type,
            title_en=rendered.title_en,
            title_ar=rendered.title_ar,
            body_en=rendered.body_en,
            body_ar=rendered.body_ar,
            data=template_vars,
            channels_sent=[],
        )
        db.add(notification)
        await db.flush()

        # -- 4. Queue dispatch via Celery task --
        try:
            from app.tasks.notification import dispatch_notification
            dispatch_notification.delay(notif_id)
        except Exception:
            logger.warning(
                "Failed to dispatch notification %s for %s", event_type, user_id,
            )
    finally:
        await redis.aclose()


# =====================================================================
#  Dispatch implementation -- called by Celery task
# =====================================================================

async def dispatch_notification_impl(
    notification_id: str,
) -> dict:
    """Load notification + user, determine channels, dispatch, update channels_sent."""
    from app.core.database import async_session_factory
    from app.core.redis import get_redis_client
    from app.services.auth.models import User

    redis = await get_redis_client()
    try:
        async with async_session_factory() as db:
            notification = await db.get(Notification, notification_id)
            if not notification:
                logger.warning("Notification %s not found", notification_id)
                return {}

            user = await db.get(User, notification.user_id)
            if not user:
                logger.warning("User %s not found for notification", notification.user_id)
                return {}

            # -- Determine channels --
            is_financial = notification.event_type in FINANCIAL_EVENTS
            channels = await _resolve_channels(notification.user_id, is_financial, db)
            if not channels:
                return {}

            lang = getattr(user, "preferred_language", "ar")
            title = notification.title_ar if lang == "ar" else notification.title_en
            body = notification.body_ar if lang == "ar" else notification.body_en

            # -- Dispatch to each channel --
            results: dict[str, dict] = {}

            if NotificationChannel.PUSH in channels:
                from app.services.notification.dispatchers import dispatch_fcm
                results["push"] = await dispatch_fcm(user, notification)

            if NotificationChannel.SMS in channels:
                from app.services.notification.dispatchers import dispatch_sms
                results["sms"] = await dispatch_sms(user, notification)

            if NotificationChannel.WHATSAPP in channels:
                from app.services.notification.dispatchers import dispatch_whatsapp
                results["whatsapp"] = await dispatch_whatsapp(user, notification, redis)

            if NotificationChannel.EMAIL in channels:
                from app.services.notification.dispatchers import dispatch_email
                results["email"] = await dispatch_email(user, notification)

            # -- Update channels_sent --
            notification.channels_sent = results
            await db.commit()

            logger.info(
                "notification_dispatched id=%s event=%s channels=%s",
                notification_id, notification.event_type, results,
            )
            return results
    finally:
        await redis.aclose()


# =====================================================================
#  Channel resolution
# =====================================================================

async def _resolve_channels(
    user_id: str,
    is_financial: bool,
    db: AsyncSession,
) -> set[NotificationChannel]:
    """Determine which channels to use for this user.

    Financial notifications bypass preference checks and always
    go to PUSH + SMS + WHATSAPP.
    """
    if is_financial:
        return {
            NotificationChannel.PUSH,
            NotificationChannel.SMS,
            NotificationChannel.WHATSAPP,
            NotificationChannel.EMAIL,
        }

    result = await db.execute(
        select(NotificationPreference)
        .where(NotificationPreference.user_id == user_id)
    )
    pref = result.scalar_one_or_none()

    channels: set[NotificationChannel] = set()
    if pref is None or pref.push_enabled:
        channels.add(NotificationChannel.PUSH)
    if pref is None or pref.sms_enabled:
        channels.add(NotificationChannel.SMS)
    if pref is None or pref.whatsapp_enabled:
        channels.add(NotificationChannel.WHATSAPP)
    if pref is None or pref.email_enabled:
        channels.add(NotificationChannel.EMAIL)

    return channels


# =====================================================================
#  Existing CRUD helpers (used by router)
# =====================================================================

async def get_user_notifications(
    user_id: str,
    db: AsyncSession,
    limit: int = 50,
) -> tuple[list[Notification], int]:
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    notifications = list(result.scalars().all())

    unread = await db.execute(
        select(func.count(Notification.id))
        .where(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
    )
    unread_count = unread.scalar() or 0

    return notifications, unread_count


async def mark_as_read(
    notification_ids: list[str],
    user_id: str,
    db: AsyncSession,
) -> int:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Notification).where(
            Notification.id.in_(notification_ids),
            Notification.user_id == user_id,
        )
    )
    count = 0
    for notif in result.scalars().all():
        notif.is_read = True
        notif.read_at = now
        count += 1
    await db.commit()
    return count


# =====================================================================
#  Notification preferences
# =====================================================================

async def get_preferences(
    user_id: str, db: AsyncSession,
) -> NotificationPreference | None:
    result = await db.execute(
        select(NotificationPreference)
        .where(NotificationPreference.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def update_preferences(
    user_id: str,
    updates: dict,
    db: AsyncSession,
) -> NotificationPreference:
    result = await db.execute(
        select(NotificationPreference)
        .where(NotificationPreference.user_id == user_id)
    )
    pref = result.scalar_one_or_none()

    if pref is None:
        from uuid import uuid4
        pref = NotificationPreference(
            id=str(uuid4()),
            user_id=user_id,
            push_enabled=True,
            sms_enabled=True,
            email_enabled=True,
            whatsapp_enabled=True,
        )
        db.add(pref)

    for key, value in updates.items():
        if value is not None and hasattr(pref, key):
            setattr(pref, key, value)

    await db.commit()
    await db.refresh(pref)
    return pref
