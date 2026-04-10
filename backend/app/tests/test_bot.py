"""
WhatsApp Bid Bot tests — 9 tests covering NLP, audio, user lookup,
bid acceptance/rejection, rate limiting, and idempotency.
"""

from __future__ import annotations

import sys
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from types import ModuleType
from uuid import uuid4


# ── Mock Celery tasks module (celery not installed in test env) ──
_mock_auction_tasks = ModuleType("app.tasks.auction")
_mock_insert_bid = MagicMock()
_mock_auction_tasks.insert_bid_to_db = _mock_insert_bid

# Ensure parent modules exist in sys.modules
if "app.tasks" not in sys.modules:
    _mock_tasks = ModuleType("app.tasks")
    sys.modules["app.tasks"] = _mock_tasks
if "app.core.celery" not in sys.modules:
    _mock_celery_mod = ModuleType("app.core.celery")
    _mock_celery_mod.celery_app = MagicMock()
    sys.modules["app.core.celery"] = _mock_celery_mod
sys.modules["app.tasks.auction"] = _mock_auction_tasks


# ── Helper: build a Meta webhook message dict ──────────────────

def _msg(sender: str, msg_id: str, body: str, msg_type: str = "text", audio_id: str | None = None) -> dict:
    """Build a dict matching Meta's webhook message shape."""
    m: dict = {"from": sender, "id": msg_id, "type": msg_type}
    if msg_type == "text":
        m["text"] = {"body": body}
    if msg_type == "audio" and audio_id:
        m["audio"] = {"id": audio_id}
    return m


# ═══════════════════════════════════════════════════════════════
# 1. Arabic number normalization
# ═══════════════════════════════════════════════════════════════

def test_arabic_number_normalization():
    """خمسمية→500, ألف→1000, ٥٠٠→500, خمسمية وخمسين→550."""
    from app.services.bot.nlp import normalize_arabic_numbers

    assert normalize_arabic_numbers("خمسمية") == "500"
    assert normalize_arabic_numbers("ألف") == "1000"
    assert normalize_arabic_numbers("٥٠٠") == "500"
    assert normalize_arabic_numbers("خمسمية وخمسين") == "550"
    assert normalize_arabic_numbers("ميتين") == "200"
    assert normalize_arabic_numbers("ألفين") == "2000"
    assert normalize_arabic_numbers("٧٥٠") == "750"
    # Spec additions
    assert normalize_arabic_numbers("ميه") == "100"
    assert normalize_arabic_numbers("خمسميه") == "500"
    assert normalize_arabic_numbers("ميّة") == "100"


# ═══════════════════════════════════════════════════════════════
# 2. Bid intent extraction — Arabic text
# ═══════════════════════════════════════════════════════════════

def test_bid_intent_extraction_arabic_text():
    """'بزيد 500 #ABC' → type=bid, amount=500, ref=ABC."""
    from app.services.bot.nlp import extract_intent

    result = extract_intent("بزيد 500 #ABC123")
    assert result.type == "bid"
    assert result.amount == 500
    assert result.auction_ref == "ABC123"

    # Spec pattern: زايد على 500
    result2 = extract_intent("زايد على 300 #XYZ")
    assert result2.type == "bid"
    assert result2.amount == 300

    # Spec pattern: عطي 500
    result3 = extract_intent("عطي 700 #ITEM1")
    assert result3.type == "bid"
    assert result3.amount == 700

    # Amount + دينار
    result4 = extract_intent("500 دينار #TEST")
    assert result4.type == "bid"
    assert result4.amount == 500


# ═══════════════════════════════════════════════════════════════
# 3. Bid intent extraction — English text
# ═══════════════════════════════════════════════════════════════

def test_bid_intent_extraction_english_text():
    """'bid 300 #XYZ' → type=bid, amount=300, ref=XYZ."""
    from app.services.bot.nlp import extract_intent

    result = extract_intent("bid 300 #XYZ789")
    assert result.type == "bid"
    assert result.amount == 300
    assert result.auction_ref == "XYZ789"


