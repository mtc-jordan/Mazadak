"""
WebSocket auction server tests — SDD §5.6.

Tests the Socket.IO event handlers directly by mocking the sio
object and Redis, avoiding the need for a real WebSocket transport.

Covers:
  1. Connect: valid JWT + ACTIVE auction → success
  2. Connect: expired/invalid JWT → disconnect with code 4401
  3. Connect: non-ACTIVE auction → disconnect with code 4404
  4. Connect: emits current_state with auction snapshot
  5. Connect: INCRs watcher_count and broadcasts watcher_update
  6. Bid accepted: publishes bid_update to Redis channel
  7. Bid accepted: triggers anti-snipe → publishes timer_extended
  8. Bid rejected: emits bid_rejected to submitting socket only
  9. Disconnect: DECRs watcher_count, broadcasts watcher_update
 10. Reconnect: current_state includes recent_bids for reconciliation
 11. Invalid bid data: emits bid_rejected with INVALID_AMOUNT
 12. Pub/Sub integration: publish reaches FakeRedis subscribers
"""

from __future__ import annotations

import json
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.auction.lua_scripts import BidScript


# ── Helpers ──────────────────────────────────────────────────────

SELLER_ID = str(uuid4())
BIDDER_ID = str(uuid4())


async def _setup_active_auction(fake_redis, auction_id=None, **overrides):
    """Create an ACTIVE auction in FakeRedis. Returns auction_id."""
    if auction_id is None:
        auction_id = str(uuid4())
    defaults = {
        "current_price": "100.0",
        "status": "ACTIVE",
        "seller_id": SELLER_ID,
        "last_bidder": "",
        "bid_count": "0",
        "extension_count": "0",
        "watcher_count": "0",
        "min_increment": "25.0",
    }
    defaults.update(overrides)
    await fake_redis.hset(f"auction:{auction_id}", mapping=defaults)
    await fake_redis.expire(f"auction:{auction_id}", 7200)
    return auction_id


def _make_valid_token(user_id=None):
    """Create a real JWT using the test RSA keys."""
    from app.services.auth.models import User, UserRole, KYCStatus, ATSTier
    from app.services.auth.service import issue_tokens

    user = MagicMock(spec=User)
    user.id = user_id or str(uuid4())
    user.role = UserRole.BUYER
    user.kyc_status = KYCStatus.VERIFIED
    user.ats_score = 500

    access_token, _, _ = issue_tokens(user)
    return access_token, user.id


def _make_expired_token():
    """Create an expired JWT."""
    from app.core.security import _private_key
    from app.core.config import settings
    from jose import jwt
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid4()),
        "role": "buyer",
        "kyc": "verified",
        "ats": 500,
        "jti": uuid4().hex,
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),  # Already expired
    }
    return jwt.encode(payload, _private_key, algorithm=settings.JWT_ALGORITHM)


# ═══════════════════════════════════════════════════════════════════
# Direct handler tests using the ws module functions
# ═══════════════════════════════════════════════════════════════════

