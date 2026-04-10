"""
WebSocket auction server tests — SDD §5.6.

Tests the /auction namespace Socket.IO event handlers directly by
calling the AuctionNamespace methods with mocked sio internals.

Covers:
  1. Connect: valid JWT + ACTIVE auction -> success
  2. Connect: expired/invalid JWT -> ConnectionRefusedError('4401')
  3. Connect: non-ACTIVE auction -> ConnectionRefusedError('4404')
  4. Connect: SCHEDULED auction -> success (allowed)
  5. Connect: emits current_state with auction snapshot + recent_bids
  6. Connect: INCRs watcher_count and broadcasts watcher_update
  7. place_bid accepted: emits bid_confirmed to bidder + publishes bid_update
  8. place_bid accepted with anti-snipe: publishes timer_extended
  9. place_bid rejected: emits bid_rejected to submitting socket only
 10. place_bid invalid amount: emits bid_rejected with INVALID_AMOUNT
 11. Disconnect: DECRs watcher_count, broadcasts watcher_update
 12. Disconnect: floors watcher count at 0
 13. ping: responds with pong
 14. mask_user_id: privacy masking
 15. Pub/Sub integration: publish reaches FakeRedis subscribers
 16. Server config: ping interval/timeout
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.auction.lua_scripts import BidLuaScripts
from app.services.auction.service import _k, _root


# -- Helpers ----------------------------------------------------------

SELLER_ID = str(uuid4())
BIDDER_ID = str(uuid4())


async def _setup_active_auction(fake_redis, auction_id=None, **overrides):
    """Create an ACTIVE auction using individual Redis keys. Returns auction_id."""
    if auction_id is None:
        auction_id = str(uuid4())
    defaults = {
        "price": "10000",
        "status": "ACTIVE",
        "seller": SELLER_ID,
        "last_bidder": "",
        "bid_count": "0",
        "extension_ct": "0",
        "watcher_ct": "0",
        "min_increment": "2500",
        "reserve": "0",
    }
    defaults.update(overrides)
    for suffix, value in defaults.items():
        await fake_redis.set(_k(auction_id, suffix), str(value))
    await fake_redis.set(_root(auction_id), "active", ex=7200)
    return auction_id


def _make_valid_token(user_id=None):
    """Create a real JWT using the test RSA keys."""
    from app.services.auth.models import User, UserRole, UserStatus, KYCStatus
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
        "exp": now - timedelta(hours=1),
    }
    return jwt.encode(payload, _private_key, algorithm=settings.JWT_ALGORITHM)


def _get_ns(fake_redis):
    """Get the AuctionNamespace instance with redis factory injected."""
    from app.services.auction import ws
    ws.set_redis_factory(lambda: fake_redis)
    # Get the registered /auction namespace
    ns = ws.sio.namespace_handlers.get("/auction")
    return ns, ws


# =====================================================================
# Connect tests
# =====================================================================

class TestWSConnect:
    """Test the on_connect handler in /auction namespace."""

    @pytest.mark.asyncio
    async def test_valid_jwt_active_auction_connects(self, fake_redis):
        """Valid JWT + ACTIVE auction -> connection accepted, session saved."""
        ns, ws = _get_ns(fake_redis)
        auction_id = await _setup_active_auction(fake_redis)
        token, user_id = _make_valid_token()

        BidLuaScripts.reset()
        sid = "test-sid-1"

        emitted = []
        rooms_entered = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to, "room": room})

        saved_sessions = {}

        async def capture_save_session(s, data, namespace=None):
            saved_sessions[s] = data

        async def capture_get_session(s, namespace=None):
            return saved_sessions.get(s, {})

        original_emit = ns.emit
        ns.emit = capture_emit
        ns.enter_room = lambda s, r: rooms_entered.append((s, r))
        ns.save_session = capture_save_session
        ns.get_session = capture_get_session

        with patch.object(ws, "_get_recent_bids", return_value=[]):
            with patch.object(ws, "_ensure_pubsub", return_value=None):
                await ns.on_connect(
                    sid, {}, {"token": token, "auction_id": auction_id},
                )

        # Session should be saved
        assert sid in saved_sessions
        assert saved_sessions[sid]["user_id"] == user_id
        assert saved_sessions[sid]["auction_id"] == auction_id

        # Should have joined the room
        assert (sid, f"auction_{auction_id}") in rooms_entered

        # Should have emitted current_state and watcher_update
        events = [e["event"] for e in emitted]
        assert "current_state" in events
        assert "watcher_update" in events

        cs = next(e for e in emitted if e["event"] == "current_state")
        assert cs["data"]["auction_id"] == auction_id
        assert cs["data"]["current_price"] == 10000
        assert cs["data"]["status"] == "ACTIVE"

        wu = next(e for e in emitted if e["event"] == "watcher_update")
        assert wu["data"]["watcher_count"] == 1

        ns.emit = original_emit

    @pytest.mark.asyncio
    async def test_expired_jwt_raises_4401(self, fake_redis):
        """Expired JWT -> ConnectionRefusedError('4401')."""
        ns, ws = _get_ns(fake_redis)
        auction_id = await _setup_active_auction(fake_redis)
        token = _make_expired_token()

        sid = "test-sid-expired"

        with pytest.raises(ConnectionRefusedError) as exc_info:
            await ns.on_connect(
                sid, {}, {"token": token, "auction_id": auction_id},
            )
        assert "4401" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_no_auth_raises_4401(self, fake_redis):
        """No auth dict -> ConnectionRefusedError('4401')."""
        ns, ws = _get_ns(fake_redis)

        with pytest.raises(ConnectionRefusedError) as exc_info:
            await ns.on_connect("test-sid-noauth", {}, None)
        assert "4401" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_nonactive_auction_raises_4404(self, fake_redis):
        """Auction not ACTIVE/SCHEDULED -> ConnectionRefusedError('4404')."""
        ns, ws = _get_ns(fake_redis)
        auction_id = await _setup_active_auction(fake_redis, status="ENDED")
        token, _ = _make_valid_token()

        with pytest.raises(ConnectionRefusedError) as exc_info:
            await ns.on_connect(
                "test-sid-ended", {},
                {"token": token, "auction_id": auction_id},
            )
        assert "4404" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_nonexistent_auction_raises_4404(self, fake_redis):
        """Auction not in Redis -> ConnectionRefusedError('4404')."""
        ns, ws = _get_ns(fake_redis)
        token, _ = _make_valid_token()

        with pytest.raises(ConnectionRefusedError) as exc_info:
            await ns.on_connect(
                "sid-noauction", {},
                {"token": token, "auction_id": "nonexistent"},
            )
        assert "4404" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_scheduled_auction_connects(self, fake_redis):
        """SCHEDULED auction -> connection accepted."""
        ns, ws = _get_ns(fake_redis)
        auction_id = await _setup_active_auction(fake_redis, status="SCHEDULED")
        token, user_id = _make_valid_token()

        BidLuaScripts.reset()
        sid = "test-sid-scheduled"

        emitted = []
        saved_sessions = {}

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to, "room": room})

        async def capture_save_session(s, data, namespace=None):
            saved_sessions[s] = data

        original_emit = ns.emit
        ns.emit = capture_emit
        ns.enter_room = lambda s, r: None
        ns.save_session = capture_save_session

        with patch.object(ws, "_get_recent_bids", return_value=[]):
            with patch.object(ws, "_ensure_pubsub", return_value=None):
                await ns.on_connect(
                    sid, {}, {"token": token, "auction_id": auction_id},
                )

        # Session saved = connection accepted
        assert sid in saved_sessions
        assert saved_sessions[sid]["user_id"] == user_id

        ns.emit = original_emit


# =====================================================================
# place_bid tests
# =====================================================================

class TestWSPlaceBid:
    """Test the on_place_bid handler."""

    @pytest.mark.asyncio
    async def test_bid_accepted_confirms_and_publishes(self, fake_redis):
        """Accepted bid -> bid_confirmed to bidder + PUBLISH bid_update."""
        ns, ws = _get_ns(fake_redis)

        BidLuaScripts.reset()
        auction_id = await _setup_active_auction(fake_redis)
        token, user_id = _make_valid_token()

        sid = "bid-sid-1"
        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to, "room": room})

        async def capture_get_session(s, namespace=None):
            return {
                "user_id": user_id,
                "auction_id": auction_id,
                "connected_at": time.time(),
            }

        original_emit = ns.emit
        ns.emit = capture_emit
        ns.get_session = capture_get_session

        with patch.dict("sys.modules", {"app.tasks.auction": MagicMock()}):
            await ns.on_place_bid(sid, {"amount": 20000})

        # bid_confirmed emitted to bidder
        confirmed = next((e for e in emitted if e["event"] == "bid_confirmed"), None)
        assert confirmed is not None
        assert confirmed["to"] == sid
        assert confirmed["data"]["amount"] == 20000

        # Redis publish log: bid_update
        published = fake_redis._published
        assert len(published) >= 1

        channel, data_str = published[-1]
        assert channel == f"channel:auction:{auction_id}"
        data = json.loads(data_str)
        assert data["event"] == "bid_update"
        assert data["payload"]["amount"] == 20000
        # user_id should be masked in broadcast
        assert "***" in data["payload"]["user_id"]

        ns.emit = original_emit

    @pytest.mark.asyncio
    async def test_bid_rejected_emitted_to_submitter_only(self, fake_redis):
        """Rejected bid -> bid_rejected emitted to sid only."""
        ns, ws = _get_ns(fake_redis)

        BidLuaScripts.reset()
        auction_id = await _setup_active_auction(fake_redis)

        sid = "bid-sid-reject"
        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to, "room": room})

        async def capture_get_session(s, namespace=None):
            return {
                "user_id": SELLER_ID,  # Seller bidding -> SELLER_CANNOT_BID
                "auction_id": auction_id,
                "connected_at": time.time(),
            }

        original_emit = ns.emit
        ns.emit = capture_emit
        ns.get_session = capture_get_session

        await ns.on_place_bid(sid, {"amount": 20000})

        reject = next((e for e in emitted if e["event"] == "bid_rejected"), None)
        assert reject is not None
        assert reject["to"] == sid
        assert reject["room"] is None
        assert reject["data"]["reason"] == "SELLER_CANNOT_BID"

        # Should NOT publish to Redis channel
        assert len(fake_redis._published) == 0

        ns.emit = original_emit

    @pytest.mark.asyncio
    async def test_bid_accepted_with_anti_snipe_publishes_timer_extended(self, fake_redis):
        """Accepted bid that triggers anti-snipe -> publishes timer_extended."""
        ns, ws = _get_ns(fake_redis)

        BidLuaScripts.reset()
        auction_id = await _setup_active_auction(fake_redis)
        # Set low TTL to trigger anti-snipe
        await fake_redis.set(_root(auction_id), "active", ex=60)

        token, user_id = _make_valid_token()
        sid = "bid-sid-antisnipe"

        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to, "room": room})

        async def capture_get_session(s, namespace=None):
            return {
                "user_id": user_id,
                "auction_id": auction_id,
                "connected_at": time.time(),
            }

        original_emit = ns.emit
        ns.emit = capture_emit
        ns.get_session = capture_get_session

        with patch.dict("sys.modules", {"app.tasks.auction": MagicMock()}):
            await ns.on_place_bid(sid, {"amount": 20000})

        # Should have published both bid_update and timer_extended
        channels_published = [ch for ch, _ in fake_redis._published]
        expected_channel = f"channel:auction:{auction_id}"
        assert channels_published.count(expected_channel) == 2

        events_published = []
        for _, data_str in fake_redis._published:
            events_published.append(json.loads(data_str)["event"])

        assert "bid_update" in events_published
        assert "timer_extended" in events_published

        timer_msg = next(
            json.loads(d) for c, d in fake_redis._published
            if json.loads(d)["event"] == "timer_extended"
        )
        assert "new_ttl" in timer_msg["payload"]
        assert timer_msg["payload"]["extension_count"] == 1

        ns.emit = original_emit

    @pytest.mark.asyncio
    async def test_invalid_amount_rejected(self, fake_redis):
        """Non-numeric or missing amount -> INVALID_AMOUNT."""
        ns, ws = _get_ns(fake_redis)

        auction_id = await _setup_active_auction(fake_redis)
        sid = "bid-sid-invalid"

        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to})

        async def capture_get_session(s, namespace=None):
            return {
                "user_id": str(uuid4()),
                "auction_id": auction_id,
                "connected_at": time.time(),
            }

        original_emit = ns.emit
        ns.emit = capture_emit
        ns.get_session = capture_get_session

        # Missing amount
        await ns.on_place_bid(sid, {})
        # Negative amount
        await ns.on_place_bid(sid, {"amount": -10})
        # String amount
        await ns.on_place_bid(sid, {"amount": "abc"})

        rejects = [e for e in emitted if e["event"] == "bid_rejected"]
        assert len(rejects) == 3
        for r in rejects:
            assert r["data"]["reason"] == "INVALID_AMOUNT"

        ns.emit = original_emit

    @pytest.mark.asyncio
    async def test_bid_without_session_rejected(self, fake_redis):
        """Bid from unconnected sid -> NOT_CONNECTED."""
        ns, ws = _get_ns(fake_redis)

        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to})

        async def capture_get_session(s, namespace=None):
            return {}

        original_emit = ns.emit
        ns.emit = capture_emit
        ns.get_session = capture_get_session

        await ns.on_place_bid("unknown-sid", {"amount": 200})

        assert len(emitted) == 1
        assert emitted[0]["data"]["reason"] == "NOT_CONNECTED"

        ns.emit = original_emit


# =====================================================================
# Disconnect tests
# =====================================================================

class TestWSDisconnect:
    """Test the on_disconnect handler."""

    @pytest.mark.asyncio
    async def test_disconnect_decrements_watcher_count(self, fake_redis):
        """Disconnect DECRs watcher_count via Redis DECR."""
        ns, ws = _get_ns(fake_redis)

        auction_id = await _setup_active_auction(fake_redis, watcher_ct="3")

        sid = "disc-sid-1"
        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "room": room})

        async def capture_get_session(s, namespace=None):
            return {
                "user_id": str(uuid4()),
                "auction_id": auction_id,
                "connected_at": time.time(),
            }

        original_emit = ns.emit
        ns.emit = capture_emit
        ns.get_session = capture_get_session
        ns.leave_room = lambda s, r: None
        ns.server = MagicMock()
        ns.server.manager.get_participants = MagicMock(return_value=iter([]))

        await ns.on_disconnect(sid)

        # Watcher count should be 2 (was 3, DECR'd)
        watcher_ct = await fake_redis.get(_k(auction_id, "watcher_ct"))
        assert watcher_ct == "2"

        wu = next((e for e in emitted if e["event"] == "watcher_update"), None)
        assert wu is not None
        assert wu["data"]["watcher_count"] == 2

        ns.emit = original_emit

    @pytest.mark.asyncio
    async def test_disconnect_floors_watcher_at_zero(self, fake_redis):
        """Watcher count doesn't go negative (floors at 0)."""
        ns, ws = _get_ns(fake_redis)

        auction_id = await _setup_active_auction(fake_redis, watcher_ct="0")

        sid = "disc-sid-floor"
        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "room": room})

        async def capture_get_session(s, namespace=None):
            return {
                "user_id": str(uuid4()),
                "auction_id": auction_id,
                "connected_at": time.time(),
            }

        original_emit = ns.emit
        ns.emit = capture_emit
        ns.get_session = capture_get_session
        ns.leave_room = lambda s, r: None
        ns.server = MagicMock()
        ns.server.manager.get_participants = MagicMock(return_value=iter([]))

        await ns.on_disconnect(sid)

        watcher_ct = await fake_redis.get(_k(auction_id, "watcher_ct"))
        assert watcher_ct == "0"

        wu = next(e for e in emitted if e["event"] == "watcher_update")
        assert wu["data"]["watcher_count"] == 0

        ns.emit = original_emit

    @pytest.mark.asyncio
    async def test_disconnect_unknown_sid_noop(self, fake_redis):
        """Disconnecting an unknown sid (empty session) is a no-op."""
        ns, ws = _get_ns(fake_redis)

        async def capture_get_session(s, namespace=None):
            return {}

        ns.get_session = capture_get_session

        # Should not raise
        await ns.on_disconnect("never-connected")


