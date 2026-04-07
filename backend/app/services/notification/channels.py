"""
Channel dispatchers — FR-NOTIF-001 → FR-NOTIF-012.

Each dispatcher is responsible for a single delivery channel.
All dispatchers follow the same interface:
    async def dispatch(user_id, phone, title, body, payload, lang) -> bool

FCM:      Firebase Admin SDK, retry 3x, refresh token on 404
WhatsApp: Meta Cloud API, pre-approved templates, rate limit 5/day/user
SMS:      Twilio primary, AWS SNS fallback
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  FCM Push
# ═══════════════════════════════════════════════════════════════════

async def send_fcm(
    fcm_token: str,
    title: str,
    body: str,
    payload: dict | None = None,
) -> bool:
    """Send a push notification via Firebase Cloud Messaging.

    Retries up to 3 times. On HTTP 404 (invalid/expired token) the
    caller should delete the token from the user's device list.
    """
    try:
        from firebase_admin import messaging  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("firebase-admin not installed — skipping FCM push")
        return False

    message = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data=payload or {},
        token=fcm_token,
    )

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            messaging.send(message)
            return True
        except messaging.UnregisteredError:
            logger.info("FCM token expired/invalid: %s", fcm_token[:20])
            return False
        except Exception as exc:
            last_exc = exc
            logger.warning("FCM send attempt %d failed: %s", attempt + 1, exc)

    logger.error("FCM send failed after 3 retries: %s", last_exc)
    return False


# ═══════════════════════════════════════════════════════════════════
#  WhatsApp (Meta Cloud API)
# ═══════════════════════════════════════════════════════════════════

async def send_whatsapp(
    phone: str,
    template_name: str,
    language: str = "ar",
    components: list[dict] | None = None,
) -> bool:
    """Send a WhatsApp message via Meta Cloud API using a pre-approved template.

    Rate limiting (5/day/user) is enforced by the caller, not here.
    """
    from app.core.config import settings

    if not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("WhatsApp not configured — skipping")
        return False

    url = f"https://graph.facebook.com/v19.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    body = {
        "messaging_product": "whatsapp",
        "to": phone.lstrip("+"),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
        },
    }
    if components:
        body["template"]["components"] = components

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=body)
        if resp.status_code == 200:
            return True
        logger.warning("WhatsApp API returned %d: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:
        logger.error("WhatsApp send failed: %s", exc)
        return False


# ═══════════════════════════════════════════════════════════════════
#  SMS (Twilio primary, AWS SNS fallback)
# ═══════════════════════════════════════════════════════════════════

async def send_sms(phone: str, body: str) -> bool:
    """Send SMS via Twilio. Falls back to AWS SNS on failure."""
    if await _send_sms_twilio(phone, body):
        return True
    logger.info("Twilio SMS failed, falling back to AWS SNS for %s", phone)
    return await _send_sms_sns(phone, body)


async def _send_sms_twilio(phone: str, body: str) -> bool:
    from app.core.config import settings

    if not settings.TWILIO_ACCOUNT_SID:
        return False

    url = (
        f"https://api.twilio.com/2010-04-01/Accounts"
        f"/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                data={
                    "From": settings.TWILIO_PHONE_NUMBER,
                    "To": phone,
                    "Body": body,
                },
            )
        if resp.status_code in (200, 201):
            return True
        logger.warning("Twilio SMS returned %d: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:
        logger.error("Twilio SMS failed: %s", exc)
        return False


async def _send_sms_sns(phone: str, body: str) -> bool:
    from app.core.config import settings

    if not settings.AWS_ACCESS_KEY_ID:
        return False

    try:
        import boto3
        client = boto3.client(
            "sns",
            region_name=settings.AWS_SNS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
        client.publish(PhoneNumber=phone, Message=body)
        return True
    except Exception as exc:
        logger.error("AWS SNS SMS failed: %s", exc)
        return False
