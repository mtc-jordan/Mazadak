"""
Full-flow integration tests — end-to-end verification.

TEST 1: Auth flow (register → verify OTP → GET /auth/me)
TEST 2: Listing + auction + bid flow
TEST 3: Snap-to-List pipeline
TEST 4: Escrow full lifecycle
TEST 5: Search Arabic query

All tests use the in-process FastAPI test client with FakeRedis +
in-memory SQLite. External services (S3, CLIP, GPT-4o, Celery,
Meilisearch, Checkout.com) are mocked.
"""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timedelta, timezone
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.services.auth import service as auth_service
from app.tests.conftest import make_listing_data


# ── Mock Celery modules (not installed in test env) ──────────────

if "app.core.celery" not in sys.modules:
    _mock_celery_mod = ModuleType("app.core.celery")
    _mock_celery_mod.celery_app = MagicMock()
    sys.modules["app.core.celery"] = _mock_celery_mod
if "app.tasks" not in sys.modules:
    sys.modules["app.tasks"] = ModuleType("app.tasks")
if "app.tasks.auction" not in sys.modules:
    _m = ModuleType("app.tasks.auction")
    _m.insert_bid_to_db = MagicMock()
    sys.modules["app.tasks.auction"] = _m
if "app.tasks.escrow" not in sys.modules:
    _m2 = ModuleType("app.tasks.escrow")
    sys.modules["app.tasks.escrow"] = _m2


# ═══════════════════════════════════════════════════════════════════
#  TEST 1 — Auth flow end to end
# ═══════════════════════════════════════════════════════════════════