class TestWSConnect:
    """Test the connect handler logic."""

    @pytest.mark.asyncio
    async def test_valid_jwt_active_auction_connects(self, fake_redis):
        """Valid JWT + ACTIVE auction → connection accepted."""
        from app.services.auction import ws

        auction_id = await _setup_active_auction(fake_redis)
        token, user_id = _make_valid_token()

        # Mock sio methods
        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        mock_sio = ws.sio
        original_emit = mock_sio.emit
        original_enter = mock_sio.enter_room
        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to, "room": room})

        mock_sio.emit = capture_emit
        mock_sio.enter_room = MagicMock()

        BidScript.reset()
        sid = "test-sid-1"

        with patch.object(ws, "_get_recent_bids", return_value=[]):
            with patch.object(ws, "_ensure_pubsub"):
                result = await ws.connect(
                    sid, {}, {"token": token, "auction_id": auction_id},
                )

        assert result is True
        assert sid in ws._sessions
        assert ws._sessions[sid]["user_id"] == user_id
        assert ws._sessions[sid]["auction_id"] == auction_id

        # Should have emitted current_state and watcher_update
        events = [e["event"] for e in emitted]
        assert "current_state" in events
        assert "watcher_update" in events

        # current_state should have auction data
        cs = next(e for e in emitted if e["event"] == "current_state")
        assert cs["data"]["auction_id"] == auction_id
        assert cs["data"]["current_price"] == 100.0
        assert cs["data"]["status"] == "ACTIVE"

        # Watcher count should be 1
        wu = next(e for e in emitted if e["event"] == "watcher_update")
        assert wu["data"]["watcher_count"] == 1

        # Restore
        mock_sio.emit = original_emit
        mock_sio.enter_room = original_enter
        ws._sessions.clear()

    @pytest.mark.asyncio
    async def test_expired_jwt_disconnects_4401(self, fake_redis):
        """Expired JWT → error 4401 emitted, connection rejected."""
        from app.services.auction import ws

        auction_id = await _setup_active_auction(fake_redis)
        token = _make_expired_token()

        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        emitted = []
        disconnected = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to})

        async def capture_disconnect(sid):
            disconnected.append(sid)

        original_emit = ws.sio.emit
        original_disc = ws.sio.disconnect
        ws.sio.emit = capture_emit
        ws.sio.disconnect = capture_disconnect

        sid = "test-sid-expired"
        result = await ws.connect(
            sid, {}, {"token": token, "auction_id": auction_id},
        )

        assert result is False
        assert sid not in ws._sessions

        # Should have emitted error with code 4401
        err = next((e for e in emitted if e["event"] == "error"), None)
        assert err is not None
        assert err["data"]["code"] == 4401

        assert sid in disconnected

        ws.sio.emit = original_emit
        ws.sio.disconnect = original_disc
        ws._sessions.clear()

    @pytest.mark.asyncio
    async def test_no_auth_disconnects(self, fake_redis):
        """No auth dict → connection rejected."""
        from app.services.auction import ws

        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        disconnected = []

        async def capture_disconnect(sid):
            disconnected.append(sid)

        original_disc = ws.sio.disconnect
        ws.sio.disconnect = capture_disconnect

        sid = "test-sid-noauth"
        result = await ws.connect(sid, {}, None)

        assert result is False
        assert sid in disconnected

        ws.sio.disconnect = original_disc
        ws._sessions.clear()

    @pytest.mark.asyncio
    async def test_nonactive_auction_disconnects_4404(self, fake_redis):
        """Auction not ACTIVE → error 4404, connection rejected."""
        from app.services.auction import ws

        auction_id = await _setup_active_auction(fake_redis, status="ENDED")
        token, _ = _make_valid_token()

        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        emitted = []
        disconnected = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to})

        async def capture_disconnect(sid):
            disconnected.append(sid)

        original_emit = ws.sio.emit
        original_disc = ws.sio.disconnect
        ws.sio.emit = capture_emit
        ws.sio.disconnect = capture_disconnect

        sid = "test-sid-ended"
        result = await ws.connect(
            sid, {}, {"token": token, "auction_id": auction_id},
        )

        assert result is False
        err = next((e for e in emitted if e["event"] == "error"), None)
        assert err is not None
        assert err["data"]["code"] == 4404

        ws.sio.emit = original_emit
        ws.sio.disconnect = original_disc
        ws._sessions.clear()

    @pytest.mark.asyncio
    async def test_nonexistent_auction_disconnects(self, fake_redis):
        """Auction not in Redis → 4404."""
        from app.services.auction import ws

        token, _ = _make_valid_token()
        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        emitted = []
        disconnected = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to})

        async def capture_disconnect(sid):
            disconnected.append(sid)

        original_emit = ws.sio.emit
        original_disc = ws.sio.disconnect
        ws.sio.emit = capture_emit
        ws.sio.disconnect = capture_disconnect

        result = await ws.connect(
            "sid-noauction", {},
            {"token": token, "auction_id": "nonexistent"},
        )

        assert result is False
        err = next((e for e in emitted if e["event"] == "error"), None)
        assert err["data"]["code"] == 4404

        ws.sio.emit = original_emit
        ws.sio.disconnect = original_disc
        ws._sessions.clear()


