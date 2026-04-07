"""
Shared test fixtures — mock Redis, in-process SQLite, FastAPI test client.

Uses a dict-backed FakeRedis for Redis operations, SQLAlchemy async SQLite
for DB, and auto-generated RSA keys for JWT signing.
No external services needed to run tests.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import app


# ── Test RSA keys (generated once per session) ──────────────────

def _ensure_test_keys():
    """Generate RSA keys in memory and patch the security module
    if the key files don't exist on disk."""
    import app.core.security as sec

    if sec._private_key:
        return  # Real keys exist

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sec._private_key = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    sec._public_key = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


_ensure_test_keys()


# ── Fake Redis (dict-backed) ────────────────────────────────────

class FakeRedis:
    """Thread-safe async Redis mock backed by dicts.

    Supports string, Hash, Set, and Lua script commands used by
    the auction engine.  A threading.Lock serialises all mutations
    so that concurrency tests (100-thread bid storms) behave the
    same way a real Redis single-threaded event loop would.
    """

    def __init__(self):
        self._store: dict[str, str] = {}
        self._hashes: dict[str, dict[str, str]] = {}
        self._sets: dict[str, set[str]] = {}
        self._ttls: dict[str, int] = {}
        self._scripts: dict[str, str] = {}   # sha → script body
        self._lock = threading.Lock()
        # Pub/Sub support
        self._channels: dict[str, list] = {}   # channel → [asyncio.Queue, ...]
        self._published: list[tuple[str, str]] = []  # (channel, data) log

    # ── String commands ────────────────────────────────────────

    async def get(self, key: str) -> str | None:
        with self._lock:
            return self._store.get(key)

    async def set(self, key: str, value: str) -> None:
        with self._lock:
            self._store[key] = str(value)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        with self._lock:
            self._store[key] = str(value)
            self._ttls[key] = ttl

    async def incr(self, key: str) -> int:
        with self._lock:
            val = int(self._store.get(key, "0")) + 1
            self._store[key] = str(val)
            return val

    # ── Hash commands ──────────────────────────────────────────

    async def hset(self, key: str, mapping: dict[str, str] | None = None, **kwargs) -> int:
        with self._lock:
            if key not in self._hashes:
                self._hashes[key] = {}
            data = mapping or {}
            data.update(kwargs)
            created = 0
            for k, v in data.items():
                if k not in self._hashes[key]:
                    created += 1
                self._hashes[key][k] = str(v)
            return created

    async def hget(self, key: str, field: str) -> str | None:
        with self._lock:
            return self._hashes.get(key, {}).get(field)

    async def hgetall(self, key: str) -> dict[str, str]:
        with self._lock:
            return dict(self._hashes.get(key, {}))

    async def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        with self._lock:
            if key not in self._hashes:
                self._hashes[key] = {}
            val = int(self._hashes[key].get(field, "0")) + amount
            self._hashes[key][field] = str(val)
            return val

    # ── Set commands ───────────────────────────────────────────

    async def sadd(self, key: str, *members: str) -> int:
        with self._lock:
            if key not in self._sets:
                self._sets[key] = set()
            before = len(self._sets[key])
            self._sets[key].update(members)
            return len(self._sets[key]) - before

    async def sismember(self, key: str, member: str) -> int:
        with self._lock:
            return 1 if member in self._sets.get(key, set()) else 0

    # ── Key commands ───────────────────────────────────────────

    async def expire(self, key: str, ttl: int) -> None:
        with self._lock:
            self._ttls[key] = ttl

    async def ttl(self, key: str) -> int:
        with self._lock:
            if key not in self._store and key not in self._hashes:
                return -2
            return self._ttls.get(key, -1)

    async def delete(self, *keys: str) -> int:
        with self._lock:
            count = 0
            for k in keys:
                found = False
                if k in self._store:
                    del self._store[k]
                    found = True
                if k in self._hashes:
                    del self._hashes[k]
                    found = True
                if k in self._sets:
                    del self._sets[k]
                    found = True
                if found:
                    self._ttls.pop(k, None)
                    count += 1
            return count

    async def exists(self, key: str) -> int:
        with self._lock:
            return 1 if (key in self._store or key in self._hashes) else 0

    # ── Lua script lifecycle (SCRIPT LOAD / EVALSHA / EVAL) ───

    async def script_load(self, script: str) -> str:
        """SCRIPT LOAD — store script, return SHA1 digest."""
        sha = hashlib.sha1(script.encode()).hexdigest()
        with self._lock:
            self._scripts[sha] = script
        return sha

    async def evalsha(self, sha: str, num_keys: int, *args) -> list:
        """EVALSHA — execute a previously loaded script by SHA."""
        with self._lock:
            if sha not in self._scripts:
                raise Exception("NOSCRIPT No matching script")
        return await self._exec_bid_script(args)

    async def eval(self, script: str, num_keys: int, *args) -> list:
        """EVAL — execute script inline (legacy path)."""
        return await self._exec_bid_script(args)

    async def _exec_bid_script(self, args: tuple) -> list:
        """Emulate the BID_VALIDATE_AND_PLACE Lua script atomically.

        The entire read-check-write sequence runs under self._lock,
        mirroring Redis's single-threaded execution model.
        Validation order matches the Lua script: status → seller →
        banned → amount.
        """
        key = args[0]
        user_id = args[1]
        amount = float(args[2])

        with self._lock:
            h = self._hashes.get(key, {})

            status = h.get("status", "")
            seller_id = h.get("seller_id", "")
            current_price = float(h.get("current_price", "0"))
            min_increment = float(h.get("min_increment", "25"))

            # 1. Auction must be ACTIVE
            if status != "ACTIVE":
                return ["REJECTED", "AUCTION_ENDED"]

            # 2. Seller cannot bid on own auction
            if user_id == seller_id:
                return ["REJECTED", "SELLER_CANNOT_BID"]

            # 3. Banned users cannot bid
            if user_id in self._sets.get("banned_users", set()):
                return ["REJECTED", "USER_BANNED"]

            # 4. Bid must exceed current price + minimum increment
            if amount <= (current_price + min_increment):
                return ["REJECTED", "BID_TOO_LOW"]

            # All checks passed — atomically update state
            self._hashes[key]["current_price"] = str(amount)
            self._hashes[key]["last_bidder"] = user_id
            bid_count = int(self._hashes[key].get("bid_count", "0")) + 1
            self._hashes[key]["bid_count"] = str(bid_count)
            return ["ACCEPTED"]

    # ── Pub/Sub commands ─────────────────────────────────────────

    async def publish(self, channel: str, message: str) -> int:
        """PUBLISH — send message to channel subscribers."""
        with self._lock:
            self._published.append((channel, message))
            queues = self._channels.get(channel, [])
            for q in queues:
                q.put_nowait({"type": "message", "channel": channel, "data": message})
            return len(queues)

    def pubsub(self):
        """Return a FakePubSub bound to this FakeRedis."""
        return FakePubSub(self)

    async def aclose(self) -> None:
        pass