# =====================================================================
# Ping/Pong tests
# =====================================================================

class TestWSPing:
    """Test the on_ping handler."""

    @pytest.mark.asyncio
    async def test_ping_responds_with_pong(self, fake_redis):
        """Client ping -> server pong with timestamp."""
        ns, ws = _get_ns(fake_redis)

        emitted = []

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to})

        original_emit = ns.emit
        ns.emit = capture_emit

        sid = "ping-sid"
        await ns.on_ping(sid)

        assert len(emitted) == 1
        assert emitted[0]["event"] == "pong"
        assert "timestamp" in emitted[0]["data"]
        assert emitted[0]["to"] == sid

        ns.emit = original_emit


# =====================================================================
# Reconnect / state reconciliation
# =====================================================================

class TestWSReconnect:
    """Test reconnection with state reconciliation."""

    @pytest.mark.asyncio
    async def test_reconnect_includes_recent_bids(self, fake_redis):
        """On reconnect, current_state includes recent_bids list."""
        ns, ws = _get_ns(fake_redis)

        auction_id = await _setup_active_auction(fake_redis)
        token, user_id = _make_valid_token()

        mock_bids = [
            {"id": str(uuid4()), "user_id": "t***123", "amount": 15000,
             "currency": "JOD", "created_at": "2026-01-01T00:00:00"},
            {"id": str(uuid4()), "user_id": "a***456", "amount": 20000,
             "currency": "JOD", "created_at": "2026-01-01T00:01:00"},
        ]

        emitted = []
        saved_sessions = {}

        async def capture_emit(event, data=None, to=None, room=None, **kw):
            emitted.append({"event": event, "data": data, "to": to})

        async def capture_save_session(s, data, namespace=None):
            saved_sessions[s] = data

        original_emit = ns.emit
        ns.emit = capture_emit
        ns.enter_room = lambda s, r: None
        ns.save_session = capture_save_session

        BidLuaScripts.reset()
        sid = "reconnect-sid"
        with patch.object(ws, "_get_recent_bids", return_value=mock_bids):
            with patch.object(ws, "_ensure_pubsub", return_value=None):
                await ns.on_connect(
                    sid, {}, {"token": token, "auction_id": auction_id},
                )

        cs = next(e for e in emitted if e["event"] == "current_state")
        assert "recent_bids" in cs["data"]
        assert len(cs["data"]["recent_bids"]) == 2
        assert cs["data"]["recent_bids"][0]["amount"] == 15000
        assert cs["data"]["recent_bids"][1]["amount"] == 20000

        ns.emit = original_emit