class TestWSBid:
    """Test the bid event handler."""

    @pytest.mark.asyncio
    async def test_bid_accepted_publishes_to_channel(self, fake_redis):
        """Accepted bid → PUBLISH bid_update to Redis channel."""
        from app.services.auction import ws

        BidScript.reset()
        auction_id = await _setup_active_auction(fake_redis)
        token, user_id = _make_valid_token()

        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        sid = "bid-sid-1"
        ws._sessions[sid] = {
            "user_id": user_id,
            "auction_id": auction_id,
            "connected_at": time.time(),
        }

        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to, "room": room})

        original_emit = ws.sio.emit
        ws.sio.emit = capture_emit

        with patch("app.services.auction.service.check_anti_snipe", new_callable=AsyncMock, return_value=False):
            with patch.dict("sys.modules", {"app.tasks.auction": MagicMock()}):
                await ws.bid(sid, {"amount": 200.0})

        # Check Redis publish log
        published = fake_redis._published
        assert len(published) >= 1

        channel, data_str = published[-1]
        assert channel == f"channel:auction:{auction_id}"
        data = json.loads(data_str)
        assert data["event"] == "bid_update"
        assert data["payload"]["amount"] == 200.0
        assert data["payload"]["user_id"] == user_id

        ws.sio.emit = original_emit
        ws._sessions.clear()

    @pytest.mark.asyncio
    async def test_bid_rejected_emitted_to_submitter_only(self, fake_redis):
        """Rejected bid → bid_rejected emitted to sid only, not room."""
        from app.services.auction import ws

        BidScript.reset()
        auction_id = await _setup_active_auction(fake_redis)

        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        sid = "bid-sid-reject"
        ws._sessions[sid] = {
            "user_id": SELLER_ID,  # Seller bidding → SELLER_CANNOT_BID
            "auction_id": auction_id,
            "connected_at": time.time(),
        }

        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to, "room": room})

        original_emit = ws.sio.emit
        ws.sio.emit = capture_emit

        await ws.bid(sid, {"amount": 200.0})

        # Should emit bid_rejected to the sid only
        reject = next((e for e in emitted if e["event"] == "bid_rejected"), None)
        assert reject is not None
        assert reject["to"] == sid
        assert reject["room"] is None
        assert reject["data"]["reason"] == "SELLER_CANNOT_BID"

        # Should NOT publish to Redis channel
        assert len(fake_redis._published) == 0

        ws.sio.emit = original_emit
        ws._sessions.clear()

    @pytest.mark.asyncio
    async def test_bid_accepted_with_anti_snipe_publishes_timer_extended(self, fake_redis):
        """Accepted bid that triggers anti-snipe → publishes timer_extended."""
        from app.services.auction import ws

        BidScript.reset()
        auction_id = await _setup_active_auction(fake_redis)
        # Set low TTL to trigger anti-snipe
        await fake_redis.expire(f"auction:{auction_id}", 60)

        token, user_id = _make_valid_token()
        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        sid = "bid-sid-antisnipe"
        ws._sessions[sid] = {
            "user_id": user_id,
            "auction_id": auction_id,
            "connected_at": time.time(),
        }

        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to, "room": room})

        original_emit = ws.sio.emit
        ws.sio.emit = capture_emit

        with patch.dict("sys.modules", {"app.tasks.auction": MagicMock()}):
            await ws.bid(sid, {"amount": 200.0})

        # Should have published both bid_update and timer_extended
        channels_published = [ch for ch, _ in fake_redis._published]
        expected_channel = f"channel:auction:{auction_id}"
        assert channels_published.count(expected_channel) == 2

        events_published = []
        for _, data_str in fake_redis._published:
            events_published.append(json.loads(data_str)["event"])

        assert "bid_update" in events_published
        assert "timer_extended" in events_published

        # timer_extended payload should have extension details
        timer_msg = next(
            json.loads(d) for c, d in fake_redis._published
            if json.loads(d)["event"] == "timer_extended"
        )
        assert "new_ttl" in timer_msg["payload"]
        assert timer_msg["payload"]["extension_count"] == 1

        ws.sio.emit = original_emit
        ws._sessions.clear()

    @pytest.mark.asyncio
    async def test_invalid_amount_rejected(self, fake_redis):
        """Non-numeric or missing amount → INVALID_AMOUNT."""
        from app.services.auction import ws

        auction_id = await _setup_active_auction(fake_redis)
        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        sid = "bid-sid-invalid"
        ws._sessions[sid] = {
            "user_id": str(uuid4()),
            "auction_id": auction_id,
            "connected_at": time.time(),
        }

        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to})

        original_emit = ws.sio.emit
        ws.sio.emit = capture_emit

        # Missing amount
        await ws.bid(sid, {})
        # Negative amount
        await ws.bid(sid, {"amount": -10})
        # String amount
        await ws.bid(sid, {"amount": "abc"})

        rejects = [e for e in emitted if e["event"] == "bid_rejected"]
        assert len(rejects) == 3
        for r in rejects:
            assert r["data"]["reason"] == "INVALID_AMOUNT"

        ws.sio.emit = original_emit
        ws._sessions.clear()

    @pytest.mark.asyncio
    async def test_bid_without_session_rejected(self, fake_redis):
        """Bid from unconnected sid → NOT_CONNECTED."""
        from app.services.auction import ws

        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to})

        original_emit = ws.sio.emit
        ws.sio.emit = capture_emit

        await ws.bid("unknown-sid", {"amount": 200.0})

        assert len(emitted) == 1
        assert emitted[0]["data"]["reason"] == "NOT_CONNECTED"

        ws.sio.emit = original_emit


