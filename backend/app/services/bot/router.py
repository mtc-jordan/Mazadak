"""
WhatsApp Bid Bot webhook — SDD spec endpoints.

GET  /api/v1/webhooks/whatsapp → Meta verification challenge
POST /api/v1/webhooks/whatsapp → incoming messages (HMAC-SHA256 verified)
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
from app.services.bot.service import process_whatsapp_message

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

    Meta sends GET with hub.mode, hub.verify_token, hub.challenge.
    Return the challenge if the token matches.
    """
    if mode == "subscribe" and token == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified")
        return Response(content=challenge, media_type="text/plain")

    logger.warning("WhatsApp webhook verification failed: mode=%s", mode)
    return Response(content="Forbidden", status_code=status.HTTP_403_FORBIDDEN)


# ═══════════════════════════════════════════════════════════════
# Inbound Message Webhook (POST)
# ═══════════════════════════════════════════════════════════════

@router.post("", status_code=status.HTTP_200_OK)
async def receive_message(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Receive inbound WhatsApp messages.

    Pipeline:
      1. Verify HMAC-SHA256 signature (X-Hub-Signature-256)
      2. Parse the Meta webhook payload
      3. For each message, run the bot pipeline
      4. Always return 200 (Meta retries on non-200)
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not _verify_meta_signature(body, signature):
        logger.warning("Invalid WhatsApp webhook signature")
        return {"status": "error", "reason": "invalid_signature"}

    try:
        payload = await request.json()
    except Exception:
        return {"status": "ok"}

    # Extract and process messages from Meta webhook format
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue

            value = change.get("value", {})
            messages = value.get("messages", [])

            for msg in messages:
                if not msg.get("from"):
                    continue

                try:
                    await process_whatsapp_message(
                        message=msg,
                        db=db,
                        redis=redis,
                    )
                except Exception as exc:
                    logger.error(
                        "Bot pipeline error for %s: %s",
                        msg.get("from"), exc, exc_info=True,
                    )

    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════
# HMAC-SHA256 Verification
# ═══════════════════════════════════════════════════════════════

def _verify_meta_signature(payload: bytes, signature: str) -> bool:
    """Verify Meta Cloud API webhook HMAC-SHA256 signature.

    The X-Hub-Signature-256 header contains: ``sha256=<hex_digest>``
    Uses settings.META_WEBHOOK_SECRET (falls back to WHATSAPP_APP_SECRET).
    """
    secret = getattr(settings, "META_WEBHOOK_SECRET", "") or settings.WHATSAPP_APP_SECRET
    if not secret:
        if settings.ENVIRONMENT == "production":
            logger.error("META_WEBHOOK_SECRET not set in production — rejecting request")
            return False
        logger.warning("META_WEBHOOK_SECRET not set — skipping signature check (non-prod)")
        return True

    if not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(f"sha256={expected}", signature)
