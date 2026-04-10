"""
Search service tests — 7 tests covering Arabic search, synonyms,
autocomplete, filters, PG fallback, and ClickHouse logging.
"""

from __future__ import annotations

import json
import sys
import time
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# ── Mock Celery (not installed in test env) ──────────────────
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

from app.services.search.schemas import (
    SearchFilters,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SuggestHit,
    SuggestResponse,
)
from app.services.search.service import (
    _build_filters,
    _build_sort,
    _sanitize_filter_value,
    suggest_listings,
)


# ═══════════════════════════════════════════════════════════════
# Helper: Mock Meilisearch search result
# ═══════════════════════════════════════════════════════════════

def _meili_result(hits, total=None, processing_ms=5):
    """Build a mock Meilisearch search() return value."""
    return {
        "hits": hits,
        "estimatedTotalHits": total or len(hits),
        "processingTimeMs": processing_ms,
        "facetDistribution": {"category_id": {"1": 3, "2": 1}},
    }


def _hit(title_ar="آيفون 15 برو", title_en="iPhone 15 Pro", **kw):
    """Build a single Meilisearch hit dict."""
    return {
        "id": kw.get("id", "aaaa-bbbb-cccc"),
        "title_ar": title_ar,
        "title_en": title_en,
        "category_id": kw.get("category_id", 1),
        "condition": kw.get("condition", "like_new"),
        "starting_price": kw.get("starting_price", 50000),
        "current_price": kw.get("current_price", 55000),
        "image_url": kw.get("image_url", ""),
        "is_charity": kw.get("is_charity", False),
        "is_certified": kw.get("is_certified", False),
        "location_city": kw.get("location_city", "Amman"),
        "location_country": kw.get("location_country", "JO"),
        "bid_count": kw.get("bid_count", 3),
        "ends_at_timestamp": kw.get("ends_at_timestamp", 1735689600),
    }


# ═══════════════════════════════════════════════════════════════
# 1. Arabic iPhone search returns results
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_search_arabic_iphone_returns_results():
    """Searching 'آيفون' returns iPhone listings via Meilisearch."""
    mock_index = MagicMock()
    mock_index.search.return_value = _meili_result([
        _hit(title_ar="آيفون 15 برو ماكس", title_en="iPhone 15 Pro Max"),
        _hit(title_ar="آيفون 14", title_en="iPhone 14"),
    ], total=2)

    mock_client = MagicMock()
    mock_client.index.return_value = mock_index

    with patch("app.services.search.service._get_client", return_value=mock_client):
        from app.services.search.service import search_listings

        request = SearchRequest(q="آيفون")
        result = await search_listings(request)

    assert result.total == 2
    assert len(result.hits) == 2
    assert "آيفون" in result.hits[0].title_ar
    assert result.degraded_mode is False

    # Verify Meilisearch was called with the Arabic query
    mock_index.search.assert_called_once()
    call_args = mock_index.search.call_args
    assert call_args[0][0] == "آيفون"


# ═══════════════════════════════════════════════════════════════
# 2. Synonym: سامسونج matches samsung
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_search_synonym_samsung():
    """'سامسونج' query is sent to Meilisearch which handles synonyms."""
    mock_index = MagicMock()
    mock_index.search.return_value = _meili_result([
        _hit(title_ar="سامسونج جالكسي S24", title_en="Samsung Galaxy S24"),
    ], total=1)

    mock_client = MagicMock()
    mock_client.index.return_value = mock_index

    with patch("app.services.search.service._get_client", return_value=mock_client):
        from app.services.search.service import search_listings

        request = SearchRequest(q="سامسونج")
        result = await search_listings(request)

    assert result.total == 1
    assert "سامسونج" in result.hits[0].title_ar or "Samsung" in (result.hits[0].title_en or "")

    # Verify the Arabic query was passed through to Meilisearch
    mock_index.search.assert_called_once()
    assert mock_index.search.call_args[0][0] == "سامسونج"


