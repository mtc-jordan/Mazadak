"""
Channel dispatchers — FR-NOTIF-001 -> FR-NOTIF-012.

dispatch_fcm(user, notification)   — iterate user.fcm_tokens, remove stale
dispatch_whatsapp(user, notification, redis) — Meta Cloud API, pre-approved templates
dispatch_sms(user, notification)   — Twilio primary, AWS SNS fallback, 160 char truncation
dispatch_email(user, notification) — SMTP primary, SendGrid fallback, branded HTML
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from app.services.auth.models import User
    from app.services.notification.models import Notification

logger = logging.getLogger(__name__)


# =====================================================================
#  FCM Push — iterate user.fcm_tokens, remove stale
# =====================================================================

async def dispatch_fcm(user: User, notification: Notification) -> dict:
    """Send push notification to all user FCM tokens. Remove stale tokens."""
    try:
        from firebase_admin import messaging  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("firebase-admin not installed — skipping FCM push")
        return {"status": "skipped", "reason": "firebase-admin not installed"}

    tokens = _get_fcm_tokens(user)
    if not tokens:
        return {"status": "skipped", "reason": "no_tokens"}

    lang = getattr(user, "preferred_language", "ar")
    title = notification.title_ar if lang == "ar" else notification.title_en
    body = notification.body_ar if lang == "ar" else notification.body_en

    stale_tokens: list[str] = []

    for token in tokens:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={"type": notification.event_type, "entity_id": str(notification.entity_id or "")},
            token=token,
        )
        try:
            messaging.send(message)
            # Remove stale tokens collected so far
            if stale_tokens:
                _dispatch_remove_stale_tokens(str(user.id), stale_tokens)
            return {"status": "sent", "token_last4": token[-4:]}
        except messaging.UnregisteredError:
            logger.info("FCM token stale, marking for removal: %s", token[:20])
            stale_tokens.append(token)
        except Exception as exc:
            logger.warning("FCM send failed for token %s: %s", token[:20], exc)

    # All tokens failed — still dispatch stale removals
    if stale_tokens:
        _dispatch_remove_stale_tokens(str(user.id), stale_tokens)

    return {"status": "failed", "reason": "all_tokens_failed"}


def _dispatch_remove_stale_tokens(user_id: str, stale_tokens: list[str]) -> None:
    """Dispatch Celery tasks to remove stale FCM tokens."""
    try:
        from app.tasks.notification import remove_fcm_token
        for token in stale_tokens:
            remove_fcm_token.delay(user_id, token)
    except Exception:
        logger.warning("Failed to dispatch stale FCM token removal for user %s", user_id)


def _get_fcm_tokens(user: User) -> list[str]:
    """Extract FCM tokens from user.fcm_tokens (JSONB array or JSON string)."""
    raw = getattr(user, "fcm_tokens", None)
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


# =====================================================================
#  WhatsApp — Meta Cloud API, pre-approved templates
# =====================================================================

async def dispatch_whatsapp(
    user: User,
    notification: Notification,
    redis: Redis,
) -> bool:
    """Send WhatsApp notification via Meta Cloud API.

    Rate limit: 5 WhatsApp notifications per user per day.
    Financial notifications bypass the rate limit.
    """
    from datetime import date

    from app.core.config import settings
    from app.services.notification.templates import FINANCIAL_EVENTS, TEMPLATES

    if not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("WhatsApp not configured — skipping")
        return False

    tmpl = TEMPLATES.get(notification.event_type)
    if not tmpl or not tmpl.whatsapp_template:
        return False

    # Rate limit: 5/day per user (financial events bypass)
    is_financial = notification.event_type in FINANCIAL_EVENTS
    daily_key = f"notif:wa:daily:{user.id}:{date.today()}"
    count = await redis.incr(daily_key)
    await redis.expire(daily_key, 86400)
    if count > 5 and not is_financial:
        logger.debug("WhatsApp daily limit reached for %s", user.id)
        return {"status": "rate_limited"}

    lang = getattr(user, "preferred_language", "ar")
    phone = getattr(user, "phone", None)
    if not phone:
        return {"status": "skipped", "reason": "no_phone"}

    url = f"https://graph.facebook.com/v19.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": phone.lstrip("+"),
        "type": "template",
        "template": {
            "name": tmpl.whatsapp_template,
            "language": {"code": lang},
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code == 200:
            return {"status": "sent"}
        logger.warning("WhatsApp API returned %d: %s", resp.status_code, resp.text[:200])
        return {"status": "failed"}
    except Exception as exc:
        logger.error("WhatsApp send failed: %s", exc)
        return {"status": "failed"}


# =====================================================================
#  SMS — Twilio primary, AWS SNS fallback, 160-char truncation
# =====================================================================

async def dispatch_sms(user: User, notification: Notification) -> dict:
    """Send SMS notification. Twilio primary, AWS SNS fallback."""
    phone = getattr(user, "phone", None)
    if not phone:
        return {"status": "skipped", "reason": "no_phone"}

    lang = getattr(user, "preferred_language", "ar")
    body = notification.body_ar if lang == "ar" else notification.body_en
    body = body[:160] if body else ""

    if await _send_sms_twilio(phone, body):
        return {"status": "sent"}
    logger.info("Twilio SMS failed, falling back to AWS SNS for %s", phone)
    if await _send_sms_sns(phone, body):
        return {"status": "sent_via_sns"}
    return {"status": "failed"}


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


# =====================================================================
#  Email — SMTP primary, SendGrid fallback, branded HTML
# =====================================================================

async def dispatch_email(user: User, notification: Notification) -> dict:
    """Send email notification. SMTP primary, SendGrid fallback."""
    email = getattr(user, "email", None)
    if not email:
        return {"status": "skipped", "reason": "no_email"}

    lang = getattr(user, "preferred_language", "ar")
    title = notification.title_ar if lang == "ar" else notification.title_en
    body = notification.body_ar if lang == "ar" else notification.body_en

    html_body = _build_email_html(title, body, lang)

    from app.core.config import settings

    if settings.EMAIL_PROVIDER == "sendgrid" and settings.SENDGRID_API_KEY:
        if await _send_email_sendgrid(email, title, html_body, settings):
            return {"status": "sent"}
        logger.info("SendGrid failed, falling back to SMTP for %s", email)

    if settings.SMTP_HOST:
        if await _send_email_smtp(email, title, html_body, settings):
            return {"status": "sent"}
    else:
        logger.warning("Email not configured (no SMTP_HOST) — skipping")
        return {"status": "skipped", "reason": "email_not_configured"}

    return {"status": "failed"}


def _build_email_html(title: str, body: str, lang: str) -> str:
    """Build a branded HTML email with MZADAK styling."""
    direction = "rtl" if lang == "ar" else "ltr"
    font_family = "'Segoe UI', Tahoma, Arial, sans-serif"

    return f"""\
