"""
Search service — Meilisearch integration (FR-SRCH-001 → FR-SRCH-012).

Full-text search across listings with Arabic + English support,
faceted filtering, relevance ranking, autocomplete suggestions,
and PostgreSQL ILIKE fallback when Meilisearch is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

import meilisearch

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

# ── Arabic stop words (common words that add no search value) ────
ARABIC_STOP_WORDS = [
    "في", "من", "على", "إلى", "عن", "مع", "هذا", "هذه", "ذلك",
    "التي", "الذي", "هو", "هي", "كان", "كانت", "يكون", "أن",
    "لا", "ما", "لم", "لن", "قد", "كل", "بعد", "قبل", "بين",
    "حتى", "إذا", "ثم", "أو", "و", "أي", "غير", "بعض", "عند",
    "ال", "the", "a", "an", "is", "are", "was", "were", "in",
    "on", "at", "to", "for", "of", "with", "by",
]

# ── Arabic/English synonyms for common product terms ─────────────
SYNONYMS = {
    "iPhone": ["آيفون", "ايفون"],
    "Samsung": ["سامسونج", "سامسونغ"],
    "PlayStation": ["بلايستيشن", "بلاي ستيشن"],
    "MacBook": ["ماك بوك", "ماكبوك"],
    "iPad": ["آيباد", "ايباد"],
    "AirPods": ["ايربودز", "اير بودز"],
    "Toyota": ["تويوتا"],
    "Mercedes": ["مرسيدس"],
    "BMW": ["بي ام دبليو"],
    "Rolex": ["رولكس"],
    "جديد": ["new"],
    "مستعمل": ["used"],
}

# Facet fields returned with every search
FACET_FIELDS = ["category_id", "condition", "city", "is_authenticated"]


def _get_client() -> meilisearch.Client:
    return meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_API_KEY)


# ═══════════════════════════════════════════════════════════════════
#  Index configuration — run once on deploy
# ═══════════════════════════════════════════════════════════════════

def setup_index() -> None:
    """Configure Meilisearch index with Arabic language settings."""
    client = _get_client()
    index = client.index(INDEX_NAME)

    index.update_settings({
        "searchableAttributes": [
            "title_ar",
            "title_en",
            "description_ar",
            "brand",
        ],
        "filterableAttributes": [
            "category_id",
            "condition",
            "city",
            "is_authenticated",
            "status",
            "starting_price",
            "listing_currency",
            "is_charity",
        ],
        "sortableAttributes": [
            "starting_price",
            "bid_count",
            "ends_at",
            "created_at",
        ],
        "stopWords": ARABIC_STOP_WORDS,
        "synonyms": SYNONYMS,
        "pagination": {"maxTotalHits": 10000},
        "typoTolerance": {
            "enabled": True,
            "minWordSizeForTypos": {"oneTypo": 4, "twoTypos": 8},
        },
    })
    logger.info("Meilisearch index '%s' configured", INDEX_NAME)


# ═══════════════════════════════════════════════════════════════════
#  Full-text search with facets
# ═══════════════════════════════════════════════════════════════════

async def search_listings(
    request: SearchRequest,
    user_id: str | None = None,
) -> SearchResponse:
    """Execute search with Meilisearch. Falls back to PostgreSQL ILIKE on failure."""
    try:
        return await _search_meilisearch(request)
    except Exception as exc:
        logger.warning("Meilisearch unavailable, falling back to ILIKE: %s", exc)
        return await _search_fallback(request)
    finally:
        _log_search(request, user_id)


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
            listing_currency=h["listing_currency"],
            image_url=h.get("image_url", ""),
            is_charity=h.get("is_charity", False),
            brand=h.get("brand"),
            city=h.get("city"),
            is_authenticated=h.get("is_authenticated", False),
            bid_count=h.get("bid_count", 0),
            ends_at=h.get("ends_at"),
        )
        for h in result["hits"]
    ]

    total = result.get("estimatedTotalHits", 0)
    facets = result.get("facetDistribution")

    return SearchResponse(
        hits=hits,
        query=request.q,
        total_hits=total,
        page=request.page,
        total_pages=(total + request.per_page - 1) // request.per_page if total else 0,
        processing_time_ms=result.get("processingTimeMs", 0),
        facets=facets,
    )


def _build_filters(request: SearchRequest) -> list[str]:
    """Build Meilisearch filter expressions from request."""
    filters: list[str] = []
    if request.category_id is not None:
        filters.append(f"category_id = {request.category_id}")
    if request.condition:
        filters.append(f'condition = "{request.condition}"')
    if request.city:
        filters.append(f'city = "{request.city}"')
    if request.is_authenticated is not None:
        filters.append(f"is_authenticated = {str(request.is_authenticated).lower()}")
    if request.status:
        filters.append(f'status = "{request.status}"')
    if request.price_min is not None:
        filters.append(f"starting_price >= {request.price_min}")
    if request.price_max is not None:
        filters.append(f"starting_price <= {request.price_max}")
    if request.currency:
        filters.append(f'listing_currency = "{request.currency}"')
    return filters


def _build_sort(request: SearchRequest) -> list[str]:
    """Map sort_by parameter to Meilisearch sort expressions."""
    mapping = {
        "price_asc": ["starting_price:asc"],
        "price_desc": ["starting_price:desc"],
        "newest": ["created_at:desc"],
        "ending_soon": ["ends_at:asc"],
        "most_bids": ["bid_count:desc"],
    }
    return mapping.get(request.sort_by or "", [])


# ═══════════════════════════════════════════════════════════════════
#  Autocomplete suggest
# ═══════════════════════════════════════════════════════════════════

async def suggest_listings(q: str, limit: int = 5) -> SuggestResponse:
    """Fast autocomplete — return title matches only, <50ms target."""
    try:
        client = _get_client()
        index = client.index(INDEX_NAME)

        result = index.search(q, {
            "limit": limit,
            "attributesToRetrieve": ["id", "title_ar", "title_en", "image_url"],
            "attributesToHighlight": ["title_ar", "title_en"],
        })

        hits = [
            SuggestHit(
                id=h["id"],
                title_ar=h["title_ar"],
                title_en=h.get("title_en"),
                image_url=h.get("image_url", ""),
            )
            for h in result["hits"]
        ]

        return SuggestResponse(
            hits=hits,
            query=q,
            processing_time_ms=result.get("processingTimeMs", 0),
        )
    except Exception as exc:
        logger.warning("Meilisearch suggest failed: %s", exc)
        return SuggestResponse(hits=[], query=q, processing_time_ms=0)


# ═══════════════════════════════════════════════════════════════════
#  PostgreSQL ILIKE fallback (degraded mode)
# ═══════════════════════════════════════════════════════════════════

async def _search_fallback(request: SearchRequest) -> SearchResponse:
    """Degraded search using PostgreSQL ILIKE when Meilisearch is down."""
    from sqlalchemy import select, func, or_
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.database import async_session_factory
    from app.services.listing.models import Listing

    async with async_session_factory() as db:
        query = select(Listing).where(Listing.status == "active")

        # Text search via ILIKE
        pattern = f"%{request.q}%"
        query = query.where(
            or_(
                Listing.title_ar.ilike(pattern),
                Listing.title_en.ilike(pattern),
                Listing.description_ar.ilike(pattern),
            )
        )

        # Apply filters
        if request.category_id is not None:
            query = query.where(Listing.category_id == request.category_id)
        if request.condition:
            query = query.where(Listing.condition == request.condition)
        if request.city:
            query = query.where(Listing.city == request.city)
        if request.is_authenticated is not None:
            if request.is_authenticated:
                query = query.where(Listing.authentication_cert_id.isnot(None))
            else:
                query = query.where(Listing.authentication_cert_id.is_(None))
        if request.price_min is not None:
            query = query.where(Listing.starting_price >= request.price_min)
        if request.price_max is not None:
            query = query.where(Listing.starting_price <= request.price_max)
        if request.currency:
            query = query.where(Listing.listing_currency == request.currency)

        # Sort
        if request.sort_by == "price_asc":
            query = query.order_by(Listing.starting_price.asc())
        elif request.sort_by == "price_desc":
            query = query.order_by(Listing.starting_price.desc())
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

        import json as _json

        hits = [
            SearchHit(
                id=str(lst.id),
                title_ar=lst.title_ar,
                title_en=lst.title_en,
                category_id=lst.category_id,
                condition=lst.condition,
                starting_price=float(lst.starting_price),
                listing_currency=lst.listing_currency,
                image_url=(
                    _json.loads(lst.image_urls)[0]
                    if lst.image_urls and lst.image_urls.startswith("[")
                    else ""
                ),
                is_charity=lst.is_charity,
                brand=lst.brand,
                city=lst.city,
                is_authenticated=lst.authentication_cert_id is not None,
                bid_count=lst.bid_count,
            )
            for lst in listings
        ]

        return SearchResponse(
            hits=hits,
            query=request.q,
            total_hits=total,
            page=request.page,
            total_pages=(total + request.per_page - 1) // request.per_page if total else 0,
            processing_time_ms=0,
            facets=None,
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

def _log_search(request: SearchRequest, user_id: str | None = None) -> None:
    """Log search query to ClickHouse for analytics (fire-and-forget)."""
    try:
        from app.core.clickhouse import get_clickhouse_client

        client = get_clickhouse_client()
        if client is None:
            return

        client.insert(
            "search_logs",
            [[
                request.q,
                user_id or "",
                request.category_id or 0,
                request.condition or "",
                request.city or "",
                request.price_min or 0.0,
                request.price_max or 0.0,
                request.sort_by or "relevance",
                request.page,
            ]],
            column_names=[
                "query", "user_id", "category_id", "condition",
                "city", "price_min", "price_max", "sort_by", "page",
            ],
        )
    except Exception:
        logger.debug("ClickHouse search log failed (non-critical)")
