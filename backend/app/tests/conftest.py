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
from app.main import _fastapi_app as app


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

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool | None:
        with self._lock:
            if nx and key in self._store:
                return None  # Key already exists — NX fails
            self._store[key] = str(value)
            if ex is not None:
                self._ttls[key] = ex
            return True

    async def setex(self, key: str, ttl: int, value: str) -> None:
        with self._lock:
            self._store[key] = str(value)
            self._ttls[key] = ttl

    async def incr(self, key: str) -> int:
        with self._lock:
            val = int(self._store.get(key, "0")) + 1
            self._store[key] = str(val)
            return val

    async def decr(self, key: str) -> int:
        with self._lock:
            val = int(self._store.get(key, "0")) - 1
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
            return 1 if (key in self._store or key in self._hashes or key in self._sets) else 0

    # ── Pipeline support ──────────────────────────────────────

    def pipeline(self, transaction: bool = True) -> "FakePipeline":
        """Return a pipeline that buffers commands and executes them."""
        return FakePipeline(self)

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
        return await self._exec_bid_script(num_keys, args)

    async def eval(self, script: str, num_keys: int, *args) -> list:
        """EVAL — execute script inline (legacy path)."""
        return await self._exec_bid_script(num_keys, args)

    async def _exec_bid_script(self, num_keys: int, args: tuple) -> list:
        """Emulate the BID_VALIDATION_SCRIPT Lua script atomically.

        Mirrors the EXACT Lua logic — lazy reads, same check order,
        same return shapes.

        KEYS[1-9]: price, status, seller, last_bidder, bid_count,
                   banned_set, root_key, extension_ct, min_increment
        ARGV: bid_amount, bidder_id
        """
        keys = args[:num_keys]
        argv = args[num_keys:]

        price_key     = keys[0] if len(keys) > 0 else ""
        status_key    = keys[1] if len(keys) > 1 else ""
        seller_key    = keys[2] if len(keys) > 2 else ""
        last_key      = keys[3] if len(keys) > 3 else ""
        bids_key      = keys[4] if len(keys) > 4 else ""
        banned_key    = keys[5] if len(keys) > 5 else ""
        ttl_key       = keys[6] if len(keys) > 6 else ""
        ext_key       = keys[7] if len(keys) > 7 else ""
        increment_key = keys[8] if len(keys) > 8 else ""

        bid_amount = int(argv[0]) if len(argv) > 0 else 0
        bidder_id  = argv[1] if len(argv) > 1 else ""

        with self._lock:
            # Read increment upfront (matches Lua)
            increment = int(self._store.get(increment_key, "0"))

            # Check 1: Auction must be ACTIVE
            status = self._store.get(status_key, "")
            if status != "ACTIVE":
                return ["REJECTED", "AUCTION_NOT_ACTIVE"]

            # Check 2: Bidder cannot be the seller
            seller = self._store.get(seller_key, "")
            if seller == bidder_id:
                return ["REJECTED", "SELLER_CANNOT_BID"]

            # Check 3: Bidder not in banned set
            if bidder_id in self._sets.get(banned_key, set()):
                return ["REJECTED", "BIDDER_BANNED"]

            # Check 4: Bid amount must exceed current price + min increment
            current_price = int(self._store.get(price_key, "0"))
            min_bid = current_price + increment
            if bid_amount < min_bid:
                return ["REJECTED", "BID_TOO_LOW", str(min_bid)]

            # All checks passed — update atomically
            self._store[price_key] = str(bid_amount)
            self._store[last_key] = bidder_id
            bid_count = int(self._store.get(bids_key, "0")) + 1
            self._store[bids_key] = str(bid_count)

            # Anti-snipe: if TTL <= 180s, extend by 180s
            ttl = self._ttls.get(ttl_key, -1)
            extended = False

            if ttl > 0 and ttl <= 180:
                self._ttls[ttl_key] = ttl + 180
                ext_ct = int(self._store.get(ext_key, "0")) + 1
                self._store[ext_key] = str(ext_ct)
                extended = True

            if extended:
                return ["ACCEPTED", str(bid_amount), "EXTENDED", str(ttl + 180)]
            else:
                return ["ACCEPTED", str(bid_amount), "NORMAL", str(ttl)]

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