<!DOCTYPE html>
<html lang="{lang}" dir="{direction}">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background-color:#FFF8F0;font-family:{font_family};">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#FFF8F0;">
    <tr>
      <td align="center" style="padding:24px 0;">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color:#FFFFFF;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          <!-- Header -->
          <tr>
            <td style="background-color:#1B2A4A;padding:24px 32px;text-align:center;">
              <h1 style="margin:0;color:#D4A853;font-size:28px;font-weight:700;letter-spacing:1px;">MZADAK</h1>
            </td>
          </tr>
          <!-- Title -->
          <tr>
            <td style="padding:24px 32px 8px 32px;">
              <h2 style="margin:0;color:#1B2A4A;font-size:20px;font-weight:600;direction:{direction};text-align:start;">{title}</h2>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:8px 32px 32px 32px;">
              <p style="margin:0;color:#333333;font-size:16px;line-height:1.6;direction:{direction};text-align:start;">{body}</p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background-color:#F5F5F5;padding:16px 32px;text-align:center;border-top:2px solid #D4A853;">
              <p style="margin:0;color:#888888;font-size:12px;">&copy; MZADAK &mdash; مزادك</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


async def _send_email_smtp(
    to_email: str,
    subject: str,
    html_body: str,
    settings: object,
) -> bool:
    """Send email via SMTP using aiosmtplib."""
    try:
        import aiosmtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart("alternative")
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME or None,
            password=settings.SMTP_PASSWORD or None,
            start_tls=True,
        )
        return True
    except ImportError:
        logger.warning("aiosmtplib not installed — skipping SMTP email")
        return False
    except Exception as exc:
        logger.error("SMTP email send failed: %s", exc)
        return False


async def _send_email_sendgrid(
    to_email: str,
    subject: str,
    html_body: str,
    settings: object,
) -> bool:
    """Send email via SendGrid API."""
    url = "https://api.sendgrid.com/v3/mail/send"
    headers = {
        "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {
            "email": settings.SMTP_FROM_EMAIL,
            "name": settings.SMTP_FROM_NAME,
        },
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body}],
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code in (200, 201, 202):
            return True
        logger.warning(
            "SendGrid API returned %d: %s", resp.status_code, resp.text[:200]
        )
        return False
    except Exception as exc:
        logger.error("SendGrid email send failed: %s", exc)
        return False