# ═══════════════════════════════════════════════════════════════
# 4. Audio transcription mock
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_audio_transcription_mock():
    """Audio transcription returns Arabic text via mocked Whisper."""
    with patch("app.services.bot.service.settings") as mock_settings:
        mock_settings.OPENAI_API_KEY = "test-key"
        mock_settings.WHATSAPP_ACCESS_TOKEN = "test-token"

        mock_responses = [
            MagicMock(status_code=200, json=lambda: {"url": "https://example.com/audio.ogg"}),
            MagicMock(status_code=200, content=b"fake-audio-bytes"),
            MagicMock(status_code=200, json=lambda: {"text": "بزيد خمسمية"}),
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_responses[:2])
        mock_client.post = AsyncMock(return_value=mock_responses[2])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.bot.service.httpx.AsyncClient", return_value=mock_client):
            from app.services.bot.service import transcribe_audio
            result = await transcribe_audio("media-id-123")

        assert result == "بزيد خمسمية"


# ═══════════════════════════════════════════════════════════════
# 5. Unlinked phone gets download link
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_unlinked_phone_gets_download_link(db_session, fake_redis):
    """Unlinked phone gets reply with download link."""
    replies = []

    async def capture_reply(phone, text):
        replies.append((phone, text))

    with patch("app.services.bot.service.send_whatsapp_reply", side_effect=capture_reply):
        from app.services.bot.service import process_whatsapp_message

        await process_whatsapp_message(
            message=_msg("962791111111", "msg-001", "بزيد 500 #ABC"),
            db=db_session,
            redis=fake_redis,
        )

    assert len(replies) == 1
    assert "mzadak.com/download" in replies[0][1]
    assert "غير مرتبط" in replies[0][1]


