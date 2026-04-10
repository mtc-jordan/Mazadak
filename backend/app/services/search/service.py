"""
Search service — Meilisearch integration (FR-SRCH-001 → FR-SRCH-012).

Full-text search across listings with Arabic + English support,
faceted filtering, relevance ranking, autocomplete suggestions,
and PostgreSQL ILIKE fallback when Meilisearch is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import meilisearch
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.search.models import SearchableListingDocument
from app.services.search.schemas import (
    SearchHit,
    SearchRequest,
    SearchResponse,
    SuggestHit,
    SuggestResponse,
)

logger = logging.getLogger(__name__)

INDEX_NAME = "listings"

# Facet fields returned with every search
FACET_FIELDS = [
    "category_id", "condition", "location_city",
    "is_certified", "is_charity",
]


def _get_client() -> meilisearch.Client:
    return meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_API_KEY)


# ═══════════════════════════════════════════════════════════════════
#  Index configuration — run once on deploy / startup
# ═══════════════════════════════════════════════════════════════════

def configure_meilisearch() -> None:
    """Configure Meilisearch index with Arabic language settings."""
    client = _get_client()
    index = client.index(INDEX_NAME)

    # Searchable attributes (order = weight)
    index.update_searchable_attributes([
        "title_ar", "title_en", "description_ar", "description_en", "brand",
    ])

    # Filterable
    index.update_filterable_attributes([
        "category_id", "condition", "status", "location_city", "location_country",
        "is_certified", "is_charity", "seller_id", "starting_price", "current_price",
        "ends_at_timestamp",
    ])

    # Sortable
    index.update_sortable_attributes([
        "starting_price", "current_price", "bid_count",
        "ends_at_timestamp", "created_at_timestamp",
    ])

    # Arabic stop words
    index.update_stop_words([
        "في", "من", "على", "إلى", "عن", "مع", "هذا", "هذه", "ال",
    ])

    # Arabic-English synonyms
    index.update_synonyms({
        "iphone": ["آيفون", "ايفون", "iPhone"],
        "samsung": ["سامسونج", "سامسنج"],
        "mercedes": ["مرسيدس", "بنز", "مرسيدس بنز"],
        "toyota": ["تويوتا", "تيوتا"],
        "rolex": ["رولكس", "رولكز"],
        "laptop": ["لابتوب", "حاسوب محمول", "كمبيوتر محمول"],
    })

    # Typo tolerance settings
    index.update_typo_tolerance({
        "enabled": True,
        "minWordSizeForTypos": {"oneTypo": 4, "twoTypos": 8},
    })

    logger.info("Meilisearch index '%s' configured", INDEX_NAME)


# ═══════════════════════════════════════════════════════════════════
#  Sync function — called by Celery on listing change
# ═══════════════════════════════════════════════════════════════════

async def sync_listing_to_meilisearch(
    listing_id: str,
    db: AsyncSession,
) -> None:
    """Sync a single listing to Meilisearch index.

    Removes from index if status is not active/ended.
    """
    from app.services.auth.models import User
    from app.services.listing.models import Listing

    listing = await db.get(Listing, str(listing_id))
    if not listing:
        logger.warning("Listing %s not found for search sync", listing_id)
        return

    client = _get_client()
    index = client.index(INDEX_NAME)

    if listing.status not in ("active", "ended"):
        index.delete_document(str(listing_id))
        return

    # Load seller for ATS score
    user = await db.get(User, listing.seller_id)
    seller_ats = user.ats_score if user else 0

    document = {
        "id": str(listing.id),
        "title_en": listing.title_en,
        "title_ar": listing.title_ar,
        "description_en": listing.description_en or "",
        "description_ar": listing.description_ar or "",
        "category_id": listing.category_id,
        "condition": listing.condition.value if hasattr(listing.condition, "value") else listing.condition,
        "status": listing.status.value if hasattr(listing.status, "value") else listing.status,
        "location_city": listing.location_city,
        "location_country": listing.location_country,
        "is_certified": listing.is_certified,
        "is_charity": listing.is_charity,
        "seller_id": str(listing.seller_id),
        "seller_ats": seller_ats,
        "starting_price": listing.starting_price,
        "current_price": listing.current_price or listing.starting_price,
        "bid_count": listing.bid_count,
        "ends_at_timestamp": int(listing.ends_at.timestamp()) if listing.ends_at else None,
        "created_at_timestamp": int(listing.created_at.timestamp()) if listing.created_at else None,
        "image_url": listing.images[0].s3_key_thumb_400 if listing.images else None,
    }

    index.add_documents([document])


# ═══════════════════════════════════════════════════════════════════
#  Full-text search with facets
# ═══════════════════════════════════════════════════════════════════

async def search_listings(
    request: SearchRequest,
    user_id: str | None = None,
) -> SearchResponse:
    """Execute search with Meilisearch. Falls back to PostgreSQL ILIKE on failure."""
    start = time.monotonic()
    try:
        result = await _search_meilisearch(request)
    except Exception as exc:
        logger.warning("Meilisearch unavailable, falling back to ILIKE: %s", exc)
        result = await _search_fallback(request)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    result.query_time_ms = elapsed_ms
    _log_search(request, result.total, elapsed_ms, user_id)
    return result


async def _search_meilisearch(request: SearchRequest) -> SearchResponse:
    """Proxy search to Meilisearch with facets."""
    client = _get_client()
    index = client.index(INDEX_NAME)

    filters = _build_filters(request)
    sort = _build_sort(request)

    params: dict[str, Any] = {
        "filter": " AND ".join(filters) if filters else None,
        "sort": sort or None,
        "offset": (request.page - 1) * request.per_page,
        "limit": request.per_page,
        "facets": FACET_FIELDS,
    }

    result = index.search(request.q, params)

    hits = [
        SearchHit(
            id=h["id"],
            title_ar=h["title_ar"],
            title_en=h.get("title_en"),
            category_id=h["category_id"],
            condition=h["condition"],
            starting_price=h["starting_price"],
            current_price=h.get("current_price"),
            image_url=h.get("image_url", ""),
            is_charity=h.get("is_charity", False),
            is_certified=h.get("is_certified", False),
            location_city=h.get("location_city"),
            location_country=h.get("location_country", "JO"),
            bid_count=h.get("bid_count", 0),
            ends_at=str(h["ends_at_timestamp"]) if h.get("ends_at_timestamp") else None,
        )
        for h in result["hits"]
    ]

    total = result.get("estimatedTotalHits", 0)
    facets = result.get("facetDistribution")

    return SearchResponse(
        hits=hits,
        total=total,
        page=request.page,
        per_page=request.per_page,
        facets=facets,
        query_time_ms=result.get("processingTimeMs", 0),
    )


def _sanitize_filter_value(val: str) -> str:
    """Strip Meilisearch special characters from filter values."""
    return val.replace('"', "").replace("\\", "").replace("'", "")


def _build_filters(request: SearchRequest) -> list[str]:
    """Build Meilisearch filter expressions from request."""
    filters: list[str] = []
    f = request.filters
    if f is None:
        return filters

    if f.category_ids:
        ids = ", ".join(str(int(c)) for c in f.category_ids)
        filters.append(f"category_id IN [{ids}]")
    if f.conditions:
        vals = ", ".join(f'"{_sanitize_filter_value(c)}"' for c in f.conditions)
        filters.append(f"condition IN [{vals}]")
    if f.status:
        vals = ", ".join(f'"{_sanitize_filter_value(s)}"' for s in f.status)
        filters.append(f"status IN [{vals}]")
    if f.location_country:
        filters.append(f'location_country = "{_sanitize_filter_value(f.location_country)}"')
    if f.is_certified is not None:
        filters.append(f"is_certified = {str(f.is_certified).lower()}")
    if f.is_charity is not None:
        filters.append(f"is_charity = {str(f.is_charity).lower()}")
    if f.min_price is not None:
        filters.append(f"current_price >= {int(f.min_price)}")
    if f.max_price is not None:
        filters.append(f"current_price <= {int(f.max_price)}")
    if f.ends_before is not None:
        filters.append(f"ends_at_timestamp <= {int(f.ends_before.timestamp())}")
    if f.ends_after is not None:
        filters.append(f"ends_at_timestamp >= {int(f.ends_after.timestamp())}")

    return filters


def _build_sort(request: SearchRequest) -> list[str]:
    """Map sort parameter to Meilisearch sort expressions."""
    mapping = {
        "ends_asc": ["ends_at_timestamp:asc"],
        "price_asc": ["current_price:asc"],
        "price_desc": ["current_price:desc"],
        "bids_desc": ["bid_count:desc"],
        "newest": ["created_at_timestamp:desc"],
    }
    return mapping.get(request.sort or "", [])


# ═══════════════════════════════════════════════════════════════════
#  Autocomplete suggest with Redis cache
# ═══════════════════════════════════════════════════════════════════

SUGGEST_CACHE_TTL = 300  # 5 minutes

async def suggest_listings(
    q: str,
    limit: int = 5,
    redis=None,
) -> SuggestResponse:
    """Fast autocomplete — return title matches only, <50ms target.

    Checks Redis cache first (suggest:{q_hash}, 5 min TTL).
    """
    q_hash = hashlib.md5(q.lower().encode()).hexdigest()
    cache_key = f"suggest:{q_hash}"

    # Check Redis cache
    if redis is not None:
        try:
            cached = await redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                return SuggestResponse(
                    hits=[SuggestHit(**h) for h in data["hits"]],
                    query=q,
                    processing_time_ms=0,
                )
        except Exception:
            pass

    try:
        client = _get_client()
        index = client.index(INDEX_NAME)

        result = index.search(q, {
            "limit": limit,
            "attributesToRetrieve": ["title_en", "title_ar", "category_id"],
        })

        hits = [
            SuggestHit(
                title_ar=h["title_ar"],
                title_en=h.get("title_en"),
                category_id=h.get("category_id"),
            )
            for h in result["hits"]
        ]

        response = SuggestResponse(
            hits=hits,
            query=q,
            processing_time_ms=result.get("processingTimeMs", 0),
        )

        # Cache in Redis
        if redis is not None:
            try:
                cache_data = json.dumps({
                    "hits": [h.model_dump() for h in hits],
                })
                await redis.set(cache_key, cache_data, ex=SUGGEST_CACHE_TTL)
            except Exception:
                pass

        return response
    except Exception as exc:
        logger.warning("Meilisearch suggest failed: %s", exc)
        return SuggestResponse(hits=[], query=q, processing_time_ms=0)


# ═══════════════════════════════════════════════════════════════════
#  PostgreSQL ILIKE fallback (degraded mode)
# ═══════════════════════════════════════════════════════════════════

async def _search_fallback(request: SearchRequest) -> SearchResponse:
    """Degraded search using PostgreSQL ILIKE when Meilisearch is down."""
    from sqlalchemy import select, func, or_

    from app.core.database import async_session_factory
    from app.services.listing.models import Listing

    logger.info("search_degraded_mode=True query=%s", request.q)

    async with async_session_factory() as db:
        query = select(Listing).where(Listing.status == "active")

        # Text search via ILIKE
        pattern = f"%{request.q}%"
        query = query.where(
            or_(
                Listing.title_ar.ilike(pattern),
                Listing.title_en.ilike(pattern),
            )
        )

        # Apply filters
        f = request.filters
        if f:
            if f.category_ids:
                query = query.where(Listing.category_id.in_(f.category_ids))
            if f.conditions:
                query = query.where(Listing.condition.in_(f.conditions))
            if f.location_country:
                query = query.where(Listing.location_country == f.location_country)
            if f.is_certified is not None:
                query = query.where(Listing.is_certified == f.is_certified)
            if f.is_charity is not None:
                query = query.where(Listing.is_charity == f.is_charity)
            if f.min_price is not None:
                query = query.where(Listing.starting_price >= f.min_price)
            if f.max_price is not None:
                query = query.where(Listing.starting_price <= f.max_price)

        # Sort
        sort = request.sort
        if sort == "price_asc":
            query = query.order_by(Listing.starting_price.asc())
        elif sort == "price_desc":
            query = query.order_by(Listing.starting_price.desc())
        elif sort == "newest":
            query = query.order_by(Listing.created_at.desc())
        else:
            query = query.order_by(Listing.created_at.desc())

        # Count
        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        # Paginate
        offset = (request.page - 1) * request.per_page
        query = query.offset(offset).limit(request.per_page)

        result = await db.execute(query)
        listings = result.scalars().all()

        hits = [
            SearchHit(
                id=str(lst.id),
                title_ar=lst.title_ar,
                title_en=lst.title_en,
                category_id=lst.category_id,
                condition=lst.condition,
                starting_price=lst.starting_price,
                current_price=lst.current_price,
                image_url=(
                    lst.images[0].s3_key_thumb_400 or lst.images[0].s3_key
                    if lst.images else ""
                ),
                is_charity=lst.is_charity,
                is_certified=lst.is_certified,
                location_city=lst.location_city,
                location_country=lst.location_country,
                bid_count=lst.bid_count,
            )
            for lst in listings
        ]

        return SearchResponse(
            hits=hits,
            total=total,
            page=request.page,
            per_page=request.per_page,
            facets=None,
            degraded_mode=True,
        )


# ═══════════════════════════════════════════════════════════════════
#  Index operations
# ═══════════════════════════════════════════════════════════════════

async def index_listing(doc: SearchableListingDocument) -> None:
    """Add or update a listing in Meilisearch."""
    client = _get_client()
    index = client.index(INDEX_NAME)
    index.add_documents([doc.model_dump()])


async def remove_listing(listing_id: str) -> None:
    """Remove a listing from the search index."""
    client = _get_client()
    index = client.index(INDEX_NAME)
    index.delete_document(listing_id)


# ═══════════════════════════════════════════════════════════════════
#  ClickHouse search logging
# ═══════════════════════════════════════════════════════════════════

def _log_search(
    request: SearchRequest,
    results_count: int,
    response_ms: int,
    user_id: str | None = None,
) -> None:
    """Log search query to ClickHouse for analytics (fire-and-forget).

    INSERT INTO search_logs (user_id, query, results_count, filters, response_ms, created_at)
    """
    try:
        from datetime import datetime, timezone
        from app.core.clickhouse import get_clickhouse_client

        client = get_clickhouse_client()
        if client is None:
            return

        filters_json = json.dumps(
            request.filters.model_dump(exclude_none=True) if request.filters else {},
        )

        client.insert(
            "search_logs",
            [[
                user_id or "",
                request.q,
                results_count,
                filters_json,
                response_ms,
                datetime.now(timezone.utc).isoformat(),
            ]],
            column_names=[
                "user_id", "query", "results_count", "filters",
                "response_ms", "created_at",
            ],
        )
    except Exception:
        logger.debug("ClickHouse search log failed (non-critical)")