# ═══════════════════════════════════════════════════════════════
# 3. Autocomplete under 50ms (with mock Meilisearch)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_autocomplete_under_50ms(fake_redis):
    """Suggest endpoint returns results quickly with mock Meilisearch."""
    mock_index = MagicMock()
    mock_index.search.return_value = {
        "hits": [
            {"title_ar": "آيفون 15", "title_en": "iPhone 15", "category_id": 1},
            {"title_ar": "آيفون 14", "title_en": "iPhone 14", "category_id": 1},
        ],
        "processingTimeMs": 3,
    }

    mock_client = MagicMock()
    mock_client.index.return_value = mock_index

    with patch("app.services.search.service._get_client", return_value=mock_client):
        start = time.monotonic()
        result = await suggest_listings("آيفون", limit=5, redis=fake_redis)
        elapsed_ms = (time.monotonic() - start) * 1000

    assert elapsed_ms < 50
    assert len(result.hits) == 2
    assert result.hits[0].title_ar == "آيفون 15"
    assert result.query == "آيفون"

    # Verify Meilisearch was called with correct params
    mock_index.search.assert_called_once()
    call_args = mock_index.search.call_args
    # search(q, params_dict) — params is positional arg [1]
    params = call_args[0][1]
    assert params["limit"] == 5
    assert "title_ar" in params["attributesToRetrieve"]


# ═══════════════════════════════════════════════════════════════
# 4. Filter: price range
# ═══════════════════════════════════════════════════════════════

def test_filter_price_range():
    """min_price and max_price build correct Meilisearch filter."""
    request = SearchRequest(
        q="test",
        filters=SearchFilters(min_price=100, max_price=500),
    )
    filters = _build_filters(request)

    assert "current_price >= 100" in filters
    assert "current_price <= 500" in filters


# ═══════════════════════════════════════════════════════════════
# 5. Filter: certified only
# ═══════════════════════════════════════════════════════════════

def test_filter_certified_only():
    """is_certified=True builds correct Meilisearch filter."""
    request = SearchRequest(
        q="rolex",
        filters=SearchFilters(is_certified=True),
    )
    filters = _build_filters(request)

    assert "is_certified = true" in filters

    # Also test with is_charity
    request2 = SearchRequest(
        q="test",
        filters=SearchFilters(is_charity=True, is_certified=False),
    )
    filters2 = _build_filters(request2)

    assert "is_charity = true" in filters2
    assert "is_certified = false" in filters2


# ═══════════════════════════════════════════════════════════════
# 6. Fallback to PostgreSQL when Meilisearch is down
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_fallback_to_postgres_when_meilisearch_down():
    """When Meilisearch fails, search falls back to PG ILIKE with degraded_mode=True."""
    # Mock Meilisearch to throw an error
    mock_client = MagicMock()
    mock_client.index.return_value.search.side_effect = Exception("Meilisearch down")

    # Create a fake fallback response (what _search_fallback would return)
    fallback_response = SearchResponse(
        hits=[
            SearchHit(
                id="test-id",
                title_ar="ساعة رولكس ذهبية",
                title_en="Gold Rolex Watch",
                category_id=1,
                condition="like_new",
                starting_price=100000,
                current_price=100000,
            ),
        ],
        total=1,
        page=1,
        per_page=20,
        facets=None,
        degraded_mode=True,
    )

    from unittest.mock import AsyncMock

    with (
        patch("app.services.search.service._get_client", return_value=mock_client),
        patch("app.services.search.service._search_fallback", new_callable=AsyncMock, return_value=fallback_response),
        patch("app.services.search.service._log_search"),
    ):
        from app.services.search.service import search_listings

        request = SearchRequest(q="رولكس")
        result = await search_listings(request)

    # Verify Meilisearch was attempted first
    mock_client.index.return_value.search.assert_called_once()

    # Verify fallback was used
    assert result.degraded_mode is True
    assert result.total == 1
    assert "رولكس" in result.hits[0].title_ar


# ═══════════════════════════════════════════════════════════════
# 7. Search logged to ClickHouse
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_search_logged_to_clickhouse():
    """Search calls _log_search which inserts into ClickHouse."""
    mock_index = MagicMock()
    mock_index.search.return_value = _meili_result([_hit()], total=1)

    mock_client = MagicMock()
    mock_client.index.return_value = mock_index

    mock_ch_client = MagicMock()

    with (
        patch("app.services.search.service._get_client", return_value=mock_client),
        patch("app.core.clickhouse.get_clickhouse_client", return_value=mock_ch_client),
    ):
        from app.services.search.service import search_listings

        request = SearchRequest(q="test query", page=1, per_page=10)
        await search_listings(request, user_id="user-123")

    # Verify ClickHouse insert was called
    mock_ch_client.insert.assert_called_once()
    call_args = mock_ch_client.insert.call_args

    assert call_args[0][0] == "search_logs"  # table name
    row = call_args[0][1][0]  # first (and only) row
    assert row[0] == "user-123"      # user_id
    assert row[1] == "test query"    # query
    assert row[2] == 1               # results_count