class FakePubSub:
    """Minimal Pub/Sub mock that pairs with FakeRedis."""

    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._queue: asyncio.Queue | None = None
        self._channels: list[str] = []

    async def subscribe(self, *channels: str):
        import asyncio as _aio
        self._queue = _aio.Queue()
        with self._redis._lock:
            for ch in channels:
                if ch not in self._redis._channels:
                    self._redis._channels[ch] = []
                self._redis._channels[ch].append(self._queue)
                self._channels.append(ch)

    async def unsubscribe(self, *channels: str):
        with self._redis._lock:
            for ch in channels:
                if ch in self._redis._channels and self._queue in self._redis._channels[ch]:
                    self._redis._channels[ch].remove(self._queue)

    async def listen(self):
        """Async generator yielding messages."""
        if self._queue is None:
            return
        while True:
            msg = await self._queue.get()
            yield msg

    async def aclose(self):
        await self.unsubscribe(*self._channels)


@pytest.fixture
def fake_redis():
    return FakeRedis()


# ── In-memory SQLite async engine ───────────────────────────────

def _register_sqlite_functions(dbapi_conn, connection_record):
    """Register PostgreSQL-compatible functions for SQLite."""
    import uuid

    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))


@pytest.fixture
async def db_session():
    """Yields an async session backed by in-memory SQLite.
    Creates auth + listing + auction tables.
    Note: Escrow tables use ARRAY/JSONB (PostgreSQL-only), so they are
    excluded here. Escrow creation in tests is mocked at the service level."""
    from sqlalchemy import event
    from app.services.auth.models import User, KYCDocument
    from app.services.listing.models import Listing
    from app.services.auction.models import Auction, Bid

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)
    tables = [
        User.__table__, KYCDocument.__table__, Listing.__table__,
        Auction.__table__, Bid.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


# ── FastAPI test client with dependency overrides ───────────────

@pytest.fixture
async def client(fake_redis, db_session):
    """AsyncClient with Redis and DB dependencies overridden."""
    from app.core.redis import get_redis

    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_db] = lambda: db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ── SMS mock ────────────────────────────────────────────────────

