"""
Tests for Meilisearch search integration — FR-SRCH-001 → FR-SRCH-012.

Covers:
  - Index configuration (setup_index with Arabic settings)
  - Full-text search with faceted filtering
  - Autocomplete suggestions (<50ms target)
  - Filter building (category, condition, city, price range, is_authenticated)
  - Sort mapping (price_asc/desc, newest, ending_soon, most_bids)
  - PostgreSQL ILIKE fallback when Meilisearch unavailable
  - ClickHouse search logging (fire-and-forget)
  - CDC sync document building (new fields: brand, city, is_authenticated, bid_count, ends_at)
  - Template rendering and synonyms
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch, call
from uuid import uuid4

import pytest
from sqlalchemy import Text, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Mock Celery before any app import ────────────────────────────
_mock_celery_app = MagicMock()
_mock_celery_app.task = lambda *a, **kw: (lambda fn: fn)

_mock_modules = {
    "app.core.celery": MagicMock(celery_app=_mock_celery_app),
}


# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

def _register_sqlite_functions(dbapi_conn, connection_record):
    import uuid as _uuid
    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(_uuid.uuid4()))
    dbapi_conn.create_function("now", 0, lambda: "2026-04-07T00:00:00")


@pytest.fixture
async def search_db():
    """Async SQLite session with listing table for fallback tests."""
    from app.core.database import Base
    from app.services.listing.models import Listing

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)

    # Patch ARRAY/JSONB columns for SQLite compat
    image_col = Listing.__table__.c.image_urls
    orig_type = image_col.type
    image_col.type = Text()

    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[Listing.__table__],
            )
    finally:
        image_col.type = orig_type

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session, factory
    await engine.dispose()


async def _create_listing(db: AsyncSession, **overrides) -> str:
    from app.services.listing.models import Listing

    lid = overrides.pop("id", str(uuid4()))
    defaults = dict(
        id=lid,
        seller_id=str(uuid4()),
        title_ar="ايفون 15 برو ماكس",
        title_en="iPhone 15 Pro Max",
        description_ar="ايفون جديد بحالة ممتازة",
        description_en="New iPhone in excellent condition",
        category_id=1,
        condition="new",
        starting_price=350.0,
        listing_currency="JOD",
        status="active",
        is_charity=False,
        image_urls=json.dumps(["img/phone1.webp"]),
        bid_count=5,
        brand="Apple",
        city="Amman",
        authentication_cert_id=str(uuid4()),
    )
    defaults.update(overrides)
    db.add(Listing(**defaults))
    await db.flush()
    return lid


# ═══════════════════════════════════════════════════════════════════
#  Test: Index configuration
# ═══════════════════════════════════════════════════════════════════

class TestSetupIndex:
    def test_setup_index_configures_searchable_attributes(self):
        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import setup_index
            setup_index()

        call_args = mock_index.update_settings.call_args[0][0]
        assert "title_ar" in call_args["searchableAttributes"]
        assert "title_en" in call_args["searchableAttributes"]
        assert "description_ar" in call_args["searchableAttributes"]
        assert "brand" in call_args["searchableAttributes"]

    def test_setup_index_configures_filterable_attributes(self):
        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import setup_index
            setup_index()

        call_args = mock_index.update_settings.call_args[0][0]
        filterable = call_args["filterableAttributes"]
        for attr in ["category_id", "condition", "city", "is_authenticated", "status", "starting_price"]:
            assert attr in filterable, f"{attr} not in filterable"

    def test_setup_index_configures_sortable_attributes(self):
        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import setup_index
            setup_index()

        call_args = mock_index.update_settings.call_args[0][0]
        sortable = call_args["sortableAttributes"]
        for attr in ["starting_price", "bid_count", "ends_at"]:
            assert attr in sortable, f"{attr} not in sortable"

    def test_setup_index_includes_arabic_stop_words(self):
        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import setup_index
            setup_index()

        call_args = mock_index.update_settings.call_args[0][0]
        stop_words = call_args["stopWords"]
        assert "في" in stop_words
        assert "من" in stop_words
        assert "على" in stop_words

    def test_setup_index_includes_synonyms(self):
        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import setup_index
            setup_index()

        call_args = mock_index.update_settings.call_args[0][0]
        synonyms = call_args["synonyms"]
        assert "آيفون" in synonyms["iPhone"]
        assert "ايفون" in synonyms["iPhone"]
        assert "سامسونج" in synonyms["Samsung"]


# ═══════════════════════════════════════════════════════════════════
#  Test: Filter and sort building
# ═══════════════════════════════════════════════════════════════════

class TestFilterBuilding:
    def test_builds_category_filter(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", category_id=5)
        filters = _build_filters(req)
        assert "category_id = 5" in filters

    def test_builds_condition_filter(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", condition="new")
        filters = _build_filters(req)
        assert 'condition = "new"' in filters

    def test_builds_city_filter(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", city="Amman")
        filters = _build_filters(req)
        assert 'city = "Amman"' in filters

    def test_builds_is_authenticated_filter(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", is_authenticated=True)
        filters = _build_filters(req)
        assert "is_authenticated = true" in filters

    def test_builds_price_range_filter(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", price_min=100, price_max=500)
        filters = _build_filters(req)
        assert any("starting_price >= 100" in f for f in filters)
        assert any("starting_price <= 500" in f for f in filters)

    def test_builds_status_filter(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", status="active")
        filters = _build_filters(req)
        assert 'status = "active"' in filters

    def test_empty_filters_when_no_params(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test")
        filters = _build_filters(req)
        assert filters == []

    def test_combined_filters(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", category_id=3, city="Amman", price_min=50)
        filters = _build_filters(req)
        assert len(filters) == 3


class TestSortBuilding:
    def test_price_asc(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_sort

        req = SearchRequest(q="test", sort_by="price_asc")
        assert _build_sort(req) == ["starting_price:asc"]

    def test_price_desc(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_sort

        req = SearchRequest(q="test", sort_by="price_desc")
        assert _build_sort(req) == ["starting_price:desc"]

    def test_newest(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_sort

        req = SearchRequest(q="test", sort_by="newest")
        assert _build_sort(req) == ["created_at:desc"]

    def test_ending_soon(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_sort

        req = SearchRequest(q="test", sort_by="ending_soon")
        assert _build_sort(req) == ["ends_at:asc"]

    def test_most_bids(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_sort

        req = SearchRequest(q="test", sort_by="most_bids")
        assert _build_sort(req) == ["bid_count:desc"]

    def test_relevance_default(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_sort

        req = SearchRequest(q="test")
        assert _build_sort(req) == []


# ═══════════════════════════════════════════════════════════════════
#  Test: Meilisearch search proxy
# ═══════════════════════════════════════════════════════════════════

class TestMeilisearchSearch:
    @pytest.mark.asyncio
    async def test_search_returns_hits_with_facets(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import search_listings

        mock_index = MagicMock()
        mock_index.search.return_value = {
            "hits": [
                {
                    "id": "abc-123",
                    "title_ar": "ايفون 15",
                    "title_en": "iPhone 15",
                    "category_id": 1,
                    "condition": "new",
                    "starting_price": 350.0,
                    "listing_currency": "JOD",
                    "image_url": "img/phone.webp",
                    "is_charity": False,
                    "brand": "Apple",
                    "city": "Amman",
                    "is_authenticated": True,
                    "bid_count": 10,
                    "ends_at": "2026-04-10T18:00:00",
                },
            ],
            "estimatedTotalHits": 1,
            "processingTimeMs": 3,
            "facetDistribution": {
                "category_id": {"1": 5, "2": 3},
                "condition": {"new": 4, "like_new": 2},
                "city": {"Amman": 6, "Irbid": 2},
                "is_authenticated": {"true": 3, "false": 5},
            },
        }

        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"):
            req = SearchRequest(q="ايفون")
            resp = await search_listings(req)

        assert resp.total_hits == 1
        assert resp.hits[0].title_ar == "ايفون 15"
        assert resp.hits[0].brand == "Apple"
        assert resp.hits[0].city == "Amman"
        assert resp.hits[0].is_authenticated is True
        assert resp.hits[0].bid_count == 10
        assert resp.facets is not None
        assert "category_id" in resp.facets

    @pytest.mark.asyncio
    async def test_search_passes_filters_to_meilisearch(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import search_listings

        mock_index = MagicMock()
        mock_index.search.return_value = {
            "hits": [],
            "estimatedTotalHits": 0,
            "processingTimeMs": 1,
        }
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"):
            req = SearchRequest(q="phone", category_id=1, city="Amman", price_min=100)
            await search_listings(req)

        search_call = mock_index.search.call_args
        filter_str = search_call[1]["filter"] if "filter" in search_call[1] else search_call[0][1]["filter"]
        assert "category_id = 1" in filter_str
        assert 'city = "Amman"' in filter_str
        assert "starting_price >= 100" in filter_str

    @pytest.mark.asyncio
    async def test_search_requests_facets(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import search_listings

        mock_index = MagicMock()
        mock_index.search.return_value = {
            "hits": [],
            "estimatedTotalHits": 0,
            "processingTimeMs": 1,
        }
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"):
            await search_listings(SearchRequest(q="test"))

        search_call = mock_index.search.call_args
        params = search_call[0][1] if len(search_call[0]) > 1 else search_call[1]
        assert "facets" in params
        assert "category_id" in params["facets"]

    @pytest.mark.asyncio
    async def test_pagination(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import search_listings

        mock_index = MagicMock()
        mock_index.search.return_value = {
            "hits": [],
            "estimatedTotalHits": 100,
            "processingTimeMs": 2,
        }
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"):
            resp = await search_listings(SearchRequest(q="test", page=3, per_page=10))

        assert resp.total_pages == 10
        assert resp.page == 3
        # Check offset was passed correctly
        search_call = mock_index.search.call_args
        params = search_call[0][1] if len(search_call[0]) > 1 else search_call[1]
        assert params["offset"] == 20  # (3-1) * 10


# ═══════════════════════════════════════════════════════════════════
#  Test: Autocomplete suggest
# ═══════════════════════════════════════════════════════════════════

class TestSuggest:
    @pytest.mark.asyncio
    async def test_suggest_returns_titles(self):
        from app.services.search.service import suggest_listings

        mock_index = MagicMock()
        mock_index.search.return_value = {
            "hits": [
                {"id": "1", "title_ar": "ايفون 15", "title_en": "iPhone 15", "image_url": "img/1.webp"},
                {"id": "2", "title_ar": "ايفون 14", "title_en": "iPhone 14", "image_url": "img/2.webp"},
            ],
            "processingTimeMs": 2,
        }
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            resp = await suggest_listings("ايفون", limit=5)

        assert len(resp.hits) == 2
        assert resp.hits[0].title_ar == "ايفون 15"
        assert resp.processing_time_ms == 2

    @pytest.mark.asyncio
    async def test_suggest_limits_attributes_retrieved(self):
        from app.services.search.service import suggest_listings

        mock_index = MagicMock()
        mock_index.search.return_value = {"hits": [], "processingTimeMs": 1}
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            await suggest_listings("test", limit=3)

        search_call = mock_index.search.call_args
        params = search_call[0][1] if len(search_call[0]) > 1 else search_call[1]
        assert params["limit"] == 3
        assert "attributesToRetrieve" in params
        assert "id" in params["attributesToRetrieve"]
        assert "title_ar" in params["attributesToRetrieve"]

    @pytest.mark.asyncio
    async def test_suggest_gracefully_handles_meilisearch_failure(self):
        from app.services.search.service import suggest_listings

        mock_client = MagicMock()
        mock_client.index.side_effect = Exception("connection refused")

        with patch("app.services.search.service._get_client", return_value=mock_client):
            resp = await suggest_listings("test")

        assert resp.hits == []
        assert resp.processing_time_ms == 0


# ═══════════════════════════════════════════════════════════════════
#  Test: PostgreSQL ILIKE fallback
# ═══════════════════════════════════════════════════════════════════

class TestILikeFallback:
    @pytest.mark.asyncio
    async def test_fallback_on_meilisearch_failure(self, search_db):
        db, factory = search_db

        lid = await _create_listing(db, title_ar="ايفون 15 برو", title_en=None, description_ar="هاتف ايفون", status="active")
        await _create_listing(db, title_ar="سامسونج جالاكسي", title_en=None, description_ar="هاتف سامسونج", status="active")
        await db.commit()

        from app.services.search.schemas import SearchRequest
        from app.services.search.service import search_listings

        mock_client = MagicMock()
        mock_client.index.return_value.search.side_effect = Exception("Meilisearch down")

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"), \
             patch("app.core.database.async_session_factory", return_value=factory()):
            resp = await search_listings(SearchRequest(q="ايفون"))

        assert resp.total_hits == 1
        assert resp.hits[0].title_ar == "ايفون 15 برو"
        assert resp.facets is None  # no facets in fallback

    @pytest.mark.asyncio
    async def test_fallback_applies_category_filter(self, search_db):
        db, factory = search_db

        await _create_listing(db, title_ar="ايفون", category_id=1, status="active")
        await _create_listing(db, title_ar="ايفون كفر", category_id=2, status="active")
        await db.commit()

        from app.services.search.schemas import SearchRequest
        from app.services.search.service import search_listings

        mock_client = MagicMock()
        mock_client.index.return_value.search.side_effect = Exception("down")

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"), \
             patch("app.core.database.async_session_factory", return_value=factory()):
            resp = await search_listings(SearchRequest(q="ايفون", category_id=1))

        assert resp.total_hits == 1

    @pytest.mark.asyncio
    async def test_fallback_applies_city_filter(self, search_db):
        db, factory = search_db

        await _create_listing(db, title_ar="ايفون", city="Amman", status="active")
        await _create_listing(db, title_ar="ايفون", city="Irbid", status="active")
        await db.commit()

        from app.services.search.schemas import SearchRequest
        from app.services.search.service import search_listings

        mock_client = MagicMock()
        mock_client.index.return_value.search.side_effect = Exception("down")

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"), \
             patch("app.core.database.async_session_factory", return_value=factory()):
            resp = await search_listings(SearchRequest(q="ايفون", city="Amman"))

        assert resp.total_hits == 1
        assert resp.hits[0].city == "Amman"

    @pytest.mark.asyncio
    async def test_fallback_applies_price_range(self, search_db):
        db, factory = search_db

        await _create_listing(db, title_ar="ايفون رخيص", starting_price=100, status="active")
        await _create_listing(db, title_ar="ايفون غالي", starting_price=800, status="active")
        await db.commit()

        from app.services.search.schemas import SearchRequest
        from app.services.search.service import search_listings

        mock_client = MagicMock()
        mock_client.index.return_value.search.side_effect = Exception("down")

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"), \
             patch("app.core.database.async_session_factory", return_value=factory()):
            resp = await search_listings(SearchRequest(q="ايفون", price_max=500))

        assert resp.total_hits == 1
        assert resp.hits[0].starting_price == 100.0

    @pytest.mark.asyncio
    async def test_fallback_is_authenticated_filter(self, search_db):
        db, factory = search_db

        await _create_listing(
            db, title_ar="ايفون موثق", authentication_cert_id=str(uuid4()), status="active",
        )
        await _create_listing(
            db, title_ar="ايفون عادي", authentication_cert_id=None, status="active",
        )
        await db.commit()

        from app.services.search.schemas import SearchRequest
        from app.services.search.service import search_listings

        mock_client = MagicMock()
        mock_client.index.return_value.search.side_effect = Exception("down")

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"), \
             patch("app.core.database.async_session_factory", return_value=factory()):
            resp = await search_listings(SearchRequest(q="ايفون", is_authenticated=True))

        assert resp.total_hits == 1
        assert resp.hits[0].is_authenticated is True

    @pytest.mark.asyncio
    async def test_fallback_only_returns_active_listings(self, search_db):
        db, factory = search_db

        await _create_listing(db, title_ar="ايفون نشط", status="active")
        await _create_listing(db, title_ar="ايفون مسودة", status="draft")
        await _create_listing(db, title_ar="ايفون ملغي", status="cancelled")
        await db.commit()

        from app.services.search.schemas import SearchRequest
        from app.services.search.service import search_listings

        mock_client = MagicMock()
        mock_client.index.return_value.search.side_effect = Exception("down")

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"), \
             patch("app.core.database.async_session_factory", return_value=factory()):
            resp = await search_listings(SearchRequest(q="ايفون"))

        assert resp.total_hits == 1


# ═══════════════════════════════════════════════════════════════════
#  Test: ClickHouse search logging
# ═══════════════════════════════════════════════════════════════════

class TestClickHouseLogging:
    def test_log_search_calls_clickhouse_insert(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _log_search

        mock_ch_client = MagicMock()

        with patch("app.core.clickhouse.get_clickhouse_client", return_value=mock_ch_client):
            _log_search(SearchRequest(q="ايفون", category_id=1, city="Amman"), user_id="user-123")

        mock_ch_client.insert.assert_called_once()
        args = mock_ch_client.insert.call_args
        assert args[0][0] == "search_logs"
        row = args[0][1][0]
        assert row[0] == "ايفون"
        assert row[1] == "user-123"

    def test_log_search_handles_no_clickhouse(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _log_search

        with patch("app.core.clickhouse.get_clickhouse_client", return_value=None):
            # Should not raise
            _log_search(SearchRequest(q="test"))

    def test_log_search_handles_clickhouse_error(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _log_search

        mock_ch_client = MagicMock()
        mock_ch_client.insert.side_effect = Exception("ClickHouse down")

        with patch("app.core.clickhouse.get_clickhouse_client", return_value=mock_ch_client):
            # Should not raise — fire-and-forget
            _log_search(SearchRequest(q="test"))


# ═══════════════════════════════════════════════════════════════════
#  Test: Templates and synonyms
# ═══════════════════════════════════════════════════════════════════

class TestTemplatesAndSynonyms:
    def test_synonyms_contain_arabic_iphone_variants(self):
        from app.services.search.service import SYNONYMS

        assert "آيفون" in SYNONYMS["iPhone"]
        assert "ايفون" in SYNONYMS["iPhone"]

    def test_synonyms_contain_samsung(self):
        from app.services.search.service import SYNONYMS

        assert "سامسونج" in SYNONYMS["Samsung"]

    def test_arabic_stop_words_present(self):
        from app.services.search.service import ARABIC_STOP_WORDS

        assert "في" in ARABIC_STOP_WORDS
        assert "من" in ARABIC_STOP_WORDS
        assert "the" in ARABIC_STOP_WORDS

    def test_facet_fields_defined(self):
        from app.services.search.service import FACET_FIELDS

        assert "category_id" in FACET_FIELDS
        assert "condition" in FACET_FIELDS
        assert "city" in FACET_FIELDS
        assert "is_authenticated" in FACET_FIELDS


# ═══════════════════════════════════════════════════════════════════
#  Test: SearchableListingDocument model
# ═══════════════════════════════════════════════════════════════════

class TestSearchableDocument:
    def test_document_includes_new_fields(self):
        from app.services.search.models import SearchableListingDocument

        doc = SearchableListingDocument(
            id="abc",
            title_ar="تست",
            description_ar="وصف",
            category_id=1,
            condition="new",
            starting_price=100.0,
            listing_currency="JOD",
            status="active",
            seller_id="seller-1",
            is_charity=False,
            image_url="img/test.webp",
            created_at="2026-04-07",
            brand="Apple",
            city="Amman",
            is_authenticated=True,
            bid_count=10,
            ends_at="2026-04-10T18:00:00",
        )
        data = doc.model_dump()
        assert data["brand"] == "Apple"
        assert data["city"] == "Amman"
        assert data["is_authenticated"] is True
        assert data["bid_count"] == 10
        assert data["ends_at"] == "2026-04-10T18:00:00"

    def test_document_defaults(self):
        from app.services.search.models import SearchableListingDocument

        doc = SearchableListingDocument(
            id="abc",
            title_ar="تست",
            description_ar="وصف",
            category_id=1,
            condition="new",
            starting_price=100.0,
            listing_currency="JOD",
            status="active",
            seller_id="seller-1",
            is_charity=False,
            image_url="img/test.webp",
            created_at="2026-04-07",
        )
        assert doc.brand is None
        assert doc.city is None
        assert doc.is_authenticated is False
        assert doc.bid_count == 0
        assert doc.ends_at is None


# ═══════════════════════════════════════════════════════════════════
#  Test: Schema validation
# ═══════════════════════════════════════════════════════════════════

class TestSchemas:
    def test_search_request_new_filters(self):
        from app.services.search.schemas import SearchRequest

        req = SearchRequest(
            q="test",
            city="Amman",
            is_authenticated=True,
            status="active",
        )
        assert req.city == "Amman"
        assert req.is_authenticated is True
        assert req.status == "active"

    def test_search_hit_new_fields(self):
        from app.services.search.schemas import SearchHit

        hit = SearchHit(
            id="1", title_ar="تست", category_id=1, condition="new",
            starting_price=100, listing_currency="JOD", image_url="",
            is_charity=False, brand="Apple", city="Amman",
            is_authenticated=True, bid_count=5, ends_at="2026-04-10",
        )
        assert hit.brand == "Apple"
        assert hit.ends_at == "2026-04-10"

    def test_search_response_includes_facets(self):
        from app.services.search.schemas import SearchResponse

        resp = SearchResponse(
            hits=[], query="test", total_hits=0, page=1,
            total_pages=0, processing_time_ms=1,
            facets={"category_id": {"1": 5}},
        )
        assert resp.facets == {"category_id": {"1": 5}}

    def test_suggest_response_schema(self):
        from app.services.search.schemas import SuggestResponse, SuggestHit

        resp = SuggestResponse(
            hits=[SuggestHit(id="1", title_ar="تست")],
            query="test",
            processing_time_ms=2,
        )
        assert len(resp.hits) == 1

    def test_sort_by_options(self):
        from app.services.search.schemas import SearchRequest

        for sort in ["price_asc", "price_desc", "newest", "ending_soon", "most_bids"]:
            req = SearchRequest(q="test", sort_by=sort)
            assert req.sort_by == sort


# ═══════════════════════════════════════════════════════════════════
#  Test: Index and remove operations
# ═══════════════════════════════════════════════════════════════════

class TestIndexOperations:
    @pytest.mark.asyncio
    async def test_index_listing_calls_add_documents(self):
        from app.services.search.models import SearchableListingDocument
        from app.services.search.service import index_listing

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        doc = SearchableListingDocument(
            id="abc", title_ar="تست", description_ar="وصف",
            category_id=1, condition="new", starting_price=100.0,
            listing_currency="JOD", status="active", seller_id="s1",
            is_charity=False, image_url="img/test.webp", created_at="2026-04-07",
        )

        with patch("app.services.search.service._get_client", return_value=mock_client):
            await index_listing(doc)

        mock_index.add_documents.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_listing_calls_delete_document(self):
        from app.services.search.service import remove_listing

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            await remove_listing("abc-123")

        mock_index.delete_document.assert_called_once_with("abc-123")


# ═══════════════════════════════════════════════════════════════════
#  Test: Performance (mocked — validates <50ms contract)
# ═══════════════════════════════════════════════════════════════════

class TestPerformance:
    @pytest.mark.asyncio
    async def test_suggest_processing_time_under_50ms(self):
        """Verify Meilisearch reports <50ms for suggest queries."""
        from app.services.search.service import suggest_listings

        mock_index = MagicMock()
        mock_index.search.return_value = {
            "hits": [
                {"id": "1", "title_ar": "ايفون 15", "title_en": "iPhone 15", "image_url": "img/1.webp"},
            ],
            "processingTimeMs": 8,  # Simulating fast response
        }
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            resp = await suggest_listings("ايفون")

        assert resp.processing_time_ms < 50

    @pytest.mark.asyncio
    async def test_search_arabic_query_processing_time(self):
        """Verify Meilisearch reports acceptable time for Arabic queries."""
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import search_listings

        mock_index = MagicMock()
        mock_index.search.return_value = {
            "hits": [
                {
                    "id": "1", "title_ar": "ساعة رولكس أصلية",
                    "category_id": 5, "condition": "like_new",
                    "starting_price": 5000.0, "listing_currency": "JOD",
                    "image_url": "img/rolex.webp", "is_charity": False,
                    "brand": "Rolex", "city": "Amman",
                    "is_authenticated": True, "bid_count": 25,
                    "ends_at": "2026-04-12T20:00:00",
                },
            ],
            "estimatedTotalHits": 1,
            "processingTimeMs": 12,
        }
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"):
            resp = await search_listings(SearchRequest(q="رولكس"))

        assert resp.processing_time_ms < 50
        assert resp.hits[0].brand == "Rolex"
        assert resp.hits[0].is_authenticated is True