class TestAuthFlowE2E:
    """Register → verify OTP → GET /auth/me → tokens work."""

    async def test_register_sends_otp(self, client, mock_sms):
        """POST /auth/register with valid Jordan phone returns 200 + otp_sent."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={"phone": "+962799999999"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["otp_sent"] is True
        mock_sms.assert_called_once()

    async def test_verify_otp_returns_tokens(self, client, fake_redis, mock_sms, db_session):
        """POST /auth/verify-otp → 200, user_id is UUID, tokens present."""
        phone = "+962799999999"

        # 1. Register (sends OTP, stores hash in FakeRedis)
        await client.post("/api/v1/auth/register", json={"phone": phone})

        # 2. Extract OTP from mock_sms call args
        sms_body = mock_sms.call_args[0][1]
        otp = re.search(r"\b(\d{6})\b", sms_body).group(1)

        # 3. Verify OTP
        resp = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone": phone, "otp": otp},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert "user" in data
        user = data["user"]
        assert user["id"] is not None
        assert len(user["id"]) == 36  # UUID4 with hyphens

    async def test_get_me_returns_user_with_ats(self, client, fake_redis, mock_sms, db_session):
        """After auth, GET /auth/me returns user with ats_score=400."""
        phone = "+962799999998"

        # Register + verify
        await client.post("/api/v1/auth/register", json={"phone": phone})
        sms_body = mock_sms.call_args[0][1]
        otp = re.search(r"\b(\d{6})\b", sms_body).group(1)
        verify_resp = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone": phone, "otp": otp},
        )
        token = verify_resp.json()["access_token"]

        # GET /auth/me with token
        me_resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_resp.status_code == 200
        me = me_resp.json()
        assert me["ats_score"] == 400  # new user default
        assert me["id"] is not None

    async def test_tokens_used_in_subsequent_requests(self, client, fake_redis, mock_sms, db_session):
        """Access token from verify-otp works for authenticated endpoints."""
        phone = "+962799999997"
        await client.post("/api/v1/auth/register", json={"phone": phone})
        otp = re.search(r"\b(\d{6})\b", mock_sms.call_args[0][1]).group(1)
        verify_resp = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone": phone, "otp": otp},
        )
        token = verify_resp.json()["access_token"]

        # Authenticated request should succeed
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        # Unauthenticated should fail
        unauth_resp = await client.get("/api/v1/auth/me")
        assert unauth_resp.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════
#  TEST 2 — Listing + auction + bid flow
# ═══════════════════════════════════════════════════════════════════


class TestListingAuctionBidFlow:
    """Create listing → publish → init auction → place bid → verify."""

    async def test_create_and_publish_listing(
        self, client, verified_user, verified_auth_headers, fake_redis, db_session
    ):
        """POST /listings/ → POST /listings/{id}/publish → 200."""
        listing_data = make_listing_data()

        # Create listing (trailing slash to match router path)
        resp = await client.post(
            "/api/v1/listings/",
            json=listing_data,
            headers=verified_auth_headers,
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        listing_id = resp.json()["id"]
        assert listing_id is not None

        # Publish — mock image count + moderation check
        with (
            patch("app.services.listing.service._count_listing_images", new_callable=AsyncMock) as mock_img,
            patch("app.services.listing.service._run_moderation", new_callable=AsyncMock) as mock_mod,
        ):
            mock_img.return_value = 3
            mock_mod.return_value = {"score": 20, "flags": []}
            pub_resp = await client.post(
                f"/api/v1/listings/{listing_id}/publish",
                headers=verified_auth_headers,
            )
        assert pub_resp.status_code == 200, f"Expected 200, got {pub_resp.status_code}: {pub_resp.text}"

    async def test_bid_accepted_and_redis_updated(
        self, verified_user, fake_redis
    ):
        """Place a bid via auction service, verify Redis state."""
        from app.services.auction.service import place_bid, _root

        auction_id = str(uuid4())
        bidder_id = str(uuid4())
        seller_id = verified_user.id

        # Manually set up auction state in Redis (mimics initialize_auction)
        root = _root(auction_id)
        await fake_redis.set(f"{root}:price", "10000")
        await fake_redis.set(f"{root}:status", "ACTIVE")
        await fake_redis.set(f"{root}:seller", seller_id)
        await fake_redis.set(f"{root}:last_bidder", "")
        await fake_redis.set(f"{root}:bid_count", "0")
        await fake_redis.set(f"{root}:min_increment", "2500")

        # Place bid
        result = await place_bid(
            auction_id=auction_id,
            user_id=bidder_id,
            amount=12500,
            redis=fake_redis,
        )
        assert result.accepted is True
        assert result.new_price == 12500

        # Verify Redis state
        bid_count = await fake_redis.get(f"{root}:bid_count")
        assert bid_count == "1"
        current_price = await fake_redis.get(f"{root}:price")
        assert current_price == "12500"
        last_bidder = await fake_redis.get(f"{root}:last_bidder")
        assert last_bidder == bidder_id

    async def test_bid_below_minimum_rejected(
        self, verified_user, fake_redis
    ):
        """Bid below current_price + min_increment is rejected."""
        from app.services.auction.service import place_bid, _root

        auction_id = str(uuid4())
        root = _root(auction_id)
        await fake_redis.set(f"{root}:price", "10000")
        await fake_redis.set(f"{root}:status", "ACTIVE")
        await fake_redis.set(f"{root}:seller", verified_user.id)
        await fake_redis.set(f"{root}:last_bidder", "")
        await fake_redis.set(f"{root}:bid_count", "0")
        await fake_redis.set(f"{root}:min_increment", "2500")

        result = await place_bid(
            auction_id=auction_id,
            user_id=str(uuid4()),
            amount=11000,  # Below 10000 + 2500 = 12500
            redis=fake_redis,
        )
        assert result.accepted is False
        assert result.rejection_reason == "BID_TOO_LOW"


# ═══════════════════════════════════════════════════════════════════
#  TEST 3 — Snap-to-List pipeline
# ═══════════════════════════════════════════════════════════════════


class TestSnapToListPipeline:
    """POST /ai/snap-to-list with mocked S3/CLIP/GPT → response < 8s."""

    async def test_pipeline_happy_path_under_8s(self, fake_redis):
        """Full pipeline returns valid response under 8 seconds."""
        from app.services.ai.schemas import SnapToListRequest
        from app.services.ai.snap_to_list import run_snap_to_list_pipeline

        request = SnapToListRequest(
            image_s3_keys=["test/img_0.jpg", "test/img_1.jpg", "test/img_2.jpg"]
        )

        mock_clip = {
            "categories": [
                {"name": "electronics", "category_id": 1, "confidence": 85.0},
                {"name": "toys", "category_id": 11, "confidence": 5.0},
                {"name": "other", "category_id": 99, "confidence": 3.0},
            ],
            "brand": "Samsung",
            "condition": "like_new",
            "clip_confidence": 85.0,
        }
        mock_gpt = {
            "title_ar": "هاتف سامسونج جالاكسي S24",
            "title_en": "Samsung Galaxy S24",
            "description_ar": "هاتف ذكي بحالة ممتازة " * 15,
            "description_en": "Smartphone in excellent condition " * 15,
        }
        mock_price = {
            "price_low": 200.0,
            "price_high": 500.0,
            "median": 350.0,
            "suggested_start": 300.0,
            "confidence": "high",
            "comparable_count": 25,
        }

        start = time.monotonic()

        with (
            patch("app.services.ai.snap_to_list.download_images_from_s3", new_callable=AsyncMock) as dl,
            patch("app.services.ai.snap_to_list.run_clip_classification", new_callable=AsyncMock) as clip,
            patch("app.services.ai.snap_to_list.generate_descriptions", new_callable=AsyncMock) as gpt,
            patch("app.services.ai.snap_to_list.get_price_estimate", new_callable=AsyncMock) as price,
        ):
            dl.return_value = [b"fake_bytes"] * 3
            clip.return_value = mock_clip
            gpt.return_value = mock_gpt
            price.return_value = mock_price

            result = await run_snap_to_list_pipeline(request, user_id=str(uuid4()), redis=fake_redis)

        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 8000, f"Pipeline took {elapsed_ms:.0f}ms (>8s)"
        assert result.title_en == "Samsung Galaxy S24"
        assert result.title_ar == "هاتف سامسونج جالاكسي S24"
        assert result.price_low == 200.0
        assert result.price_high == 500.0
        assert result.suggested_start == 300.0

    async def test_pipeline_gpt_failure_returns_clip_only(self, fake_redis):
        """When GPT-4o fails, pipeline returns CLIP result with blank descriptions."""
        from app.services.ai.schemas import SnapToListRequest
        from app.services.ai.snap_to_list import run_snap_to_list_pipeline

        request = SnapToListRequest(
            image_s3_keys=["test/a.jpg", "test/b.jpg", "test/c.jpg"]
        )

        mock_clip = {
            "categories": [
                {"name": "electronics", "category_id": 1, "confidence": 80.0},
            ],
            "brand": "Apple",
            "condition": "good",
            "clip_confidence": 80.0,
        }
        mock_price = {
            "price_low": 100.0,
            "price_high": 300.0,
            "median": 200.0,
            "suggested_start": 150.0,
            "confidence": "medium",
            "comparable_count": 10,
        }

        with (
            patch("app.services.ai.snap_to_list.download_images_from_s3", new_callable=AsyncMock) as dl,
            patch("app.services.ai.snap_to_list.run_clip_classification", new_callable=AsyncMock) as clip,
            patch("app.services.ai.snap_to_list.generate_descriptions", new_callable=AsyncMock) as gpt,
            patch("app.services.ai.snap_to_list.get_price_estimate", new_callable=AsyncMock) as price,
        ):
            dl.return_value = [b"fake"] * 3
            clip.return_value = mock_clip
            import asyncio as _aio
            gpt.side_effect = _aio.TimeoutError("GPT-4o timeout")
            price.return_value = mock_price

            result = await run_snap_to_list_pipeline(request, user_id=str(uuid4()), redis=fake_redis)

        # Should still return a result (CLIP-only fallback)
        assert result is not None
        assert result.category_id == 1


# ═══════════════════════════════════════════════════════════════════
#  TEST 4 — Escrow full lifecycle
# ═══════════════════════════════════════════════════════════════════


class TestEscrowLifecycle:
    """Walk through the 12-state escrow FSM via valid transitions."""

    @pytest.fixture
    async def escrow_db(self):
        """Async SQLite session with escrow tables."""
        from sqlalchemy import Text, event
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from app.core.database import Base
        from app.services.escrow.models import Escrow, EscrowEvent

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        def _register_funcs(dbapi_conn, _):
            import uuid
            dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))
            dbapi_conn.create_function("now", 0, lambda: "2026-04-09T00:00:00")

        event.listen(engine.sync_engine, "connect", _register_funcs)

        patch_targets = []
        for col in (Escrow.__table__.c.evidence_s3_keys, Escrow.__table__.c.evidence_hashes, EscrowEvent.__table__.c.meta):
            patch_targets.append((col, col.type))
            col.type = Text()

        try:
            async with engine.begin() as conn:
                await conn.run_sync(
                    Base.metadata.create_all,
                    tables=[Escrow.__table__, EscrowEvent.__table__],
                )
        finally:
            for col, orig_type in patch_targets:
                col.type = orig_type

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            yield session
        await engine.dispose()

    async def _insert_escrow(self, db, state="payment_pending", **overrides):
        from sqlalchemy import insert
        from app.services.escrow.models import Escrow

        defaults = dict(
            id=str(uuid4()),
            auction_id=str(uuid4()),
            winner_id=str(uuid4()),
            seller_id=str(uuid4()),
            amount=500.0,
            currency="JOD",
            transition_count=0,
            retry_count=0,
        )
        defaults.update(overrides)
        defaults["state"] = state
        await db.execute(insert(Escrow.__table__).values(**defaults))
        await db.commit()
        return defaults

    def _get_fsm(self):
        sys.modules.pop("app.services.escrow.fsm", None)
        with patch.dict("sys.modules", {
            "app.tasks.escrow": MagicMock(),
            "app.core.celery": MagicMock(),
            "celery": MagicMock(),
        }):
            from app.services.escrow import fsm
        return fsm

    async def test_full_escrow_lifecycle(self, escrow_db):
        """Walk through valid escrow transitions matching VALID_TRANSITIONS map.

        payment_pending → funds_held → shipping_requested → label_generated
        → shipped → in_transit → delivered → inspection_period.
        """
        fsm = self._get_fsm()
        row = await self._insert_escrow(escrow_db)
        eid = UUID(row["id"])
        winner_id = UUID(row["winner_id"])
        seller_id = UUID(row["seller_id"])
        system_id = uuid4()  # system actor UUID

        # 1. payment_pending → funds_held
        escrow = await fsm.transition_escrow(
            eid, "funds_held", winner_id,
            "webhook", "webhook.payment_captured", {}, escrow_db,
        )
        assert escrow.state == "funds_held"

        # 2. funds_held → shipping_requested
        escrow = await fsm.transition_escrow(
            eid, "shipping_requested", system_id,
            "system", "auto_ship_request", {}, escrow_db,
        )
        assert escrow.state == "shipping_requested"

        # 3. shipping_requested → label_generated
        escrow = await fsm.transition_escrow(
            eid, "label_generated", seller_id,
            "seller", "seller_generated_label", {"label_url": "https://example.com/label"}, escrow_db,
        )
        assert escrow.state == "label_generated"

        # 4. label_generated → shipped
        escrow = await fsm.transition_escrow(
            eid, "shipped", seller_id,
            "seller", "seller_shipped", {"tracking": "JO123456"}, escrow_db,
        )
        assert escrow.state == "shipped"

        # 5. shipped → in_transit
        escrow = await fsm.transition_escrow(
            eid, "in_transit", system_id,
            "system", "carrier_in_transit", {}, escrow_db,
        )
        assert escrow.state == "in_transit"

        # 6. in_transit → delivered
        escrow = await fsm.transition_escrow(
            eid, "delivered", system_id,
            "system", "delivery_confirmed", {}, escrow_db,
        )
        assert escrow.state == "delivered"

        # 7. delivered → inspection_period
        escrow = await fsm.transition_escrow(
            eid, "inspection_period", winner_id,
            "buyer", "buyer_confirmed_receipt", {}, escrow_db,
        )
        assert escrow.state == "inspection_period"

        # Verify event log has 7 transitions
        from sqlalchemy import select
        from app.services.escrow.models import EscrowEvent

        result = await escrow_db.execute(
            select(EscrowEvent).where(EscrowEvent.escrow_id == str(eid))
        )
        events = result.scalars().all()
        assert len(events) == 7

    async def test_invalid_transition_rejected(self, escrow_db):
        """payment_pending cannot jump to in_transit (skip states)."""
        fsm = self._get_fsm()
        row = await self._insert_escrow(escrow_db, state="payment_pending")

        with pytest.raises(Exception):
            await fsm.transition_escrow(
                UUID(row["id"]), "in_transit", UUID(row["winner_id"]),
                "system", "skip_transition", {}, escrow_db,
            )

    async def test_terminal_state_cannot_transition(self, escrow_db):
        """Released (terminal) cannot transition to anything."""
        fsm = self._get_fsm()
        row = await self._insert_escrow(escrow_db, state="released")

        with pytest.raises(Exception):
            await fsm.transition_escrow(
                UUID(row["id"]), "funds_held", UUID(row["winner_id"]),
                "system", "invalid", {}, escrow_db,
            )


# ═══════════════════════════════════════════════════════════════════
#  TEST 5 — Search Arabic query
# ═══════════════════════════════════════════════════════════════════


class TestSearchArabicQuery:
    """Search for آيفون returns results under 200ms."""

    async def test_arabic_search_returns_results(self):
        """Search for 'آيفون' returns non-empty results with matching titles."""
        from app.services.search.service import search_listings
        from app.services.search.schemas import SearchRequest

        mock_hits = [
            {
                "id": str(uuid4()),
                "title_ar": "آيفون 15 برو ماكس",
                "title_en": "iPhone 15 Pro Max",
                "category_id": 1,
                "condition": "like_new",
                "starting_price": 50000,
                "current_price": 55000,
                "image_url": "",
                "is_charity": False,
                "is_certified": False,
                "location_city": "Amman",
                "location_country": "JO",
                "bid_count": 5,
                "ends_at_timestamp": 1735689600,
            },
            {
                "id": str(uuid4()),
                "title_ar": "آيفون 14 برو",
                "title_en": "iPhone 14 Pro",
                "category_id": 1,
                "condition": "good",
                "starting_price": 30000,
                "current_price": 32000,
                "image_url": "",
                "is_charity": False,
                "is_certified": False,
                "location_city": "Zarqa",
                "location_country": "JO",
                "bid_count": 2,
                "ends_at_timestamp": 1735690000,
            },
        ]

        mock_meili_response = {
            "hits": mock_hits,
            "estimatedTotalHits": 2,
            "processingTimeMs": 12,
            "facetDistribution": {"category_id": {"1": 2}},
        }

        # q must be min_length=1
        req = SearchRequest(q="آيفون")

        start = time.monotonic()

        with patch("app.services.search.service._get_client") as mock_client:
            mock_index = MagicMock()
            mock_index.search.return_value = mock_meili_response
            mock_client_inst = MagicMock()
            mock_client_inst.index.return_value = mock_index
            mock_client.return_value = mock_client_inst

            result = await search_listings(req)

        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 200, f"Search took {elapsed_ms:.0f}ms (>200ms)"
        assert result.total > 0
        assert len(result.hits) == 2
        # All results contain iPhone/آيفون in title
        for hit in result.hits:
            title_combined = f"{hit.title_ar} {hit.title_en}".lower()
            assert "آيفون" in title_combined or "iphone" in title_combined

    async def test_arabic_search_response_time(self):
        """Search service processes request under 200ms even with mock latency."""
        from app.services.search.service import search_listings
        from app.services.search.schemas import SearchRequest

        mock_response = {
            "hits": [
                {
                    "id": str(uuid4()),
                    "title_ar": "آيفون 13",
                    "title_en": "iPhone 13",
                    "category_id": 1,
                    "condition": "good",
                    "starting_price": 20000,
                    "current_price": 22000,
                    "image_url": "",
                    "is_charity": False,
                    "is_certified": False,
                    "location_city": "Irbid",
                    "location_country": "JO",
                    "bid_count": 1,
                    "ends_at_timestamp": 1735689600,
                },
            ],
            "estimatedTotalHits": 1,
            "processingTimeMs": 5,
            "facetDistribution": {},
        }

        req = SearchRequest(q="آيفون")

        start = time.monotonic()

        with patch("app.services.search.service._get_client") as mock_client:
            mock_index = MagicMock()
            mock_index.search.return_value = mock_response
            inst = MagicMock()
            inst.index.return_value = mock_index
            mock_client.return_value = inst

            result = await search_listings(req)

        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 200
        assert len(result.hits) == 1
        assert "آيفون" in result.hits[0].title_ar