class FakePipeline:
    """Minimal Redis pipeline mock for FakeRedis.

    Buffers commands and executes them sequentially via execute().
    Supports: get, set, ttl, incr, expire, delete, exists.
    """

    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._commands: list[tuple[str, tuple, dict]] = []

    def get(self, key: str) -> "FakePipeline":
        self._commands.append(("get", (key,), {}))
        return self

    def set(self, key: str, value: str, ex: int | None = None) -> "FakePipeline":
        self._commands.append(("set", (key, value), {"ex": ex}))
        return self

    def ttl(self, key: str) -> "FakePipeline":
        self._commands.append(("ttl", (key,), {}))
        return self

    def incr(self, key: str) -> "FakePipeline":
        self._commands.append(("incr", (key,), {}))
        return self

    def expire(self, key: str, ttl: int) -> "FakePipeline":
        self._commands.append(("expire", (key, ttl), {}))
        return self

    def delete(self, *keys: str) -> "FakePipeline":
        self._commands.append(("delete", keys, {}))
        return self

    def exists(self, key: str) -> "FakePipeline":
        self._commands.append(("exists", (key,), {}))
        return self

    async def execute(self) -> list:
        results = []
        for cmd, args, kwargs in self._commands:
            method = getattr(self._redis, cmd)
            result = await method(*args, **kwargs)
            results.append(result)
        self._commands.clear()
        return results


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

# Patch PostgreSQL-only types for SQLite compatibility
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy import JSON, Text
from sqlalchemy.ext.compiler import compiles

@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):
    return "TEXT"


def _register_sqlite_functions(dbapi_conn, connection_record):
    """Register PostgreSQL-compatible functions for SQLite."""
    import uuid

    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))
    dbapi_conn.create_function("now", 0, lambda: "2026-04-08T00:00:00")


@pytest.fixture
async def db_session():
    """Yields an async session backed by in-memory SQLite.
    Creates auth + listing + auction tables.
    Note: Escrow tables use ARRAY/JSONB (PostgreSQL-only), so they are
    excluded here. Escrow creation in tests is mocked at the service level."""
    from sqlalchemy import event
    from app.services.auth.models import User, UserKycDocument, RefreshToken
    from app.services.listing.models import Listing, ListingImage
    from app.services.auction.models import Auction, Bid

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)
    tables = [
        User.__table__, UserKycDocument.__table__, RefreshToken.__table__,
        Listing.__table__, ListingImage.__table__, Auction.__table__, Bid.__table__,
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
    from app.services.auth.models import User, UserRole, UserStatus, KYCStatus

    user = User(
        id=str(uuid4()),
        phone="+962790000000",
        full_name="Test User",
        full_name_ar="مستخدم اختبار",
        role=UserRole.BUYER,
        status=UserStatus.PENDING_KYC,
        kyc_status=KYCStatus.NOT_STARTED,
        ats_score=400,
        preferred_language="ar",
        fcm_tokens=[],
        is_pro_seller=False,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    return user


@pytest.fixture
def auth_headers(test_user, fake_redis):
    """Return (headers_dict, access_token, refresh_token, jti) for test_user."""
    from app.services.auth.service import issue_tokens

    access_token, refresh_token, jti = issue_tokens(test_user)

    return {
        "headers": {"Authorization": f"Bearer {access_token}"},
        "access_token": access_token,
        "refresh_token": refresh_token,
        "jti": jti,
    }


# ── Listing helpers ─────────────────────────────────────────────

@pytest.fixture
async def verified_user(db_session):
    """Create a KYC-verified seller user."""
    from app.services.auth.models import User, UserRole, UserStatus, KYCStatus

    user = User(
        id=str(uuid4()),
        phone="+962791111111",
        full_name="Verified Seller",
        full_name_ar="بائع معتمد",
        role=UserRole.SELLER,
        status=UserStatus.ACTIVE,
        kyc_status=KYCStatus.VERIFIED,
        ats_score=600,
        preferred_language="ar",
        fcm_tokens=[],
        is_pro_seller=False,
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
    """Build valid listing creation payload with sensible defaults.

    All prices in INTEGER cents (min 100 = 1 JOD).
    starts_at/ends_at must be in the future.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    data = {
        "title_ar": "سيارة تويوتا كامري 2023",
        "title_en": "Toyota Camry 2023",
        "category_id": 1,
        "condition": "like_new",
        "starting_price": 10000,  # 100 JOD in cents
        "min_increment": 2500,
        "starts_at": (now + timedelta(minutes=10)).isoformat(),
        "ends_at": (now + timedelta(hours=25)).isoformat(),
    }
    data.update(overrides)
    return data
