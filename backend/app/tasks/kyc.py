"""
KYC notification Celery task — FR-AUTH-005, PM-02 Step 12.

Notifies user of manual KYC review outcome via push + WhatsApp.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.celery import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.notify_kyc_outcome", bind=True, max_retries=3)
def notify_kyc_outcome(self, user_id: str, outcome: str, reason: str = "") -> None:
    """Send KYC outcome notification to user.

    PM-02 Step 12: Push + WhatsApp notification.
    outcome: 'approved' or 'rejected'
    """
    logger.info("KYC notification: user=%s outcome=%s reason=%s", user_id, outcome, reason)

    if outcome == "approved":
        title_en = "Identity Verified!"
        title_ar = "تم التحقق من هويتك!"
        body_en = "Your KYC verification is approved. You can now create listings."
        body_ar = "تم الموافقة على التحقق من هويتك. يمكنك الآن إنشاء إعلانات."
    else:
        title_en = "KYC Verification Update"
        title_ar = "تحديث التحقق من الهوية"
        body_en = f"Your KYC verification was not approved. {f'Reason: {reason}' if reason else 'Please contact support.'}"
        body_ar = f"لم تتم الموافقة على التحقق من هويتك. {f'السبب: {reason}' if reason else 'يرجى التواصل مع الدعم.'}"

    # Dispatch via the notification service (push + WhatsApp + in-app)
    event_type = "kyc_approved" if outcome == "approved" else "kyc_rejected"
    try:
        asyncio.run(_send_kyc_notification(user_id, event_type, reason))
    except Exception as exc:
        logger.error("KYC notification dispatch failed for %s: %s", user_id, exc)


async def _send_kyc_notification(
    user_id: str, event_type: str, reason: str,
) -> None:
    from app.core.redis import get_redis_client
    from app.services.notification.service import queue_notification

    redis = await get_redis_client()
    try:
        await queue_notification(
            user_id,
            event_type,
            user_id,  # entity_id = user themselves
            {"reason": reason} if reason else None,
            redis=redis,
        )
    finally:
        await redis.aclose()

    logger.info("KYC notification dispatched: user=%s event=%s", user_id, event_type)