# =====================================================================
# mask_user_id
# =====================================================================

class TestMaskUserId:
    """Test the mask_user_id privacy helper."""

    def test_normal_uuid(self):
        from app.services.auction.ws import mask_user_id
        uid = "abc12345-6789-def0-1234-567890abcdef"
        masked = mask_user_id(uid)
        assert masked == "a***def"

    def test_short_id(self):
        from app.services.auction.ws import mask_user_id
        assert mask_user_id("ab") == "***"
        assert mask_user_id("") == "***"
        assert mask_user_id(None) == "***"

    def test_exactly_5_chars(self):
        from app.services.auction.ws import mask_user_id
        masked = mask_user_id("12345")
        assert masked == "1***345"


# =====================================================================
# Pub/Sub integration
# =====================================================================

class TestWSPubSub:
    """Test Redis Pub/Sub integration with FakeRedis."""

    @pytest.mark.asyncio
    async def test_publish_reaches_subscriber(self, fake_redis):
        """Messages published to a channel reach FakePubSub subscribers."""
        pubsub = fake_redis.pubsub()
        await pubsub.subscribe("channel:auction:test-123")

        await fake_redis.publish("channel:auction:test-123", json.dumps({
            "event": "bid_update",
            "payload": {"amount": 30000},
        }))

        messages = []
        async for msg in pubsub.listen():
            messages.append(msg)
            break

        assert len(messages) == 1
        assert messages[0]["type"] == "message"
        data = json.loads(messages[0]["data"])
        assert data["event"] == "bid_update"
        assert data["payload"]["amount"] == 30000

        await pubsub.aclose()

    @pytest.mark.asyncio
    async def test_publish_returns_subscriber_count(self, fake_redis):
        """PUBLISH returns number of subscribers."""
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


# =====================================================================
# Server config
# =====================================================================

class TestWSServerConfig:
    """Verify Socket.IO server configuration."""

    def test_ping_interval_30s(self):
        from app.services.auction.ws import sio
        assert sio.eio.ping_interval == 30

    def test_ping_timeout_10s(self):
        from app.services.auction.ws import sio
        assert sio.eio.ping_timeout == 10

    def test_auction_namespace_registered(self):
        from app.services.auction.ws import sio
        assert "/auction" in sio.namespace_handlers

    def test_room_name_format(self):
        from app.services.auction.ws import _room
        assert _room("abc-123") == "auction_abc-123"

    def test_channel_name_format(self):
        from app.services.auction.ws import _channel
        assert _channel("abc-123") == "channel:auction:abc-123"
