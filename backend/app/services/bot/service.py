"""
WhatsApp Bid Bot — core pipeline per spec.

Message flow:
  1. Idempotency check (Redis: bot:processed:{message_id})
  2. Look up MZADAK user by phone (User.phone == '+{sender_phone}')
  3. Reject suspended / banned users
  4. If audio → transcribe via OpenAI Whisper
  5. Normalize Arabic numbers → extract intent via regex
  6. Execute intent (bid / check / help)
  7. Send reply via Meta Cloud API
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.auth.models import User
from app.services.bot.nlp import BotIntent, extract_intent

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Main entry point — spec signature: process_whatsapp_message(message, db)
# ═══════════════════════════════════════════════════════════════

async def process_whatsapp_message(
    message: dict,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Process a single inbound WhatsApp message.

    Args:
        message: Raw Meta webhook message dict with keys:
            from, id, type, text.body, audio.id
        db: Database session.
        redis: Redis client.
    """
    sender_phone: str = message.get("from", "")
    message_id: str = message.get("id", "")

    # ── 1. Idempotency check ────────────────────────────────────
    idem_key = f"bot:processed:{message_id}"
    was_set = await redis.set(idem_key, "1", nx=True, ex=86400)
    if not was_set:
        logger.debug("Duplicate message skipped: %s", message_id)
        return

    # ── 2. Look up MZADAK user by phone ─────────────────────────
    user = await _lookup_user_by_phone(sender_phone, db)
    if not user:
        await send_whatsapp_reply(
            sender_phone,
            "رقمك غير مرتبط بحساب مزادك. حمل التطبيق:\nmzadak.com/download\n\n"
            "Your number isn't linked to MZADAK. Download the app: mzadak.com/download",
        )
        return

    # ── 3. Check suspended / banned ─────────────────────────────
    if user.status in ("suspended", "banned"):
        await send_whatsapp_reply(sender_phone, "حسابك موقوف. تواصل مع الدعم.")
        return

    # ── 4. Extract text (transcribe audio if needed) ────────────
    msg_type: str = message.get("type", "text")
    text = ""

    if msg_type == "audio":
        audio_id = (message.get("audio") or {}).get("id")
        if audio_id:
            text = await transcribe_audio(audio_id) or ""
        if not text:
            await send_whatsapp_reply(
                sender_phone,
                "لم أفهم الرسالة الصوتية. أرسل نصاً.",
            )
            return
    elif msg_type == "text":
        text = (message.get("text") or {}).get("body", "").strip()
    else:
        await send_whatsapp_reply(
            sender_phone,
            "أرسل رسالة نصية أو صوتية للمزايدة.",
        )
        return

    if not text:
        await send_whatsapp_reply(
            sender_phone,
            _help_text(getattr(user, "preferred_language", "ar")),
        )
        return

    # ── 5. NLP intent extraction ────────────────────────────────
    intent = extract_intent(text)
    logger.info(
        "Bot intent: phone=%s type=%s amount=%s ref=%s",
        sender_phone, intent.type, intent.amount, intent.auction_ref,
    )

    # ── 6. Dispatch by intent type ──────────────────────────────
    if intent.type == "bid":
        await handle_bid_intent(user, intent, sender_phone, db, redis)
    elif intent.type == "check":
        await handle_check_intent(user, intent, sender_phone, db, redis)
    elif intent.type == "help":
        await send_whatsapp_reply(
            sender_phone,
            _help_text(getattr(user, "preferred_language", "ar")),
        )
    else:
        await send_whatsapp_reply(
            sender_phone,
            _build_unknown_intent_reply(text),
        )


# ═══════════════════════════════════════════════════════════════
# Bid handler
# ═══════════════════════════════════════════════════════════════