class TestWSDisconnect:
    """Test the disconnect handler."""

    @pytest.mark.asyncio
    async def test_disconnect_decrements_watcher_count(self, fake_redis):
        """Disconnect DECRs watcher_count."""
        from app.services.auction import ws

        auction_id = await _setup_active_auction(fake_redis, watcher_count="3")
        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        sid = "disc-sid-1"
        ws._sessions[sid] = {
            "user_id": str(uuid4()),
            "auction_id": auction_id,
            "connected_at": time.time(),
        }

        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "room": room})

        original_emit = ws.sio.emit
        ws.sio.emit = capture_emit
        ws.sio.leave_room = MagicMock()
        ws.sio.manager = MagicMock()
        ws.sio.manager.get_participants = MagicMock(return_value=iter([]))

        await ws.disconnect(sid)

        # Session should be cleaned up
        assert sid not in ws._sessions

        # Watcher count should be 2 (was 3)
        state = await fake_redis.hgetall(f"auction:{auction_id}")
        assert state["watcher_count"] == "2"

        # Should broadcast watcher_update
        wu = next((e for e in emitted if e["event"] == "watcher_update"), None)
        assert wu is not None
        assert wu["data"]["watcher_count"] == 2

        ws.sio.emit = original_emit

    @pytest.mark.asyncio
    async def test_disconnect_floors_watcher_at_zero(self, fake_redis):
        """Watcher count doesn't go negative."""
        from app.services.auction import ws

        auction_id = await _setup_active_auction(fake_redis, watcher_count="0")
        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        sid = "disc-sid-floor"
        ws._sessions[sid] = {
            "user_id": str(uuid4()),
            "auction_id": auction_id,
            "connected_at": time.time(),
        }

        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "room": room})

        original_emit = ws.sio.emit
        ws.sio.emit = capture_emit
        ws.sio.leave_room = MagicMock()
        ws.sio.manager = MagicMock()
        ws.sio.manager.get_participants = MagicMock(return_value=iter([]))

        await ws.disconnect(sid)

        state = await fake_redis.hgetall(f"auction:{auction_id}")
        assert state["watcher_count"] == "0"

        wu = next(e for e in emitted if e["event"] == "watcher_update")
        assert wu["data"]["watcher_count"] == 0

        ws.sio.emit = original_emit

    @pytest.mark.asyncio
    async def test_disconnect_unknown_sid_noop(self, fake_redis):
        """Disconnecting an unknown sid is a no-op."""
        from app.services.auction import ws

        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        # Should not raise
        await ws.disconnect("never-connected")


