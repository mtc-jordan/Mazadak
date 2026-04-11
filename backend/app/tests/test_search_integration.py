"""
Tests for Meilisearch search integration — FR-SRCH-001 → FR-SRCH-012.

Covers:
  - Index configuration (configure_meilisearch with Arabic settings)
  - Full-text search with faceted filtering
  - Autocomplete suggestions (<50ms target)
  - Filter building (category_ids, conditions, price range, location, certified, charity)
  - Sort mapping (price_asc/desc, newest, ends_asc, bids_desc)
  - PostgreSQL ILIKE fallback when Meilisearch unavailable
  - ClickHouse search logging (fire-and-forget)
  - SearchableListingDocument model
  - Schema validation
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
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

    # Patch JSONB columns for SQLite compat
    mod_flags_col = Listing.__table__.c.moderation_flags
    orig_type = mod_flags_col.type
    mod_flags_col.type = Text()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    mod_flags_col.type = orig_type

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session, factory

    await engine.dispose()


async def _create_listing(db: AsyncSession, **overrides) -> str:
    """Insert a minimal Listing row, returning the ID."""
    from app.services.listing.models import Listing

    now = datetime.now(timezone.utc)
    lid = str(uuid4())
    defaults = dict(
        id=lid,
        seller_id=str(uuid4()),
        title_en="Test Listing",
        title_ar="عنوان تجريبي",
        description_ar="وصف",
        category_id=1,
        condition="good",
        starting_price=500,
        min_increment=25,
        location_country="JO",
        status="draft",
        starts_at=now,
        ends_at=now + timedelta(hours=24),
        moderation_flags=[],
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
            from app.services.search.service import configure_meilisearch
            configure_meilisearch()

        mock_index.update_searchable_attributes.assert_called_once()
        args = mock_index.update_searchable_attributes.call_args[0][0]
        assert "title_ar" in args
        assert "title_en" in args
        assert "description_ar" in args
        assert "brand" in args

    def test_setup_index_configures_filterable_attributes(self):
        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import configure_meilisearch
            configure_meilisearch()

        mock_index.update_filterable_attributes.assert_called_once()
        filterable = mock_index.update_filterable_attributes.call_args[0][0]
        for attr in ["category_id", "condition", "status", "location_city",
                      "is_certified", "is_charity", "starting_price"]:
            assert attr in filterable, f"{attr} not in filterable"

    def test_setup_index_configures_sortable_attributes(self):
        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import configure_meilisearch
            configure_meilisearch()

        mock_index.update_sortable_attributes.assert_called_once()
        sortable = mock_index.update_sortable_attributes.call_args[0][0]
        for attr in ["starting_price", "current_price", "bid_count",
                      "ends_at_timestamp", "created_at_timestamp"]:
            assert attr in sortable, f"{attr} not in sortable"

    def test_setup_index_includes_arabic_stop_words(self):
        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import configure_meilisearch
            configure_meilisearch()

        mock_index.update_stop_words.assert_called_once()
        stop_words = mock_index.update_stop_words.call_args[0][0]
        assert "في" in stop_words
        assert "من" in stop_words
        assert "على" in stop_words

    def test_setup_index_includes_synonyms(self):
        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            from app.services.search.service import configure_meilisearch
            configure_meilisearch()

        mock_index.update_synonyms.assert_called_once()
        synonyms = mock_index.update_synonyms.call_args[0][0]
        assert "آيفون" in synonyms["iphone"]
        assert "ايفون" in synonyms["iphone"]
        assert "سامسونج" in synonyms["samsung"]


# ═══════════════════════════════════════════════════════════════════
#  Test: Filter and sort building
# ═══════════════════════════════════════════════════════════════════

class TestFilterBuilding:
    def test_builds_category_filter(self):
        from app.services.search.schemas import SearchRequest, SearchFilters
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", filters=SearchFilters(category_ids=[5]))
        filters = _build_filters(req)
        assert "category_id IN [5]" in filters

    def test_builds_condition_filter(self):
        from app.services.search.schemas import SearchRequest, SearchFilters
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", filters=SearchFilters(conditions=["new"]))
        filters = _build_filters(req)
        assert 'condition IN ["new"]' in filters

    def test_builds_country_filter(self):
        from app.services.search.schemas import SearchRequest, SearchFilters
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", filters=SearchFilters(location_country="JO"))
        filters = _build_filters(req)
        assert 'location_country = "JO"' in filters

    def test_builds_certified_filter(self):
        from app.services.search.schemas import SearchRequest, SearchFilters
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", filters=SearchFilters(is_certified=True))
        filters = _build_filters(req)
        assert "is_certified = true" in filters

    def test_builds_price_range_filter(self):
        from app.services.search.schemas import SearchRequest, SearchFilters
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", filters=SearchFilters(min_price=100, max_price=500))
        filters = _build_filters(req)
        assert any("current_price >= 100" in f for f in filters)
        assert any("current_price <= 500" in f for f in filters)

    def test_builds_status_filter(self):
        from app.services.search.schemas import SearchRequest, SearchFilters
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", filters=SearchFilters(status=["active"]))
        filters = _build_filters(req)
        assert 'status IN ["active"]' in filters

    def test_empty_filters_when_no_params(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test")
        filters = _build_filters(req)
        assert filters == []

    def test_combined_filters(self):
        from app.services.search.schemas import SearchRequest, SearchFilters
        from app.services.search.service import _build_filters

        req = SearchRequest(q="test", filters=SearchFilters(
            category_ids=[3], location_country="JO", min_price=50,
        ))
        filters = _build_filters(req)
        assert len(filters) == 3


class TestSortBuilding:
    def test_price_asc(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_sort

        req = SearchRequest(q="test", sort="price_asc")
        assert _build_sort(req) == ["current_price:asc"]

    def test_price_desc(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_sort

        req = SearchRequest(q="test", sort="price_desc")
        assert _build_sort(req) == ["current_price:desc"]

    def test_newest(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_sort

        req = SearchRequest(q="test", sort="newest")
        assert _build_sort(req) == ["created_at_timestamp:desc"]

    def test_ending_soon(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_sort

        req = SearchRequest(q="test", sort="ends_asc")
        assert _build_sort(req) == ["ends_at_timestamp:asc"]

    def test_most_bids(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _build_sort

        req = SearchRequest(q="test", sort="bids_desc")
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
                    "starting_price": 35000,
                    "current_price": 40000,
                    "image_url": "img/phone.webp",
                    "is_charity": False,
                    "is_certified": True,
                    "location_city": "Amman",
                    "location_country": "JO",
                    "bid_count": 10,
                    "ends_at_timestamp": 1744300800,
                },
            ],
            "estimatedTotalHits": 1,
            "processingTimeMs": 3,
            "facetDistribution": {
                "category_id": {"1": 5, "2": 3},
                "condition": {"new": 4, "like_new": 2},
            },
        }

        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"):
            req = SearchRequest(q="ايفون")
            resp = await search_listings(req)

        assert resp.total == 1
        assert resp.hits[0].title_ar == "ايفون 15"
        assert resp.hits[0].is_certified is True
        assert resp.hits[0].location_city == "Amman"
        assert resp.hits[0].bid_count == 10
        assert resp.facets is not None
        assert "category_id" in resp.facets

    @pytest.mark.asyncio
    async def test_search_passes_filters_to_meilisearch(self):
        from app.services.search.schemas import SearchRequest, SearchFilters
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
            req = SearchRequest(
                q="phone",
                filters=SearchFilters(category_ids=[1], min_price=100),
            )
            await search_listings(req)

        search_call = mock_index.search.call_args
        params = search_call[0][1]
        filter_str = params["filter"]
        assert "category_id IN [1]" in filter_str
        assert "current_price >= 100" in filter_str

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
        params = search_call[0][1]
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

        assert resp.total == 100
        assert resp.page == 3
        assert resp.per_page == 10
        # Check offset was passed correctly: (3-1) * 10 = 20
        search_call = mock_index.search.call_args
        params = search_call[0][1]
        assert params["offset"] == 20


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
                {"title_ar": "ايفون 15", "title_en": "iPhone 15", "category_id": 1},
                {"title_ar": "ايفون 14", "title_en": "iPhone 14", "category_id": 1},
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

        await _create_listing(db, title_ar="ايفون 15 برو", title_en="iPhone 15 Pro", description_ar="هاتف ايفون", status="active")
        await _create_listing(db, title_ar="سامسونج جالاكسي", title_en="Samsung Galaxy", description_ar="هاتف سامسونج", status="active")
        await db.commit()

        from app.services.search.schemas import SearchRequest
        from app.services.search.service import search_listings

        mock_client = MagicMock()
        mock_client.index.return_value.search.side_effect = Exception("Meilisearch down")

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"), \
             patch("app.core.database.async_session_factory", return_value=factory()):
            resp = await search_listings(SearchRequest(q="ايفون"))

        assert resp.total == 1
        assert resp.hits[0].title_ar == "ايفون 15 برو"
        assert resp.facets is None  # no facets in fallback

    @pytest.mark.asyncio
    async def test_fallback_applies_category_filter(self, search_db):
        db, factory = search_db

        await _create_listing(db, title_ar="ايفون", category_id=1, status="active")
        await _create_listing(db, title_ar="ايفون كفر", category_id=2, status="active")
        await db.commit()

        from app.services.search.schemas import SearchRequest, SearchFilters
        from app.services.search.service import search_listings

        mock_client = MagicMock()
        mock_client.index.return_value.search.side_effect = Exception("down")

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"), \
             patch("app.core.database.async_session_factory", return_value=factory()):
            resp = await search_listings(SearchRequest(
                q="ايفون",
                filters=SearchFilters(category_ids=[1]),
            ))

        assert resp.total == 1

    @pytest.mark.asyncio
    async def test_fallback_applies_price_range(self, search_db):
        db, factory = search_db

        await _create_listing(db, title_ar="ايفون رخيص", starting_price=100, status="active")
        await _create_listing(db, title_ar="ايفون غالي", starting_price=800, status="active")
        await db.commit()

        from app.services.search.schemas import SearchRequest, SearchFilters
        from app.services.search.service import search_listings

        mock_client = MagicMock()
        mock_client.index.return_value.search.side_effect = Exception("down")

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"), \
             patch("app.core.database.async_session_factory", return_value=factory()):
            resp = await search_listings(SearchRequest(
                q="ايفون",
                filters=SearchFilters(max_price=500),
            ))

        assert resp.total == 1
        assert resp.hits[0].starting_price == 100

    @pytest.mark.asyncio
    async def test_fallback_certified_filter(self, search_db):
        db, factory = search_db

        await _create_listing(db, title_ar="ايفون موثق", is_certified=True, status="active")
        await _create_listing(db, title_ar="ايفون عادي", is_certified=False, status="active")
        await db.commit()

        from app.services.search.schemas import SearchRequest, SearchFilters
        from app.services.search.service import search_listings

        mock_client = MagicMock()
        mock_client.index.return_value.search.side_effect = Exception("down")

        with patch("app.services.search.service._get_client", return_value=mock_client), \
             patch("app.services.search.service._log_search"), \
             patch("app.core.database.async_session_factory", return_value=factory()):
            resp = await search_listings(SearchRequest(
                q="ايفون",
                filters=SearchFilters(is_certified=True),
            ))

        assert resp.total == 1
        assert resp.hits[0].is_certified is True

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

        assert resp.total == 1


# ═══════════════════════════════════════════════════════════════════
#  Test: ClickHouse search logging
# ═══════════════════════════════════════════════════════════════════

class TestClickHouseLogging:
    def test_log_search_calls_clickhouse_insert(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _log_search

        mock_ch_client = MagicMock()

        with patch("app.core.clickhouse.get_clickhouse_client", return_value=mock_ch_client):
            _log_search(SearchRequest(q="ايفون"), results_count=5, response_ms=12, user_id="user-123")

        mock_ch_client.insert.assert_called_once()
        args = mock_ch_client.insert.call_args
        assert args[0][0] == "search_logs"

    def test_log_search_handles_no_clickhouse(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _log_search

        with patch("app.core.clickhouse.get_clickhouse_client", return_value=None):
            # Should not raise
            _log_search(SearchRequest(q="test"), results_count=0, response_ms=1)

    def test_log_search_handles_clickhouse_error(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import _log_search

        mock_ch_client = MagicMock()
        mock_ch_client.insert.side_effect = Exception("ClickHouse down")

        with patch("app.core.clickhouse.get_clickhouse_client", return_value=mock_ch_client):
            # Should not raise — fire-and-forget
            _log_search(SearchRequest(q="test"), results_count=0, response_ms=1)


# ═══════════════════════════════════════════════════════════════════
#  Test: Constants and facet config
# ═══════════════════════════════════════════════════════════════════

class TestConstantsAndConfig:
    def test_facet_fields_defined(self):
        from app.services.search.service import FACET_FIELDS

        assert "category_id" in FACET_FIELDS
        assert "condition" in FACET_FIELDS
        assert "location_city" in FACET_FIELDS
        assert "is_certified" in FACET_FIELDS
        assert "is_charity" in FACET_FIELDS


# ═══════════════════════════════════════════════════════════════════
#  Test: SearchableListingDocument model
# ═══════════════════════════════════════════════════════════════════

class TestSearchableDocument:
    def test_document_includes_fields(self):
        from app.services.search.models import SearchableListingDocument

        doc = SearchableListingDocument(
            id="abc",
            title_ar="تست",
            description_ar="وصف",
            category_id=1,
            condition="new",
            starting_price=10000,
            status="active",
            seller_id="seller-1",
            is_charity=False,
            image_url="img/test.webp",
            brand="Apple",
            location_city="Amman",
            location_country="JO",
            is_certified=True,
            bid_count=10,
            ends_at_timestamp=1744300800,
            created_at_timestamp=1744200000,
        )
        data = doc.model_dump()
        assert data["brand"] == "Apple"
        assert data["location_city"] == "Amman"
        assert data["is_certified"] is True
        assert data["bid_count"] == 10
        assert data["ends_at_timestamp"] == 1744300800

    def test_document_defaults(self):
        from app.services.search.models import SearchableListingDocument

        doc = SearchableListingDocument(
            id="abc",
            title_ar="تست",
            description_ar="وصف",
            category_id=1,
            condition="new",
            starting_price=10000,
            status="active",
            seller_id="seller-1",
            is_charity=False,
        )
        assert doc.brand is None
        assert doc.location_city is None
        assert doc.is_certified is False
        assert doc.bid_count == 0
        assert doc.ends_at_timestamp is None
        assert doc.location_country == "JO"


# ═══════════════════════════════════════════════════════════════════
#  Test: Schema validation
# ═══════════════════════════════════════════════════════════════════

class TestSchemas:
    def test_search_request_with_nested_filters(self):
        from app.services.search.schemas import SearchRequest, SearchFilters

        req = SearchRequest(
            q="test",
            filters=SearchFilters(
                category_ids=[1, 2],
                conditions=["new"],
                is_certified=True,
                location_country="JO",
            ),
        )
        assert req.filters.category_ids == [1, 2]
        assert req.filters.is_certified is True
        assert req.filters.location_country == "JO"

    def test_search_hit_fields(self):
        from app.services.search.schemas import SearchHit

        hit = SearchHit(
            id="1", title_ar="تست", category_id=1, condition="new",
            starting_price=100, image_url="",
            is_charity=False, is_certified=True,
            location_city="Amman", location_country="JO",
            bid_count=5, ends_at="2026-04-10",
        )
        assert hit.is_certified is True
        assert hit.ends_at == "2026-04-10"
        assert hit.location_city == "Amman"

    def test_search_response_includes_facets(self):
        from app.services.search.schemas import SearchResponse

        resp = SearchResponse(
            hits=[], total=0, page=1,
            per_page=20, query_time_ms=1,
            facets={"category_id": {"1": 5}},
        )
        assert resp.facets == {"category_id": {"1": 5}}

    def test_suggest_response_schema(self):
        from app.services.search.schemas import SuggestResponse, SuggestHit

        resp = SuggestResponse(
            hits=[SuggestHit(title_ar="تست", category_id=1)],
            query="test",
            processing_time_ms=2,
        )
        assert len(resp.hits) == 1

    def test_sort_options(self):
        from app.services.search.schemas import SearchRequest

        for sort in ["price_asc", "price_desc", "newest", "ends_asc", "bids_desc"]:
            req = SearchRequest(q="test", sort=sort)
            assert req.sort == sort


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
            category_id=1, condition="new", starting_price=10000,
            status="active", seller_id="s1",
            is_charity=False, image_url="img/test.webp",
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
        from app.services.search.service import suggest_listings

        mock_index = MagicMock()
        mock_index.search.return_value = {
            "hits": [
                {"title_ar": "ايفون 15", "title_en": "iPhone 15", "category_id": 1},
            ],
            "processingTimeMs": 8,
        }
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("app.services.search.service._get_client", return_value=mock_client):
            resp = await suggest_listings("ايفون")

        assert resp.processing_time_ms < 50

    @pytest.mark.asyncio
    async def test_search_arabic_query_processing_time(self):
        from app.services.search.schemas import SearchRequest
        from app.services.search.service import search_listings

        mock_index = MagicMock()
        mock_index.search.return_value = {
            "hits": [
                {
                    "id": "1", "title_ar": "ساعة رولكس أصلية",
                    "category_id": 5, "condition": "like_new",
                    "starting_price": 500000,
                    "image_url": "img/rolex.webp", "is_charity": False,
                    "is_certified": True,
                    "location_city": "Amman", "location_country": "JO",
                    "bid_count": 25,
                    "ends_at_timestamp": 1744387200,
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

        assert resp.query_time_ms < 100  # includes Python overhead
        assert resp.hits[0].is_certified is True
