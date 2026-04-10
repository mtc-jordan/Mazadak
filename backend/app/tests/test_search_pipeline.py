"""
Tests for search pipeline — FR-SRCH-001 → FR-SRCH-012.

7 tests:
  1. test_search_arabic_iphone_returns_results  — 'آيفون' matches iPhone listings
  2. test_search_synonym_samsung               — 'سامسونج' matches samsung
  3. test_autocomplete_under_50ms              — timing with mock Meilisearch
  4. test_filter_price_range                   — min/max price filter built correctly
  5. test_filter_certified_only                — is_certified filter
  6. test_fallback_to_postgres_when_meilisearch_down — degraded_mode=True
  7. test_search_logged_to_clickhouse           — ClickHouse INSERT called
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import JSON, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.search.schemas import (
    SearchFilters,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SuggestHit,
    SuggestResponse,
)


# -- Fake Redis for suggest caching -----------------------------------

class FakeRedis:
    """Minimal async Redis mock for suggest cache tests."""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._lock = threading.Lock()

    async def get(self, key: str) -> str | None:
        with self._lock:
            return self._store.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        with self._lock:
            self._store[key] = str(value)

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_redis():
    return FakeRedis()


# -- Mock Meilisearch helpers -----------------------------------------

def _make_meili_hit(**overrides) -> dict:
    """Build a Meilisearch hit dict with sensible defaults."""
    defaults = {
        "id": str(uuid4()),
        "title_ar": "آيفون 15 برو",
        "title_en": "iPhone 15 Pro",
        "category_id": 1,
        "condition": "like_new",
        "starting_price": 50000,
        "current_price": 55000,
        "image_url": "thumb.jpg",
        "is_charity": False,
        "is_certified": False,
        "location_city": "Amman",
        "location_country": "JO",
        "bid_count": 3,
        "ends_at_timestamp": int((datetime.now(timezone.utc) + timedelta(hours=12)).timestamp()),
    }
    defaults.update(overrides)
    return defaults


def _make_meili_result(hits: list[dict], total: int = 0, time_ms: int = 5) -> dict:
    """Build a Meilisearch search() return dict."""
    return {
        "hits": hits,
        "estimatedTotalHits": total or len(hits),
        "processingTimeMs": time_ms,
        "facetDistribution": {
            "category_id": {"1": len(hits)},
            "condition": {"like_new": len(hits)},
        },
    }


# -- SQLite fixture for fallback tests --------------------------------

def _register_sqlite_functions(dbapi_conn, connection_record):
    import uuid as _uuid
    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(_uuid.uuid4()))
    dbapi_conn.create_function("now", 0, lambda: "2026-04-08T00:00:00")


@pytest.fixture
async def search_db():
    """Async SQLite session with listing tables for fallback test."""
    from sqlalchemy import event
    from app.core.database import Base
    from app.services.auth.models import User, UserKycDocument, RefreshToken
    from app.services.listing.models import Listing, ListingImage

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)

    # Patch JSONB -> JSON for SQLite
    patch_targets = []
    jsonb_cols = [
        Listing.__table__.c.moderation_flags,
        User.__table__.c.fcm_tokens,
        RefreshToken.__table__.c.device_info,
    ]
    for col in jsonb_cols:
        patch_targets.append((col, col.type))
        col.type = JSON()

    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                UserKycDocument.__table__,
                RefreshToken.__table__,
                Listing.__table__,
                ListingImage.__table__,
            ],
        )

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    for col, orig_type in patch_targets:
        col.type = orig_type
    await engine.dispose()


async def _create_listing(db: AsyncSession, **overrides) -> str:
    """Insert a listing for fallback tests."""
    from app.services.listing.models import Listing

    lid = overrides.pop("id", str(uuid4()))
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=lid,
        seller_id=str(uuid4()),
        category_id=1,
        title_ar="آيفون 15 برو ماكس",
        title_en="iPhone 15 Pro Max",
        description_ar="",
        description_en="",
        condition="like_new",
        status="active",
        is_certified=False,
        is_charity=False,
        starting_price=50000,
        current_price=55000,
        bid_count=3,
        watcher_count=0,
        min_increment=2500,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=23),
        extension_count=0,
        location_city="Amman",
        location_country="JO",
        ai_generated=False,
        moderation_status="approved",
        moderation_flags=[],
        view_count=0,
    )
    defaults.update(overrides)
    listing = Listing(**defaults)
    db.add(listing)
    await db.commit()
    return lid


# =====================================================================
#  TEST 1: Arabic search 'آيفون' returns iPhone results
# =====================================================================

class TestSearchArabicIphone:

    @pytest.mark.asyncio
    async def test_search_arabic_iphone_returns_results(self):
        """Search for 'آيفون' returns iPhone listings via Meilisearch."""
        hits = [
            _make_meili_hit(title_ar="آيفون 15 برو", title_en="iPhone 15 Pro"),
            _make_meili_hit(title_ar="آيفون 14", title_en="iPhone 14"),
        ]
        mock_result = _make_meili_result(hits, total=2)

        mock_index = MagicMock()
        mock_index.search.return_value = mock_result

        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import search_listings

            request = SearchRequest(q="آيفون")
            response = await search_listings(request)

        assert response.total == 2
        assert len(response.hits) == 2
        assert response.hits[0].title_ar == "آيفون 15 برو"
        assert response.hits[1].title_en == "iPhone 14"
        # Verify Meilisearch was called with Arabic query
        mock_index.search.assert_called_once()
        assert mock_index.search.call_args[0][0] == "آيفون"


# =====================================================================
#  TEST 2: Synonym search 'سامسونج' matches samsung
# =====================================================================

class TestSearchSynonymSamsung:

    @pytest.mark.asyncio
    async def test_search_synonym_samsung(self):
        """Search for 'سامسونج' returns Samsung listings (synonym mapping)."""
        hits = [
            _make_meili_hit(
                title_ar="سامسونج جالكسي S24",
                title_en="Samsung Galaxy S24",
                category_id=1,
            ),
        ]
        mock_result = _make_meili_result(hits, total=1)

        mock_index = MagicMock()
        mock_index.search.return_value = mock_result

        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import search_listings

            request = SearchRequest(q="سامسونج")
            response = await search_listings(request)

        assert response.total == 1
        assert "سامسونج" in response.hits[0].title_ar
        # Query passed to Meilisearch as-is (synonym resolution is server-side)
        mock_index.search.assert_called_once()
        assert mock_index.search.call_args[0][0] == "سامسونج"


# =====================================================================
#  TEST 3: Autocomplete returns in < 50ms
# =====================================================================

class TestAutocompleteSpeed:

    @pytest.mark.asyncio
    async def test_autocomplete_under_50ms(self, fake_redis):
        """Suggest endpoint returns within 50ms (with mock Meilisearch)."""
        hits = [
            {"title_ar": "آيفون 15", "title_en": "iPhone 15", "category_id": 1},
        ]
        mock_result = {"hits": hits, "processingTimeMs": 3}

        mock_index = MagicMock()
        mock_index.search.return_value = mock_result

        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import suggest_listings

            start = time.monotonic()
            response = await suggest_listings("iphone", limit=5, redis=fake_redis)
            elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 50
        assert len(response.hits) == 1
        assert response.hits[0].title_en == "iPhone 15"
        assert response.hits[0].category_id == 1

        # Verify result was cached in Redis
        import hashlib
        q_hash = hashlib.md5("iphone".encode()).hexdigest()
        cached = await fake_redis.get(f"suggest:{q_hash}")
        assert cached is not None

        # Second call should hit cache (no Meilisearch call)
        mock_index.search.reset_mock()
        response2 = await suggest_listings("iphone", limit=5, redis=fake_redis)
        assert len(response2.hits) == 1
        mock_index.search.assert_not_called()


# =====================================================================
#  TEST 4: Price range filter
# =====================================================================

class TestFilterPriceRange:

    @pytest.mark.asyncio
    async def test_filter_price_range(self):
        """Price range filter builds correct Meilisearch filter string."""
        hits = [_make_meili_hit(current_price=30000)]
        mock_result = _make_meili_result(hits, total=1)

        mock_index = MagicMock()
        mock_index.search.return_value = mock_result

        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import search_listings

            request = SearchRequest(
                q="phone",
                filters=SearchFilters(min_price=20000, max_price=50000),
            )
            response = await search_listings(request)

        assert response.total == 1
        # Check the filter string passed to Meilisearch
        call_params = mock_index.search.call_args[0][1]
        filter_str = call_params["filter"]
        assert "current_price >= 20000" in filter_str
        assert "current_price <= 50000" in filter_str


# =====================================================================
#  TEST 5: Certified-only filter
# =====================================================================

class TestFilterCertifiedOnly:

    @pytest.mark.asyncio
    async def test_filter_certified_only(self):
        """is_certified=True filter is passed to Meilisearch."""
        hits = [_make_meili_hit(is_certified=True)]
        mock_result = _make_meili_result(hits, total=1)

        mock_index = MagicMock()
        mock_index.search.return_value = mock_result

        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import search_listings

            request = SearchRequest(
                q="watch",
                filters=SearchFilters(is_certified=True),
            )
            response = await search_listings(request)

        assert response.total == 1
        call_params = mock_index.search.call_args[0][1]
        filter_str = call_params["filter"]
        assert "is_certified = true" in filter_str


# =====================================================================
#  TEST 6: Fallback to PostgreSQL when Meilisearch is down
# =====================================================================

class _FakeSessionFactory:
    """Context manager that yields a pre-existing session."""

    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        pass


class TestFallbackToPostgres:

    @pytest.mark.asyncio
    async def test_fallback_to_postgres_when_meilisearch_down(self, search_db):
        """When Meilisearch is unavailable, search falls back to ILIKE with degraded_mode=True."""
        # Insert test listings
        await _create_listing(search_db, title_ar="آيفون 15 برو", title_en="iPhone 15 Pro")
        await _create_listing(search_db, title_ar="سامسونج S24", title_en="Samsung S24")

        # Make Meilisearch raise an exception
        mock_client = MagicMock()
        mock_client.index.return_value.search.side_effect = Exception("Connection refused")

        fake_factory = _FakeSessionFactory(search_db)

        # Patch Meilisearch client and session factory for fallback
        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.core.database.async_session_factory", fake_factory), \
             patch("app.services.search.service._log_search"):
            from app.services.search.service import search_listings

            request = SearchRequest(q="آيفون")
            response = await search_listings(request)

        assert response.degraded_mode is True
        assert response.total >= 1
        assert any("آيفون" in h.title_ar for h in response.hits)


# =====================================================================
#  TEST 7: Search logged to ClickHouse
# =====================================================================

class TestSearchLoggedToClickhouse:

    @pytest.mark.asyncio
    async def test_search_logged_to_clickhouse(self):
        """Search result is logged to ClickHouse with correct columns."""
        hits = [_make_meili_hit()]
        mock_result = _make_meili_result(hits, total=1)

        mock_index = MagicMock()
        mock_index.search.return_value = mock_result

        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        mock_ch_client = MagicMock()

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.core.clickhouse.get_clickhouse_client", return_value=mock_ch_client):
            from app.services.search.service import search_listings

            request = SearchRequest(
                q="laptop",
                filters=SearchFilters(category_ids=[5]),
            )
            response = await search_listings(request, user_id="user-123")

        assert response.total == 1
        # Verify ClickHouse insert was called
        mock_ch_client.insert.assert_called_once()
        call_args = mock_ch_client.insert.call_args

        assert call_args[0][0] == "search_logs"  # table name
        row = call_args[0][1][0]  # first (only) row
        columns = call_args[1]["column_names"]

        assert columns == [
            "user_id", "query", "results_count", "filters",
            "response_ms", "created_at",
        ]
        assert row[0] == "user-123"       # user_id
        assert row[1] == "laptop"         # query
        assert row[2] == 1               # results_count
        assert "category_ids" in row[3]  # filters JSON
        assert isinstance(row[4], int)    # response_ms
        assert row[5]                     # created_at not empty
