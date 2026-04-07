"""
Notification service — FR-NOTIF-001 → FR-NOTIF-012, PM-11.

Public API:
    queue_notification(user_id, event_type, entity_id, data, redis)
        → dedup check → Celery task send_notification

    send_notification_impl(user_id, event_type, entity_id, data, db, redis)
        → resolve template → check preferences → dispatch channels → persist

Existing CRUD helpers (get/mark-read) are preserved for the router.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.notification.models import (
    Notification,
    NotificationChannel,
    NotificationPreference,
)
from app.services.notification.templates import (
    FINANCIAL_EVENTS,
    TEMPLATES,
    render_template,
)

logger = logging.getLogger(__name__)

DEDUP_TTL = 60  # seconds


# ═══════════════════════════════════════════════════════════════════
#  Public entry point — called from anywhere in the codebase
# ═══════════════════════════════════════════════════════════════════

async def queue_notification(
    user_id: str,
    event_type: str,
    entity_id: str,
    data: dict | None = None,
    *,
    redis: Redis,
) -> bool:
    """Deduplicate and queue a notification for async delivery.

    Dedup key: ``notif:{user_id}:{event_type}:{entity_id}`` with 60s TTL.
    Returns True if queued, False if deduplicated (skipped).
    """
    dedup_key = f"notif:{user_id}:{event_type}:{entity_id}"
    if await redis.exists(dedup_key):
        logger.debug("Dedup hit: %s", dedup_key)
        return False

    await redis.setex(dedup_key, DEDUP_TTL, "1")

    try:
        from app.tasks.notification import send_notification
        send_notification.delay(user_id, event_type, entity_id, data or {})
    except Exception:
        logger.warning("Failed to queue notification %s for %s", event_type, user_id)
        return False

    return True


# ═══════════════════════════════════════════════════════════════════
#  Celery task implementation — called by send_notification task
# ═══════════════════════════════════════════════════════════════════

async def send_notification_impl(
    user_id: str,
    event_type: str,
    entity_id: str,
    data: dict,
    db: AsyncSession,
    redis: Redis,
) -> list[str]:
    """Resolve template, check preferences, dispatch, persist.

    Returns list of channels that were dispatched to.
    """
    # ── 1. Resolve template ───────────────────────────────────────
    rendered = render_template(event_type, data)
    if rendered is None:
        logger.warning("Unknown notification event_type: %s", event_type)
        return []

    # ── 2. Determine channels ─────────────────────────────────────
    is_financial = event_type in FINANCIAL_EVENTS
    channels = await _resolve_channels(user_id, is_financial, db)
    if not channels:
        logger.debug("No channels enabled for user %s event %s", user_id, event_type)
        return []

    # ── 3. WhatsApp rate limit (non-financial only) ───────────────
    wa_key = f"wa_daily:{user_id}"
    wa_blocked = False
    if NotificationChannel.WHATSAPP in channels and not is_financial:
        from app.core.config import settings
        count = int(await redis.get(wa_key) or 0)
        if count >= settings.WHATSAPP_RATE_LIMIT_PER_DAY:
            channels.discard(NotificationChannel.WHATSAPP)
            wa_blocked = True
            logger.debug("WhatsApp daily limit reached for %s", user_id)

    # ── 4. Load user for phone / FCM token / language ─────────────
    from app.services.auth.models import User
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning("User %s not found — skipping notification", user_id)
        return []

    lang = getattr(user, "preferred_language", "ar")
    title = rendered.title_ar if lang == "ar" else rendered.title_en
    body = rendered.body_ar if lang == "ar" else rendered.body_en

    # ── 5. Dispatch to each channel ───────────────────────────────
    dispatched: list[str] = []

    if NotificationChannel.PUSH in channels:
        from app.services.notification.channels import send_fcm
        fcm_token = getattr(user, "fcm_token", None)
        if fcm_token:
            ok = await send_fcm(fcm_token, title, body, {"entity_id": entity_id})
            if ok:
                dispatched.append("push")

    if NotificationChannel.SMS in channels:
        from app.services.notification.channels import send_sms
        ok = await send_sms(user.phone, body)
        if ok:
            dispatched.append("sms")

    if NotificationChannel.WHATSAPP in channels:
        if rendered.whatsapp_template:
            from app.services.notification.channels import send_whatsapp
            ok = await send_whatsapp(
                user.phone, rendered.whatsapp_template,
                language=lang,
            )
            if ok:
                dispatched.append("whatsapp")
                if not is_financial:
                    await redis.incr(wa_key)
                    # Set TTL to end of day if first message
                    if int(await redis.get(wa_key) or 0) == 1:
                        await redis.expire(wa_key, 86400)

    # ── 6. Persist in-app notification ────────────────────────────
    notification = Notification(
        user_id=user_id,
        channel="in_app",
        title_ar=rendered.title_ar,
        title_en=rendered.title_en,
        body_ar=rendered.body_ar,
        body_en=rendered.body_en,
        payload={"event_type": event_type, "entity_id": entity_id, **(data or {})},
    )
    db.add(notification)
    await db.commit()
    dispatched.append("in_app")

    return dispatched


# ═══════════════════════════════════════════════════════════════════
#  Channel resolution
# ═══════════════════════════════════════════════════════════════════

async def _resolve_channels(
    user_id: str,
    is_financial: bool,
    db: AsyncSession,
) -> set[NotificationChannel]:
    """Determine which channels to use for this user.

    Financial notifications bypass preference checks and always
    go to PUSH + SMS + WHATSAPP + IN_APP.
    """
    if is_financial:
        return {
            NotificationChannel.PUSH,
            NotificationChannel.SMS,
            NotificationChannel.WHATSAPP,
            NotificationChannel.IN_APP,
        }

    # Load user preferences
    result = await db.execute(
        select(NotificationPreference)
        .where(NotificationPreference.user_id == user_id)
    )
    pref = result.scalar_one_or_none()

    # Default: all channels enabled
    channels: set[NotificationChannel] = {NotificationChannel.IN_APP}
    if pref is None or pref.push_enabled:
        channels.add(NotificationChannel.PUSH)
    if pref is None or pref.sms_enabled:
        channels.add(NotificationChannel.SMS)
    if pref is None or pref.whatsapp_enabled:
        channels.add(NotificationChannel.WHATSAPP)

    return channels


# ═══════════════════════════════════════════════════════════════════
#  Existing CRUD helpers (used by router)
# ═══════════════════════════════════════════════════════════════════

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
    result = await db.execute(
        select(Notification).where(
            Notification.id.in_(notification_ids),
            Notification.user_id == user_id,
        )
    )
    count = 0
    for notif in result.scalars().all():
        notif.is_read = True
        count += 1
    await db.commit()
    return count