# ═══════════════════════════════════════════════════════════════
# 6. Bid accepted sends confirmation
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bid_accepted_sends_confirmation(db_session, fake_redis):
    """Valid bid is accepted via Lua — confirmation reply + Celery dispatched."""
    from app.services.auth.models import User, UserRole, UserStatus, KYCStatus
    from app.services.auction.lua_scripts import BidLuaScripts, BidResult

    user = User(
        id=str(uuid4()),
        phone="+962790000001",
        full_name="Bidder",
        full_name_ar="مزايد",
        role=UserRole.BUYER,
        status=UserStatus.ACTIVE,
        kyc_status=KYCStatus.VERIFIED,
        ats_score=400,
        preferred_language="ar",
        fcm_tokens=[],
        is_pro_seller=False,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    replies = []

    async def capture_reply(phone, text):
        replies.append((phone, text))

    mock_result = BidResult(accepted=True, new_price=50000, extended=False)
    mock_listing = {"auction_id": "AUCTION1", "title_ar": "آيفون 15", "title_en": "iPhone 15"}

    with (
        patch("app.services.bot.service.send_whatsapp_reply", side_effect=capture_reply),
        patch.object(BidLuaScripts, "validate_bid", return_value=mock_result),
        patch("app.services.bot.service._search_active_listing", return_value=mock_listing),
    ):
        _mock_insert_bid.reset_mock()
        _mock_insert_bid.delay = MagicMock()

        from app.services.bot.service import process_whatsapp_message
        await process_whatsapp_message(
            message=_msg("962790000001", "msg-bid-001", "بزيد 500 #AUCTION1"),
            db=db_session,
            redis=fake_redis,
        )

    assert len(replies) == 1
    assert "قبول" in replies[0][1] or "تم" in replies[0][1]
    assert "آيفون" in replies[0][1]
    _mock_insert_bid.delay.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# 7. Bid rejected sends reason
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bid_rejected_sends_reason(db_session, fake_redis):
    """Bid too low returns rejection with minimum required."""
    from app.services.auth.models import User, UserRole, UserStatus, KYCStatus
    from app.services.auction.lua_scripts import BidLuaScripts, BidResult

    user = User(
        id=str(uuid4()),
        phone="+962790000002",
        full_name="Low Bidder",
        full_name_ar="مزايد",
        role=UserRole.BUYER,
        status=UserStatus.ACTIVE,
        kyc_status=KYCStatus.VERIFIED,
        ats_score=400,
        preferred_language="ar",
        fcm_tokens=[],
        is_pro_seller=False,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    replies = []

    async def capture_reply(phone, text):
        replies.append((phone, text))

    mock_result = BidResult(
        accepted=False,
        rejection_reason="BID_TOO_LOW",
        min_required=60000,
    )
    mock_listing = {"auction_id": "AUCTION2", "title_ar": "سامسونج", "title_en": "Samsung"}

    with (
        patch("app.services.bot.service.send_whatsapp_reply", side_effect=capture_reply),
        patch.object(BidLuaScripts, "validate_bid", return_value=mock_result),
        patch("app.services.bot.service._search_active_listing", return_value=mock_listing),
    ):
        from app.services.bot.service import process_whatsapp_message
        await process_whatsapp_message(
            message=_msg("962790000002", "msg-bid-002", "بزيد 100 #AUCTION2"),
            db=db_session,
            redis=fake_redis,
        )

    assert len(replies) == 1
    assert "أقل من الحد" in replies[0][1] or "الحد الأدنى" in replies[0][1]


# ═══════════════════════════════════════════════════════════════
# 8. Rate limiting — 5 bids per minute
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_rate_limiting_5_bids_per_minute(db_session, fake_redis):
    """6th bid in 1 minute is rate-limited."""
    from app.services.auth.models import User, UserRole, UserStatus, KYCStatus
    from app.services.auction.lua_scripts import BidLuaScripts, BidResult

    user = User(
        id=str(uuid4()),
        phone="+962790000003",
        full_name="Fast Bidder",
        full_name_ar="مزايد سريع",
        role=UserRole.BUYER,
        status=UserStatus.ACTIVE,
        kyc_status=KYCStatus.VERIFIED,
        ats_score=400,
        preferred_language="ar",
        fcm_tokens=[],
        is_pro_seller=False,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    replies = []

    async def capture_reply(phone, text):
        replies.append((phone, text))

    mock_result = BidResult(accepted=True, new_price=50000, extended=False)
    mock_listing = {"auction_id": "AUCTION3", "title_ar": "ساعة", "title_en": "Watch"}

    with (
        patch("app.services.bot.service.send_whatsapp_reply", side_effect=capture_reply),
        patch.object(BidLuaScripts, "validate_bid", return_value=mock_result),
        patch("app.services.bot.service._search_active_listing", return_value=mock_listing),
    ):
        _mock_insert_bid.reset_mock()
        _mock_insert_bid.delay = MagicMock()

        from app.services.bot.service import process_whatsapp_message

        for i in range(6):
            await process_whatsapp_message(
                message=_msg("962790000003", f"msg-rate-{i}", "بزيد 500 #AUCTION3"),
                db=db_session,
                redis=fake_redis,
            )

    # 5 accepted + 1 rate-limited = 6 replies
    assert len(replies) == 6
    assert "كثرت" in replies[-1][1] or "انتظر" in replies[-1][1]
    assert _mock_insert_bid.delay.call_count == 5


# ═══════════════════════════════════════════════════════════════
# 9. Idempotency — same message_id processed once
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_idempotency_same_message_id_processed_once(db_session, fake_redis):
    """Duplicate message_id is silently ignored."""
    from app.services.auth.models import User, UserRole, UserStatus, KYCStatus

    user = User(
        id=str(uuid4()),
        phone="+962790000004",
        full_name="Idempotent User",
        full_name_ar="مستخدم",
        role=UserRole.BUYER,
        status=UserStatus.ACTIVE,
        kyc_status=KYCStatus.VERIFIED,
        ats_score=400,
        preferred_language="ar",
        fcm_tokens=[],
        is_pro_seller=False,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    replies = []

    async def capture_reply(phone, text):
        replies.append((phone, text))

    with patch("app.services.bot.service.send_whatsapp_reply", side_effect=capture_reply):
        from app.services.bot.service import process_whatsapp_message

        for _ in range(2):
            await process_whatsapp_message(
                message=_msg("962790000004", "msg-duplicate-001", "مساعدة"),
                db=db_session,
                redis=fake_redis,
            )

    # Only 1 reply — second message was deduplicated
    assert len(replies) == 1