async def handle_bid_intent(
    user: User,
    intent: BotIntent,
    phone: str,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Handle a bid intent — validate via Lua, persist via Celery."""

    if not intent.amount:
        await send_whatsapp_reply(
            phone,
            "أرسل المبلغ مع رقم المزاد.\nمثال: زايد 500 #اسم_المنتج",
        )
        return

    if not intent.auction_ref:
        await send_whatsapp_reply(
            phone,
            "على أي مزاد تريد المزايدة؟ أرسل اسم المنتج.",
        )
        return

    # ── Search for active listing ───────────────────────────────
    listing = await _search_active_listing(intent.auction_ref, db)
    if not listing:
        await send_whatsapp_reply(
            phone,
            "ما لقيت مزاد نشط بهذا الاسم. تحقق من التطبيق.",
        )
        return

    # ── Rate limit: 5 bids per minute per user (Redis INCR) ─────
    rate_key = f"bot:bid:rate:{user.id}"
    count = await redis.incr(rate_key)
    if count == 1:
        await redis.expire(rate_key, 60)
    if count > 5:
        await send_whatsapp_reply(phone, "كثرت المزايدات. انتظر دقيقة.")
        return

    # ── Validate bid via Lua script ─────────────────────────────
    from app.services.auction.lua_scripts import BidLuaScripts

    amount_cents = intent.amount * 100
    auction_id = str(listing.get("auction_id", intent.auction_ref))

    result = await BidLuaScripts.validate_bid(
        redis, auction_id, amount_cents, str(user.id),
    )

    if result.accepted:
        from app.tasks.auction import insert_bid_to_db as _insert_bid_task
        _insert_bid_task.delay(auction_id, str(user.id), amount_cents, "JOD")

        title = listing.get("title_ar") or listing.get("title_en") or intent.auction_ref
        msg = f"تم قبول مزايدتك: {intent.amount} دينار على {title}\n"
        if result.extended:
            msg += "تم تمديد المزاد 3 دقائق!"
        await send_whatsapp_reply(phone, msg)
    else:
        reason = result.rejection_reason or "UNKNOWN"
        reason_map = {
            "BID_TOO_LOW": (
                f"مزايدتك أقل من الحد الأدنى. الحد الأدنى: "
                f"{(result.min_required or 0) // 100} دينار"
            ),
            "AUCTION_NOT_ACTIVE": "المزاد انتهى أو لم يبدأ بعد.",
            "SELLER_CANNOT_BID": "لا يمكنك المزايدة على مزادك الخاص.",
        }
        msg = reason_map.get(reason, "رُفضت المزايدة. تحقق من التطبيق.")
        await send_whatsapp_reply(phone, msg)


# ═══════════════════════════════════════════════════════════════
# Check handler
# ═══════════════════════════════════════════════════════════════

async def handle_check_intent(
    user: User,
    intent: BotIntent,
    phone: str,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Handle a status-check intent — read current price from Redis."""
    if not intent.auction_ref:
        await send_whatsapp_reply(
            phone,
            "حدد رقم المزاد للاستعلام.\nمثال: كم السعر #ABC123",
        )
        return

    listing = await _search_active_listing(intent.auction_ref, db)
    if not listing:
        await send_whatsapp_reply(
            phone,
            f"ما لقيت مزاد بهذا الاسم.",
        )
        return

    auction_id = str(listing.get("auction_id", intent.auction_ref))
    price_raw = await redis.get(f"auction:{auction_id}:price")
    status_raw = await redis.get(f"auction:{auction_id}:status")
    bid_count_raw = await redis.get(f"auction:{auction_id}:bid_count")

    if not price_raw or not status_raw:
        await send_whatsapp_reply(phone, "لم يتم العثور على بيانات المزاد.")
        return

    price = int(price_raw) / 100
    status = status_raw if isinstance(status_raw, str) else status_raw.decode()
    bid_count = int(bid_count_raw) if bid_count_raw else 0
    title = listing.get("title_ar") or listing.get("title_en", "")

    await send_whatsapp_reply(
        phone,
        f"{title}\n"
        f"السعر الحالي: {price:.2f} دينار\n"
        f"عدد المزايدات: {bid_count}\n"
        f"الحالة: {status}",
    )


# ═══════════════════════════════════════════════════════════════
# Audio transcription via OpenAI Whisper
# ═══════════════════════════════════════════════════════════════

async def transcribe_audio(audio_id: str) -> Optional[str]:
    """Download WhatsApp audio and transcribe via OpenAI Whisper API.

    Steps:
      1. GET media URL from Meta Cloud API
      2. Download the audio file
      3. POST to OpenAI Whisper with Arabic prompt hint
    """
    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set — cannot transcribe audio")
        return None

    try:
        # Step 1: Get media URL from Meta
        async with httpx.AsyncClient(timeout=15) as client:
            meta_resp = await client.get(
                f"https://graph.facebook.com/v18.0/{audio_id}",
                headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"},
            )
            if meta_resp.status_code != 200:
                logger.warning("Failed to get media URL: %d", meta_resp.status_code)
                return None

            media_url = meta_resp.json().get("url")
            if not media_url:
                return None

            # Step 2: Download audio
            audio_resp = await client.get(
                media_url,
                headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"},
            )
            if audio_resp.status_code != 200:
                return None

            audio_bytes = audio_resp.content

        # Step 3: Transcribe via Whisper (with Arabic prompt hint)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                files={"file": ("voice.ogg", audio_bytes, "audio/ogg")},
                data={
                    "model": "whisper-1",
                    "language": "ar",
                    "prompt": "مزايدة على مزادك. أرقام وأسعار.",
                },
            )
            if resp.status_code == 200:
                return resp.json().get("text", "")

        logger.warning("Whisper transcription failed: %d", resp.status_code)
        return None

    except Exception as exc:
        logger.error("Audio transcription error: %s", exc)
        return None


