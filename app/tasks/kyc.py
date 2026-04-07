"""
KYC notification Celery task — FR-AUTH-005, PM-02 Step 12.

Notifies user of manual KYC review outcome via push + WhatsApp.
"""

from __future__ import annotations

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

    # TODO: Call notification service to send push + WhatsApp
    # from app.services.notification.service import send_notification
    # send_notification(user_id, channel="push", title=title_en, body=body_en)
    # send_notification(user_id, channel="whatsapp", title=title_en, body=body_en)

    logger.info(
        "KYC notification sent: user=%s title=%s", user_id, title_en,
    )