class TestWSReconnect:
    """Test reconnection with state reconciliation."""

    @pytest.mark.asyncio
    async def test_reconnect_includes_recent_bids(self, fake_redis):
        """On reconnect, current_state includes recent_bids list."""
        from app.services.auction import ws

        auction_id = await _setup_active_auction(fake_redis)
        token, user_id = _make_valid_token()

        ws.set_redis_factory(lambda: fake_redis)
        ws._sessions.clear()

        mock_bids = [
            {"id": str(uuid4()), "user_id": str(uuid4()), "amount": 150.0,
             "currency": "JOD", "created_at": "2026-01-01T00:00:00"},
            {"id": str(uuid4()), "user_id": str(uuid4()), "amount": 200.0,
             "currency": "JOD", "created_at": "2026-01-01T00:01:00"},
        ]

        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to})

        original_emit = ws.sio.emit
        ws.sio.emit = capture_emit
        ws.sio.enter_room = MagicMock()

        sid = "reconnect-sid"
        with patch.object(ws, "_get_recent_bids", return_value=mock_bids):
            with patch.object(ws, "_ensure_pubsub"):
                await ws.connect(
                    sid, {}, {"token": token, "auction_id": auction_id},
                )

        cs = next(e for e in emitted if e["event"] == "current_state")
        assert "recent_bids" in cs["data"]
        assert len(cs["data"]["recent_bids"]) == 2
        assert cs["data"]["recent_bids"][0]["amount"] == 150.0
        assert cs["data"]["recent_bids"][1]["amount"] == 200.0

        ws.sio.emit = original_emit
        ws._sessions.clear()


class TestWSPubSub:
    """Test Redis Pub/Sub integration with FakeRedis."""

    @pytest.mark.asyncio
    async def test_publish_reaches_subscriber(self, fake_redis):
        """Messages published to a channel reach FakePubSub subscribers."""
        import asyncio

        pubsub = fake_redis.pubsub()
        await pubsub.subscribe("channel:auction:test-123")

        await fake_redis.publish("channel:auction:test-123", json.dumps({
            "event": "bid_update",
            "payload": {"amount": 300.0},
        }))

        # Read the message from the async generator
        messages = []
        async for msg in pubsub.listen():
            messages.append(msg)
            break  # Just read one

        assert len(messages) == 1
        assert messages[0]["type"] == "message"
        data = json.loads(messages[0]["data"])
        assert data["event"] == "bid_update"
        assert data["payload"]["amount"] == 300.0

        await pubsub.aclose()

    @pytest.mark.asyncio
    async def test_publish_returns_subscriber_count(self, fake_redis):
        """PUBLISH returns number of subscribers that received the message."""
        count = await fake_redis.publish("empty-channel", "test")
        assert count == 0

        pubsub = fake_redis.pubsub()
        await pubsub.subscribe("test-ch")

        count = await fake_redis.publish("test-ch", "hello")
        assert count == 1

        await pubsub.aclose()

    @pytest.mark.asyncio
    async def test_published_messages_logged(self, fake_redis):
        """All published messages are recorded in _published for assertions."""
        await fake_redis.publish("ch1", "msg1")
        await fake_redis.publish("ch2", "msg2")

        assert len(fake_redis._published) == 2
        assert fake_redis._published[0] == ("ch1", "msg1")
        assert fake_redis._published[1] == ("ch2", "msg2")


class TestWSServerConfig:
    """Verify Socket.IO server configuration."""

    def test_ping_interval_30s(self):
        from app.services.auction.ws import sio
        assert sio.eio.ping_interval == 30

    def test_ping_timeout_10s(self):
        from app.services.auction.ws import sio
        assert sio.eio.ping_timeout == 10

    def test_sio_app_mounted_on_fastapi(self):
        from app.main import app

        # Check that /ws route is mounted
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/ws" in routes or any("/ws" in str(r) for r in app.routes)