# ═══════════════════════════════════════════════════════════════
# Listing search helper
# ═══════════════════════════════════════════════════════════════

async def _search_active_listing(ref: str, db: AsyncSession) -> Optional[dict]:
    """Search for an active listing by auction ref.

    Tries UUID lookup first, then falls back to Meilisearch keyword search.
    Returns dict with auction_id, title_ar, title_en, or None.
    """
    from app.services.auction.models import Auction
    from app.services.listing.models import Listing

    # Try direct UUID lookup (auction_id or listing_id)
    try:
        import uuid
        uuid.UUID(ref)  # validate it's a UUID
        auction = await db.get(Auction, ref)
        if auction and auction.status == "active":
            listing = await db.get(Listing, auction.listing_id)
            return {
                "auction_id": auction.id,
                "title_ar": getattr(listing, "title_ar", "") if listing else "",
                "title_en": getattr(listing, "title_en", "") if listing else "",
            }
    except (ValueError, AttributeError):
        pass

    # Fuzzy search via Meilisearch
    try:
        import meilisearch

        client = meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_API_KEY)
        result = client.index("listings").search(
            ref,
            {
                "limit": 1,
                "filter": ["status = active"],
                "attributesToRetrieve": ["id", "title_ar", "title_en", "auction_id"],
            },
        )
        hits = result.get("hits", [])
        if hits:
            hit = hits[0]
            return {
                "auction_id": hit.get("auction_id", hit.get("id")),
                "title_ar": hit.get("title_ar", ""),
                "title_en": hit.get("title_en", ""),
            }
    except Exception as exc:
        logger.debug("Meilisearch search failed (falling back): %s", exc)

    # Fallback: ILIKE search in PostgreSQL
    stmt = (
        select(Listing)
        .where(
            Listing.status == "active",
            (Listing.title_ar.ilike(f"%{ref}%")) | (Listing.title_en.ilike(f"%{ref}%")),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    listing = result.scalar_one_or_none()
    if listing:
        # Get associated auction
        auction_stmt = select(Auction).where(
            Auction.listing_id == listing.id,
            Auction.status == "active",
        ).limit(1)
        auction_result = await db.execute(auction_stmt)
        auction = auction_result.scalar_one_or_none()
        if auction:
            return {
                "auction_id": auction.id,
                "title_ar": listing.title_ar or "",
                "title_en": listing.title_en or "",
            }

    return None


# ═══════════════════════════════════════════════════════════════
# User lookup
# ═══════════════════════════════════════════════════════════════

async def _lookup_user_by_phone(
    sender_phone: str, db: AsyncSession,
) -> Optional[User]:
    """Find MZADAK user by phone number."""
    phone = f"+{sender_phone}" if not sender_phone.startswith("+") else sender_phone
    result = await db.scalar(select(User).where(User.phone == phone))
    return result


# ═══════════════════════════════════════════════════════════════
# WhatsApp reply via Meta Cloud API
# ═══════════════════════════════════════════════════════════════

async def send_whatsapp_reply(phone: str, text: str) -> None:
    """Send a text message via Meta Cloud API."""
    if not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("WhatsApp credentials not set — reply not sent to %s", phone)
        return

    url = f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": text},
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=payload)

        if resp.status_code not in (200, 201):
            logger.warning(
                "WhatsApp send failed %d for %s: %s",
                resp.status_code, phone, resp.text[:200],
            )
    except Exception as exc:
        logger.error("WhatsApp send error for %s: %s", phone, exc)


# ═══════════════════════════════════════════════════════════════
# Reply builders
# ═══════════════════════════════════════════════════════════════

def _help_text(language: str = "ar") -> str:
    """Bilingual help message."""
    return (
        "مرحباً بك في بوت مزادك!\n\n"
        "الأوامر المتاحة:\n"
        "- زايد [المبلغ] #[رقم المزاد] — للمزايدة\n"
        "- كم السعر #[رقم المزاد] — للاستعلام\n"
        "- مساعدة — لعرض هذه الرسالة\n\n"
        "Welcome to MZADAK Bot!\n"
        "- bid [amount] #[auction] — place a bid\n"
        "- check #[auction] — check price\n"
        "- help — show this message"
    )


def _build_unknown_intent_reply(text: str) -> str:
    """Reply when intent cannot be determined."""
    return (
        f"لم أفهم طلبك: \"{text[:50]}\"\n\n"
        "أرسل 'مساعدة' لعرض الأوامر المتاحة.\n"
        "Send 'help' to see available commands."
    )