@pytest.fixture
def mock_sms():
    """Patch send_sms to capture OTP without real SMS delivery."""
    with patch("app.services.auth.service.send_sms", new_callable=AsyncMock) as m:
        m.return_value = True
        yield m


# ── Auth helpers ────────────────────────────────────────────────

@pytest.fixture
async def test_user(db_session):
    """Create a standard buyer user in the test DB and return it."""
    from app.services.auth.models import User, UserRole, KYCStatus, ATSTier

    user = User(
        id=str(uuid4()),
        phone="+962790000000",
        full_name_ar="مستخدم اختبار",
        full_name_en="Test User",
        role=UserRole.BUYER,
        kyc_status=KYCStatus.PENDING,
        ats_score=400,
        ats_tier=ATSTier.TRUSTED,
        country_code="JO",
        preferred_language="ar",
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    return user


@pytest.fixture
def auth_headers(test_user, fake_redis):
    """Return (headers_dict, access_token, refresh_token, jti) for test_user."""
    from app.services.auth.service import issue_tokens, store_refresh_token

    access_token, refresh_token, jti = issue_tokens(test_user)

    async def _store():
        await store_refresh_token(refresh_token, test_user.id, fake_redis)
    return {
        "headers": {"Authorization": f"Bearer {access_token}"},
        "access_token": access_token,
        "refresh_token": refresh_token,
        "jti": jti,
        "store_refresh": _store,
    }


# ── Listing helpers ─────────────────────────────────────────────

@pytest.fixture
async def verified_user(db_session):
    """Create a KYC-verified seller user."""
    from app.services.auth.models import User, UserRole, KYCStatus, ATSTier

    user = User(
        id=str(uuid4()),
        phone="+962791111111",
        full_name_ar="بائع معتمد",
        full_name_en="Verified Seller",
        role=UserRole.SELLER,
        kyc_status=KYCStatus.VERIFIED,
        ats_score=600,
        ats_tier=ATSTier.PRO,
        country_code="JO",
        preferred_language="ar",
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    return user


@pytest.fixture
def verified_auth_headers(verified_user, fake_redis):
    """Auth headers for KYC-verified seller."""
    from app.services.auth.service import issue_tokens

    access_token, _, jti = issue_tokens(verified_user)
    return {"Authorization": f"Bearer {access_token}"}


def make_listing_data(**overrides) -> dict:
    """Build valid listing creation payload with sensible defaults."""
    data = {
        "title_ar": "سيارة تويوتا كامري 2023",
        "description_ar": "سيارة تويوتا كامري موديل 2023 بحالة ممتازة، قطعت 20 ألف كم فقط، لون أبيض لؤلؤي",
        "category_id": 1,
        "condition": "like_new",
        "starting_price": 100.0,
        "listing_currency": "JOD",
        "duration_hours": 24,
        "image_urls": ["https://example.com/img1.jpg"],
    }
    data.update(overrides)
    return data
