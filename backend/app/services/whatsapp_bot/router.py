"""
WhatsApp Bot webhook endpoint — FR-BOT-001.

POST /api/v1/webhooks/whatsapp  — receive inbound messages (HMAC verified)
GET  /api/v1/webhooks/whatsapp  — Meta verification challenge

HMAC verification uses the app secret from Meta Cloud API to validate
that incoming requests are genuinely from Meta (not spoofed).
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, Query, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.services.whatsapp_bot.schemas import WhatsAppWebhookPayload
from app.services.whatsapp_bot.service import handle_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp-bot"])


# ═══════════════════════════════════════════════════════════════
# Meta Webhook Verification (GET)
# ═══════════════════════════════════════════════════════════════

@router.get("")
async def verify_webhook(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge"),
) -> Response:
    """Meta Cloud API webhook verification challenge.

    Meta sends a GET request with hub.mode, hub.verify_token, and
    hub.challenge.  We return the challenge if the token matches.
    """
    if mode == "subscribe" and token == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified")
        return Response(content=challenge, media_type="text/plain")

    logger.warning("WhatsApp webhook verification failed: mode=%s", mode)
    return Response(
        content="Forbidden",
        status_code=status.HTTP_403_FORBIDDEN,
    )


# ═══════════════════════════════════════════════════════════════
# Inbound Message Webhook (POST)
# ═══════════════════════════════════════════════════════════════

@router.post("", status_code=status.HTTP_200_OK)
async def receive_message(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Receive and process inbound WhatsApp messages.

    Pipeline:
      1. Verify HMAC-SHA256 signature (X-Hub-Signature-256 header)
      2. Parse the Meta webhook payload
      3. For each message, run the bot pipeline asynchronously
      4. Always return 200 (Meta retries on non-200)
    """
    # ── HMAC Signature Verification ──────────────────────────────
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not _verify_meta_signature(body, signature):
        logger.warning("Invalid WhatsApp webhook signature")
        return {"status": "error", "reason": "invalid_signature"}

    # ── Parse payload ────────────────────────────────────────────
    try:
        payload = WhatsAppWebhookPayload.model_validate_json(body)
    except Exception as exc:
        logger.warning("Failed to parse WhatsApp webhook: %s", exc)
        return {"status": "ok"}  # Return 200 to prevent Meta retries

    # ── Process messages ─────────────────────────────────────────
    for entry in payload.entry:
        for change in entry.changes:
            if change.field != "messages":
                continue

            messages = change.value.messages or []
            contacts = change.value.contacts or []

            for msg in messages:
                # Resolve sender phone from contacts or message.from
                sender_phone = msg.from_ or ""
                if not sender_phone and contacts:
                    sender_phone = contacts[0].wa_id

                if not sender_phone:
                    continue

                try:
                    await handle_message(sender_phone, msg, db, redis)
                except Exception as exc:
                    logger.error(
                        "Bot pipeline error for %s: %s",
                        sender_phone, exc, exc_info=True,
                    )
                    # Don't fail the webhook — Meta will retry
                    from app.services.whatsapp_bot import templates
                    from app.services.whatsapp_bot.service import _send_reply
                    try:
                        await _send_reply(sender_phone, templates.error_generic())
                    except Exception:
                        pass

    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════
# HMAC Verification
# ═══════════════════════════════════════════════════════════════

def _verify_meta_signature(payload: bytes, signature: str) -> bool:
    """Verify Meta Cloud API webhook HMAC-SHA256 signature.

    The X-Hub-Signature-256 header contains: ``sha256=<hex_digest>``
    computed using the App Secret as the HMAC key.
    """
    if not settings.WHATSAPP_APP_SECRET:
        # In dev mode without secret configured, allow through
        logger.warning("WHATSAPP_APP_SECRET not set — skipping signature check")
        return True

    if not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(f"sha256={expected}", signature)
