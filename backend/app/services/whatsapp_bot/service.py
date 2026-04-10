"""
WhatsApp Bid Bot — core pipeline (FR-BOT-001 → FR-BOT-010).

Message flow:
  1. Receive inbound message (text or audio)
  2. If audio → transcribe via Whisper (FR-BOT-003)
  3. Extract intent via AraBERT NLP (FR-BOT-004)
  4. If keyword reference → fuzzy search Meilisearch (FR-BOT-005)
  5. Look up MZADAK account from wa_accounts (FR-BOT-002)
  6. If not linked → reply with linking instructions (PM-10-07)
  7. Execute intent (bid / check / help)
  8. Compose Arabic reply (PM-10)
  9. Send reply via Meta Cloud API
"""

from __future__ import annotations

import json
import logging

import httpx
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.whatsapp_bot.models import (
    BotConversation,
    BotIntent,
    ConversationState,
    WaAccount,
)
from app.services.whatsapp_bot.nlp import extract_intent
from app.services.whatsapp_bot.schemas import ParsedIntent, WhatsAppMessage
from app.services.whatsapp_bot import templates
from app.services.whatsapp_bot.transcription import (
    download_whatsapp_media,
    transcribe_audio,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════════

async def handle_message(
    sender_phone: str,
    message: WhatsAppMessage,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Process a single inbound WhatsApp message through the full pipeline."""

    # ── 1. Extract text ──────────────────────────────────────────
    text: str | None = None

    if message.type == "audio" and message.audio:
        audio_bytes = await download_whatsapp_media(message.audio.id)
        if audio_bytes:
            text = await transcribe_audio(audio_bytes)
        if not text:
            await _send_reply(sender_phone, templates.transcription_failed())
            return

    elif message.type == "text" and message.text:
        text = message.text.body.strip()

    elif message.type == "interactive" and message.interactive:
        # Button / list reply — extract the reply payload
        if message.interactive.button_reply:
            text = message.interactive.button_reply.get("id", "")
        elif message.interactive.list_reply:
            text = message.interactive.list_reply.get("id", "")

    if not text:
        await _send_reply(sender_phone, templates.help_message())
        return

    # ── 2. Check for multi-turn conversation state ───────────────
    conversation = await _get_conversation(sender_phone, db)
    if conversation and conversation.state != ConversationState.IDLE:
        await _handle_multi_turn(sender_phone, text, conversation, db, redis)
        return

    # ── 3. NLP intent extraction ─────────────────────────────────
    parsed = await extract_intent(text)
    logger.info(
        "Bot intent: phone=%s intent=%s confidence=%.2f keyword=%s amount=%s",
        sender_phone, parsed.intent, parsed.confidence, parsed.keyword, parsed.amount,
    )

    # ── 4. Dispatch by intent ────────────────────────────────────
    if parsed.intent == "help":
        await _send_reply(sender_phone, templates.help_message())
        return

    if parsed.intent == "link":
        await _send_reply(sender_phone, templates.account_not_linked())
        return

    # ── 5. Look up MZADAK account ────────────────────────────────
    wa_account = await _lookup_account(sender_phone, db)
    if not wa_account:
        await _send_reply(sender_phone, templates.account_not_linked())
        return

    # ── 6. Execute intent ────────────────────────────────────────
    if parsed.intent == "bid":
        await _handle_bid(sender_phone, wa_account, parsed, db, redis)
    elif parsed.intent == "check":
        await _handle_check(sender_phone, wa_account, parsed, db, redis)
    else:
        await _send_reply(sender_phone, templates.help_message())


# ═══════════════════════════════════════════════════════════════
# Intent Handlers
# ═══════════════════════════════════════════════════════════════

async def _handle_bid(
    sender_phone: str,
    wa_account: WaAccount,
    parsed: ParsedIntent,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Handle a bid intent — FR-BOT-006, FR-BOT-007."""

    # ── Rate limit check (FR-BOT-009) ────────────────────────────
    is_limited = await _check_rate_limit(sender_phone, redis)
    if is_limited:
        await _send_reply(sender_phone, templates.rate_limited())
        return

    # ── Need keyword to find auction ─────────────────────────────
    if not parsed.keyword and not parsed.auction_id:
        await _send_reply(sender_phone, templates.help_message())
        return

    # ── Search for auction ───────────────────────────────────────
    auction = None
    if parsed.auction_id:
        auction = await _get_auction_by_id(parsed.auction_id, db)
    else:
        auctions = await _search_auctions(parsed.keyword, redis)
        if not auctions:
            await _send_reply(
                sender_phone,
                templates.no_auction_found(parsed.keyword or ""),
            )
            return

        if len(auctions) == 1:
            auction = auctions[0]
        else:
            # Multiple matches — start disambiguation flow
            await _start_disambiguation(
                sender_phone, auctions, parsed, db,
            )
            return

    if not auction:
        await _send_reply(
            sender_phone,
            templates.no_auction_found(parsed.keyword or ""),
        )
        return

    # ── Need amount ──────────────────────────────────────────────
    if not parsed.amount:
        # Ask for amount in multi-turn
        conversation = await _get_or_create_conversation(sender_phone, db)
        conversation.state = ConversationState.AWAITING_AMOUNT
        conversation.intent = BotIntent.BID
        conversation.context_auction_ids = json.dumps([auction["id"]])
        conversation.context_keyword = auction.get("title", "")
        await db.commit()

        await _send_reply(
            sender_phone,
            f"كم تريد أن تزايد على \"{auction['title']}\"؟\n"
            f"السعر الحالي: {auction['current_price']:.2f} JOD\n\n"
            f"أرسل المبلغ.",
        )
        return

    # ── Place the bid ────────────────────────────────────────────
    await _execute_bid(
        sender_phone, wa_account, auction, parsed.amount, db, redis,
    )


async def _handle_check(
    sender_phone: str,
    wa_account: WaAccount,
    parsed: ParsedIntent,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Handle a status-check intent — FR-BOT-008."""
    if not parsed.keyword:
        await _send_reply(
            sender_phone,
            "أي مزاد تريد الاستفسار عنه؟ أرسل اسم المنتج.",
        )
        return

    auctions = await _search_auctions(parsed.keyword, redis)
    if not auctions:
        await _send_reply(
            sender_phone,
            templates.no_auction_found(parsed.keyword),
        )
        return

    if len(auctions) == 1:
        a = auctions[0]
        await _send_reply(
            sender_phone,
            templates.auction_status(
                auction_title=a["title"],
                current_price=a["current_price"],
                bid_count=a.get("bid_count", 0),
                time_left=a.get("time_left", "غير معروف"),
            ),
        )
    else:
        await _send_reply(
            sender_phone,
            templates.multiple_auctions_found(
                [{"title": a["title"], "current_price": a["current_price"], "auction_id": a["id"]}
                 for a in auctions[:5]],
            ),
        )


# ═══════════════════════════════════════════════════════════════
# Multi-turn Conversation
# ═══════════════════════════════════════════════════════════════

async def _handle_multi_turn(
    sender_phone: str,
    text: str,
    conversation: BotConversation,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Handle follow-up messages in a multi-turn conversation."""

    if conversation.state == ConversationState.AWAITING_AUCTION_CHOICE:
        await _handle_auction_choice(sender_phone, text, conversation, db, redis)

    elif conversation.state == ConversationState.AWAITING_AMOUNT:
        await _handle_amount_input(sender_phone, text, conversation, db, redis)

    elif conversation.state == ConversationState.AWAITING_CONFIRMATION:
        await _handle_confirmation(sender_phone, text, conversation, db, redis)

    else:
        # Reset stale conversation
        conversation.state = ConversationState.IDLE
        await db.commit()
        await _send_reply(sender_phone, templates.help_message())


async def _handle_auction_choice(
    sender_phone: str,
    text: str,
    conversation: BotConversation,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """User picks an auction from disambiguation list."""
    from app.services.whatsapp_bot.arabic_numbers import extract_amount

    choice = extract_amount(text)
    if not choice or not conversation.context_auction_ids:
        conversation.state = ConversationState.IDLE
        await db.commit()
        await _send_reply(sender_phone, templates.help_message())
        return

    auction_ids = json.loads(conversation.context_auction_ids)
    idx = int(choice) - 1

    if idx < 0 or idx >= len(auction_ids):
        await _send_reply(sender_phone, "رقم غير صحيح. حاول مجدداً.")
        return

    auction = await _get_auction_by_id(auction_ids[idx], db)
    if not auction:
        conversation.state = ConversationState.IDLE
        await db.commit()
        await _send_reply(sender_phone, templates.error_generic())
        return

    # If we already have an amount, place the bid
    if conversation.context_amount:
        wa_account = await _lookup_account(sender_phone, db)
        if wa_account:
            conversation.state = ConversationState.IDLE
            await db.commit()
            await _execute_bid(
                sender_phone, wa_account, auction,
                conversation.context_amount, db, redis,
            )
            return

    # Otherwise ask for amount
    conversation.state = ConversationState.AWAITING_AMOUNT
    conversation.context_auction_ids = json.dumps([auction["id"]])
    conversation.context_keyword = auction.get("title", "")
    await db.commit()

    await _send_reply(
        sender_phone,
        f"كم تريد أن تزايد على \"{auction['title']}\"?\n"
        f"السعر الحالي: {auction['current_price']:.2f} JOD",
    )


async def _handle_amount_input(
    sender_phone: str,
    text: str,
    conversation: BotConversation,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """User provides a bid amount."""
    from app.services.whatsapp_bot.arabic_numbers import extract_amount

    amount = extract_amount(text)
    if not amount or amount <= 0:
        await _send_reply(sender_phone, "يُرجى إرسال مبلغ صحيح (مثلاً: 500).")
        return

    auction_ids = json.loads(conversation.context_auction_ids or "[]")
    if not auction_ids:
        conversation.state = ConversationState.IDLE
        await db.commit()
        await _send_reply(sender_phone, templates.error_generic())
        return

    auction = await _get_auction_by_id(auction_ids[0], db)
    if not auction:
        conversation.state = ConversationState.IDLE
        await db.commit()
        await _send_reply(sender_phone, templates.error_generic())
        return

    wa_account = await _lookup_account(sender_phone, db)
    if not wa_account:
        conversation.state = ConversationState.IDLE
        await db.commit()
        await _send_reply(sender_phone, templates.account_not_linked())
        return

    conversation.state = ConversationState.IDLE
    await db.commit()

    await _execute_bid(sender_phone, wa_account, auction, amount, db, redis)


async def _handle_confirmation(
    sender_phone: str,
    text: str,
    conversation: BotConversation,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """User confirms or cancels a pending bid."""
    text_lower = text.strip()
    if text_lower in ("نعم", "اي", "أي", "ايوا", "اه", "yes", "1"):
        # Confirmed — place bid
        if conversation.context_amount and conversation.context_auction_ids:
            auction_ids = json.loads(conversation.context_auction_ids)
            auction = await _get_auction_by_id(auction_ids[0], db)
            wa_account = await _lookup_account(sender_phone, db)
            if auction and wa_account:
                conversation.state = ConversationState.IDLE
                await db.commit()
                await _execute_bid(
                    sender_phone, wa_account, auction,
                    conversation.context_amount, db, redis,
                )
                return

    # Cancelled or error
    conversation.state = ConversationState.IDLE
    await db.commit()
    await _send_reply(sender_phone, "تم إلغاء المزايدة.")


# ═══════════════════════════════════════════════════════════════
# Core Actions
# ═══════════════════════════════════════════════════════════════

async def _execute_bid(
    sender_phone: str,
    wa_account: WaAccount,
    auction: dict,
    amount: float,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Place a bid via the auction service and reply."""
    from app.services.auction.service import place_bid

    # Rate limit per auction
    is_limited = await _check_rate_limit(
        sender_phone, redis, auction_id=auction["id"],
    )
    if is_limited:
        await _send_reply(sender_phone, templates.rate_limited())
        return

    try:
        status, reason = await place_bid(
            auction["id"], wa_account.user_id, amount, redis,
        )
    except Exception as exc:
        logger.error("place_bid failed: %s", exc)
        await _send_reply(sender_phone, templates.error_generic())
        return

    if status == "ACCEPTED":
        await _send_reply(
            sender_phone,
            templates.bid_accepted(auction["title"], amount),
        )
    elif reason == "BID_TOO_LOW":
        await _send_reply(
            sender_phone,
            templates.bid_rejected_too_low(
                auction["title"],
                auction["current_price"],
                auction["current_price"] + auction.get("min_increment", 25.0),
            ),
        )
    elif reason == "AUCTION_NOT_ACTIVE":
        await _send_reply(
            sender_phone,
            templates.bid_rejected_ended(auction["title"]),
        )
    else:
        await _send_reply(sender_phone, templates.error_generic())


async def _start_disambiguation(
    sender_phone: str,
    auctions: list[dict],
    parsed: ParsedIntent,
    db: AsyncSession,
) -> None:
    """Send disambiguation list and set multi-turn state."""
    top5 = auctions[:5]
    conversation = await _get_or_create_conversation(sender_phone, db)
    conversation.state = ConversationState.AWAITING_AUCTION_CHOICE
    conversation.intent = BotIntent(parsed.intent) if parsed.intent in BotIntent.__members__.values() else BotIntent.BID
    conversation.context_auction_ids = json.dumps([a["id"] for a in top5])
    conversation.context_amount = parsed.amount
    conversation.context_keyword = parsed.keyword
    await db.commit()

    await _send_reply(
        sender_phone,
        templates.multiple_auctions_found(
            [{"title": a["title"], "current_price": a["current_price"], "auction_id": a["id"]}
             for a in top5],
        ),
    )


# ═══════════════════════════════════════════════════════════════
# Data Access Helpers
# ═══════════════════════════════════════════════════════════════

async def _lookup_account(
    phone: str, db: AsyncSession,
) -> WaAccount | None:
    """Find a linked WaAccount by phone number (FR-BOT-002)."""
    stmt = select(WaAccount).where(
        WaAccount.wa_phone == phone,
        WaAccount.is_active.is_(True),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_conversation(
    phone: str, db: AsyncSession,
) -> BotConversation | None:
    """Get active conversation for phone, or None."""
    stmt = select(BotConversation).where(
        BotConversation.wa_phone == phone,
    ).order_by(BotConversation.updated_at.desc()).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_or_create_conversation(
    phone: str, db: AsyncSession,
) -> BotConversation:
    """Get or create a conversation record for multi-turn flows."""
    existing = await _get_conversation(phone, db)
    if existing:
        return existing

    conv = BotConversation(wa_phone=phone)
    db.add(conv)
    await db.flush()
    return conv


async def _search_auctions(
    keyword: str | None, redis: Redis,
) -> list[dict]:
    """Fuzzy-search active auctions via Meilisearch (FR-BOT-005)."""
    if not keyword:
        return []

    try:
        import meilisearch

        client = meilisearch.Client(
            settings.MEILISEARCH_URL,
            settings.MEILISEARCH_API_KEY,
        )
        result = client.index("auctions").search(
            keyword,
            {
                "limit": 5,
                "filter": ["status = active"],
                "attributesToRetrieve": [
                    "id", "title", "current_price", "bid_count",
                    "time_left", "min_increment",
                ],
            },
        )
        return result.get("hits", [])
    except Exception as exc:
        logger.error("Meilisearch search failed: %s", exc)
        return []


async def _get_auction_by_id(
    auction_id: str, db: AsyncSession,
) -> dict | None:
    """Fetch auction details by ID from the database.

    Returns a dict matching the Meilisearch hit shape for consistency.
    """
    from app.services.auction.models import Auction

    auction = await db.get(Auction, auction_id)
    if not auction:
        return None

    current_price = float(auction.current_price) if auction.current_price else float(auction.starting_price)
    return {
        "id": auction.id,
        "title": auction.title,
        "current_price": current_price,
        "bid_count": auction.bid_count or 0,
        "time_left": "",  # computed client-side
        "min_increment": float(auction.min_increment) if auction.min_increment else settings.DEFAULT_MIN_INCREMENT,
    }


# ═══════════════════════════════════════════════════════════════
# Rate Limiting (FR-BOT-009)
# ═══════════════════════════════════════════════════════════════

async def _check_rate_limit(
    phone: str,
    redis: Redis,
    *,
    auction_id: str | None = None,
) -> bool:
    """Enforce rate limit: 10 bids/user/auction/minute (matches WebSocket limits).

    Returns True if rate-limited (should block).
    """
    if auction_id:
        key = f"rate:wa_bid:{phone}:{auction_id}"
    else:
        key = f"rate:wa_msg:{phone}"

    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)

    limit = settings.RATE_LIMIT_BID_PER_MINUTE  # 10
    return count > limit


# ═══════════════════════════════════════════════════════════════
# WhatsApp Reply (Meta Cloud API)
# ═══════════════════════════════════════════════════════════════

async def _send_reply(phone: str, text: str) -> bool:
    """Send a free-form text reply via Meta Cloud API.

    Unlike send_whatsapp() in notification/channels.py (which uses
    pre-approved templates for outbound-first messages), this sends
    free-form text within the 24-hour conversation window opened
    by the user's inbound message.
    """
    if not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("WhatsApp not configured — skipping reply to %s", phone)
        return False

    url = (
        f"https://graph.facebook.com/v19.0/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": text},
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=body)

        if resp.status_code == 200:
            return True

        logger.warning(
            "WhatsApp reply failed %d: %s", resp.status_code, resp.text[:200],
        )
        return False
    except Exception as exc:
        logger.error("WhatsApp reply error: %s", exc)
        return False
