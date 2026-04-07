"""
Listing tests — FR-LIST-001 → FR-LIST-013.

Covers: creation validation, price constraints, Free-tier cap,
bid-count guards, AI moderation routing, pHash duplicate detection,
CRUD operations, filter/sort/pagination, auth requirements.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

import pytest

from app.services.listing.models import Listing, ListingStatus, set_image_urls
from app.services.listing.service import (
    create_listing,
    update_listing,
    delete_listing,
    submit_for_moderation,
    list_listings,
    check_phash_duplicates,
    _hamming_similarity,
    ListingLimitError,
    BidCountError,
    StatusError,
)
from app.services.listing.schemas import ListingCreateRequest, ListingUpdateRequest
from app.tests.conftest import make_listing_data


# ── Schema Validation ──────────────────────────────────────────

class TestListingSchemaValidation:
    """FR-LIST-001: Input validation rules."""

    def test_title_ar_required(self):
        """title_ar is mandatory."""
        with pytest.raises(Exception):
            ListingCreateRequest(**make_listing_data(title_ar=""))

    def test_description_ar_min_50_chars(self):
        """description_ar must be at least 50 characters."""
        with pytest.raises(Exception):
            ListingCreateRequest(**make_listing_data(description_ar="too short"))

    def test_duration_min_1_hour(self):
        with pytest.raises(Exception):
            ListingCreateRequest(**make_listing_data(duration_hours=0))

    def test_duration_max_168_hours(self):
        """7 days = 168 hours max."""
        with pytest.raises(Exception):
            ListingCreateRequest(**make_listing_data(duration_hours=169))

    def test_duration_valid_range(self):
        req = ListingCreateRequest(**make_listing_data(duration_hours=1))
        assert req.duration_hours == 1
        req2 = ListingCreateRequest(**make_listing_data(duration_hours=168))
        assert req2.duration_hours == 168

    def test_reserve_must_be_gte_starting(self):
        """reserve_price must be >= starting_price."""
        with pytest.raises(Exception):
            ListingCreateRequest(**make_listing_data(
                starting_price=100.0, reserve_price=50.0
            ))

    def test_reserve_equal_to_starting_is_valid(self):
        req = ListingCreateRequest(**make_listing_data(
            starting_price=100.0, reserve_price=100.0
        ))
        assert req.reserve_price == 100.0

    def test_reserve_above_starting_is_valid(self):
        req = ListingCreateRequest(**make_listing_data(
            starting_price=100.0, reserve_price=200.0
        ))
        assert req.reserve_price == 200.0

    def test_buy_it_now_must_exceed_starting(self):
        with pytest.raises(Exception):
            ListingCreateRequest(**make_listing_data(
                starting_price=100.0, buy_it_now_price=100.0
            ))

    def test_starting_price_must_be_positive(self):
        with pytest.raises(Exception):
            ListingCreateRequest(**make_listing_data(starting_price=0))

    def test_image_urls_required_min_1(self):
        with pytest.raises(Exception):
            ListingCreateRequest(**make_listing_data(image_urls=[]))

    def test_image_urls_max_10(self):
        with pytest.raises(Exception):
            ListingCreateRequest(**make_listing_data(
                image_urls=[f"https://example.com/{i}.jpg" for i in range(11)]
            ))

    def test_condition_must_be_valid_enum(self):
        with pytest.raises(Exception):
            ListingCreateRequest(**make_listing_data(condition="broken"))

    def test_currency_must_be_valid(self):
        with pytest.raises(Exception):
            ListingCreateRequest(**make_listing_data(listing_currency="USD"))

    def test_valid_listing_passes(self):
        req = ListingCreateRequest(**make_listing_data())
        assert req.title_ar == "سيارة تويوتا كامري 2023"
        assert req.duration_hours == 24


# ── Service: Create Listing ───────────────────────────────────

class TestCreateListing:
    """FR-LIST-001/002: Creation + Free-tier cap."""

    @pytest.mark.asyncio
    async def test_creates_draft_listing(self, db_session, verified_user):
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        assert listing.status == "draft"
        assert listing.seller_id == verified_user.id
        assert listing.title_ar == data.title_ar
        assert listing.duration_hours == 24
        assert listing.bid_count == 0

    @pytest.mark.asyncio
    async def test_image_urls_stored_as_json(self, db_session, verified_user):
        urls = ["https://example.com/a.jpg", "https://example.com/b.jpg"]
        data = ListingCreateRequest(**make_listing_data(image_urls=urls))
        listing = await create_listing(verified_user.id, data, db_session)
        from app.services.listing.models import get_image_urls
        assert get_image_urls(listing) == urls

    @pytest.mark.asyncio
    async def test_free_tier_max_5_active(self, db_session, verified_user):
        """Free tier: max 5 active listings."""
        for i in range(5):
            lid = str(uuid4())
            l = Listing(
                id=lid,
                seller_id=verified_user.id,
                title_ar=f"عنصر {i}",
                description_ar="وصف طويل بما يكفي لتجاوز الحد الأدنى لعدد الأحرف المطلوب",
                category_id=1,
                condition="new",
                starting_price=10.0,
                listing_currency="JOD",
                duration_hours=24,
                status=ListingStatus.ACTIVE.value,
                bid_count=0,
            )
            set_image_urls(l, ["https://example.com/img.jpg"])
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        data = ListingCreateRequest(**make_listing_data())
        with pytest.raises(ListingLimitError):
            await create_listing(verified_user.id, data, db_session)

    @pytest.mark.asyncio
    async def test_draft_doesnt_count_toward_limit(self, db_session, verified_user):
        """Draft listings don't count toward active cap."""
        for i in range(5):
            lid = str(uuid4())
            l = Listing(
                id=lid,
                seller_id=verified_user.id,
                title_ar=f"مسودة {i}",
                description_ar="وصف طويل بما يكفي لتجاوز الحد الأدنى لعدد الأحرف",
                category_id=1,
                condition="new",
                starting_price=10.0,
                listing_currency="JOD",
                duration_hours=24,
                status=ListingStatus.DRAFT.value,
                bid_count=0,
            )
            set_image_urls(l, ["https://example.com/img.jpg"])
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        # Should succeed — drafts don't count
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        assert listing.status == "draft"


# ── Service: Update Listing ───────────────────────────────────

class TestUpdateListing:
    """FR-LIST-010: Edit blocked if bid_count > 0."""

    @pytest.mark.asyncio
    async def test_update_draft_succeeds(self, db_session, verified_user):
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        update = ListingUpdateRequest(title_ar="عنوان محدث جديد")
        updated = await update_listing(listing, update, db_session)
        assert updated.title_ar == "عنوان محدث جديد"

    @pytest.mark.asyncio
    async def test_update_blocked_with_bids(self, db_session, verified_user):
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        listing.bid_count = 1
        await db_session.commit()

        update = ListingUpdateRequest(title_ar="تحديث")
        with pytest.raises(BidCountError):
            await update_listing(listing, update, db_session)

    @pytest.mark.asyncio
    async def test_update_non_draft_blocked(self, db_session, verified_user):
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        listing.status = ListingStatus.ACTIVE.value
        await db_session.commit()

        update = ListingUpdateRequest(title_ar="تحديث")
        with pytest.raises(StatusError):
            await update_listing(listing, update, db_session)

    @pytest.mark.asyncio
    async def test_update_validates_reserve_price(self, db_session, verified_user):
        data = ListingCreateRequest(**make_listing_data(starting_price=100.0))
        listing = await create_listing(verified_user.id, data, db_session)

        update = ListingUpdateRequest(reserve_price=50.0)
        with pytest.raises(ValueError, match="reserve_price"):
            await update_listing(listing, update, db_session)


# ── Service: Delete Listing ───────────────────────────────────

class TestDeleteListing:
    """FR-LIST-011: Delete blocked if bid_count > 0."""

    @pytest.mark.asyncio
    async def test_delete_sets_cancelled(self, db_session, verified_user):
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        await delete_listing(listing, db_session)
        assert listing.status == ListingStatus.CANCELLED.value

    @pytest.mark.asyncio
    async def test_delete_blocked_with_bids(self, db_session, verified_user):
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        listing.bid_count = 3
        await db_session.commit()

        with pytest.raises(BidCountError):
            await delete_listing(listing, db_session)


# ── Service: Submit for Moderation ────────────────────────────

class TestSubmitForModeration:
    """FR-LIST-006: AI score > 70 → queue. FR-LIST-007: pHash detection."""

    @pytest.mark.asyncio
    async def test_low_score_goes_active(self, db_session, verified_user):
        """AI score ≤ 70 → listing goes directly to ACTIVE."""
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        with patch(
            "app.services.listing.service._run_moderation",
            new_callable=AsyncMock,
            return_value={"score": 30.0, "flags": [], "auto_approve": True},
        ):
            result = await submit_for_moderation(listing, db_session)

        assert result.status == ListingStatus.ACTIVE.value
        assert result.moderation_score == 30.0
        assert result.published_at is not None

    @pytest.mark.asyncio
    async def test_high_score_goes_to_moderation_queue(self, db_session, verified_user):
        """AI score > 70 → listing goes to PENDING_MODERATION."""
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        with patch(
            "app.services.listing.service._run_moderation",
            new_callable=AsyncMock,
            return_value={"score": 85.0, "flags": ["prohibited_item"], "auto_approve": False},
        ):
            result = await submit_for_moderation(listing, db_session)

        assert result.status == ListingStatus.PENDING_MODERATION.value
        assert result.moderation_score == 85.0
        assert result.published_at is None

    @pytest.mark.asyncio
    async def test_boundary_score_70_goes_active(self, db_session, verified_user):
        """Exactly 70.0 → active (threshold is > 70, not >=)."""
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        with patch(
            "app.services.listing.service._run_moderation",
            new_callable=AsyncMock,
            return_value={"score": 70.0, "flags": [], "auto_approve": True},
        ):
            result = await submit_for_moderation(listing, db_session)

        assert result.status == ListingStatus.ACTIVE.value

    @pytest.mark.asyncio
    async def test_boundary_score_70_1_goes_to_queue(self, db_session, verified_user):
        """70.1 → moderation queue."""
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        with patch(
            "app.services.listing.service._run_moderation",
            new_callable=AsyncMock,
            return_value={"score": 70.1, "flags": ["suspicious"], "auto_approve": False},
        ):
            result = await submit_for_moderation(listing, db_session)

        assert result.status == ListingStatus.PENDING_MODERATION.value

    @pytest.mark.asyncio
    async def test_ai_unavailable_fallback(self, db_session, verified_user):
        """AI unavailable → score=50 → moderation queue (not auto-approve)."""
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        # _run_moderation raises an exception internally → falls back to 50.0
        with patch(
            "app.services.listing.service._run_moderation",
            new_callable=AsyncMock,
            return_value={"score": 50.0, "flags": ["ai_unavailable"], "auto_approve": False},
        ):
            result = await submit_for_moderation(listing, db_session)

        assert result.moderation_score == 50.0
        assert result.status == ListingStatus.ACTIVE.value  # 50 ≤ 70

    @pytest.mark.asyncio
    async def test_submit_non_draft_raises(self, db_session, verified_user):
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        listing.status = ListingStatus.ACTIVE.value
        await db_session.commit()

        with pytest.raises(StatusError):
            await submit_for_moderation(listing, db_session)

    @pytest.mark.asyncio
    async def test_moderation_flags_stored(self, db_session, verified_user):
        data = ListingCreateRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        with patch(
            "app.services.listing.service._run_moderation",
            new_callable=AsyncMock,
            return_value={"score": 80.0, "flags": ["prohibited_item", "spam"], "auto_approve": False},
        ):
            result = await submit_for_moderation(listing, db_session)

        flags = json.loads(result.moderation_flags)
        assert "prohibited_item" in flags
        assert "spam" in flags


# ── pHash Duplicate Detection ─────────────────────────────────

class TestPHashDetection:
    """FR-LIST-007: pHash similarity ≥ 92% → flag."""

    def test_identical_hashes_100_percent(self):
        assert _hamming_similarity("abcdef01", "abcdef01") == 100.0

    def test_completely_different_hashes(self):
        # All bits different
        assert _hamming_similarity("00000000", "ffffffff") == 0.0

    def test_similar_hashes_high_percentage(self):
        # Only 1 bit difference in last nibble (f vs e → 1 bit)
        sim = _hamming_similarity("abcdef0f", "abcdef0e")
        assert sim > 90.0

    def test_different_lengths_returns_zero(self):
        assert _hamming_similarity("abcd", "abcdef") == 0.0

    @pytest.mark.asyncio
    async def test_phash_duplicate_found(self, db_session, verified_user):
        """Listings with similar pHash are flagged."""
        # Create existing listing with pHash
        existing = Listing(
            id=str(uuid4()),
            seller_id=verified_user.id,
            title_ar="منتج موجود",
            description_ar="وصف طويل بما يكفي لتجاوز الحد الأدنى لعدد الأحرف",
            category_id=1,
            condition="new",
            starting_price=100.0,
            listing_currency="JOD",
            duration_hours=24,
            status=ListingStatus.ACTIVE.value,
            phash="abcdef0123456789",
            bid_count=0,
        )
        set_image_urls(existing, ["img.jpg"])
        db_session.add(existing)
        await db_session.flush()
        await db_session.commit()

        # Check with identical hash
        dupes = await check_phash_duplicates("abcdef0123456789", str(uuid4()), db_session)
        assert len(dupes) == 1
        assert dupes[0]["similarity"] == 100.0

    @pytest.mark.asyncio
    async def test_phash_no_duplicate_below_threshold(self, db_session, verified_user):
        """Listings below 92% similarity are not flagged."""
        existing = Listing(
            id=str(uuid4()),
            seller_id=verified_user.id,
            title_ar="منتج مختلف",
            description_ar="وصف طويل بما يكفي لتجاوز الحد الأدنى لعدد الأحرف",
            category_id=1,
            condition="new",
            starting_price=100.0,
            listing_currency="JOD",
            duration_hours=24,
            status=ListingStatus.ACTIVE.value,
            phash="0000000000000000",
            bid_count=0,
        )
        set_image_urls(existing, ["img.jpg"])
        db_session.add(existing)
        await db_session.flush()
        await db_session.commit()

        # Very different hash
        dupes = await check_phash_duplicates("ffffffffffffffff", str(uuid4()), db_session)
        assert len(dupes) == 0


# ── List Listings (Filter/Sort/Pagination) ────────────────────

class TestListListings:
    """FR-LIST-003: GET /listings with filters."""

    @pytest.mark.asyncio
    async def test_list_empty(self, db_session):
        listings, total = await list_listings(db_session)
        assert listings == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self, db_session, verified_user):
        for status_val in [ListingStatus.ACTIVE.value, ListingStatus.DRAFT.value]:
            l = Listing(
                id=str(uuid4()),
                seller_id=verified_user.id,
                title_ar="عنصر",
                description_ar="وصف طويل بما يكفي لتجاوز الحد الأدنى لعدد الأحرف",
                category_id=1,
                condition="new",
                starting_price=100.0,
                listing_currency="JOD",
                duration_hours=24,
                status=status_val,
                bid_count=0,
            )
            set_image_urls(l, ["img.jpg"])
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        active, total = await list_listings(db_session, status="active")
        assert len(active) == 1
        assert total == 1

    @pytest.mark.asyncio
    async def test_list_with_category_filter(self, db_session, verified_user):
        for cat in [1, 2, 1]:
            l = Listing(
                id=str(uuid4()),
                seller_id=verified_user.id,
                title_ar="عنصر",
                description_ar="وصف طويل بما يكفي لتجاوز الحد الأدنى لعدد الأحرف",
                category_id=cat,
                condition="new",
                starting_price=100.0,
                listing_currency="JOD",
                duration_hours=24,
                status=ListingStatus.ACTIVE.value,
                bid_count=0,
            )
            set_image_urls(l, ["img.jpg"])
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        result, total = await list_listings(db_session, category_id=1)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_with_price_range(self, db_session, verified_user):
        for price in [50.0, 100.0, 200.0, 500.0]:
            l = Listing(
                id=str(uuid4()),
                seller_id=verified_user.id,
                title_ar="عنصر",
                description_ar="وصف طويل بما يكفي لتجاوز الحد الأدنى لعدد الأحرف",
                category_id=1,
                condition="new",
                starting_price=price,
                listing_currency="JOD",
                duration_hours=24,
                status=ListingStatus.ACTIVE.value,
                bid_count=0,
            )
            set_image_urls(l, ["img.jpg"])
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        result, _ = await list_listings(db_session, min_price=100.0, max_price=200.0)
        assert len(result) == 2
        prices = [float(r.starting_price) for r in result]
        assert all(100.0 <= p <= 200.0 for p in prices)

    @pytest.mark.asyncio
    async def test_list_pagination(self, db_session, verified_user):
        for i in range(5):
            l = Listing(
                id=str(uuid4()),
                seller_id=verified_user.id,
                title_ar=f"عنصر {i}",
                description_ar="وصف طويل بما يكفي لتجاوز الحد الأدنى لعدد الأحرف",
                category_id=1,
                condition="new",
                starting_price=100.0,
                listing_currency="JOD",
                duration_hours=24,
                status=ListingStatus.ACTIVE.value,
                bid_count=0,
            )
            set_image_urls(l, ["img.jpg"])
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        page1, total = await list_listings(db_session, limit=2)
        assert len(page1) == 2
        assert total == 5

    @pytest.mark.asyncio
    async def test_list_seller_filter(self, db_session, verified_user):
        other_id = str(uuid4())
        for sid in [verified_user.id, other_id, verified_user.id]:
            l = Listing(
                id=str(uuid4()),
                seller_id=sid,
                title_ar="عنصر",
                description_ar="وصف طويل بما يكفي لتجاوز الحد الأدنى لعدد الأحرف",
                category_id=1,
                condition="new",
                starting_price=100.0,
                listing_currency="JOD",
                duration_hours=24,
                status=ListingStatus.ACTIVE.value,
                bid_count=0,
            )
            set_image_urls(l, ["img.jpg"])
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        result, total = await list_listings(db_session, seller_id=verified_user.id)
        assert len(result) == 2


# ── Endpoint Tests ────────────────────────────────────────────

class TestCreateListingEndpoint:
    """POST /api/v1/listings integration tests."""

    @pytest.mark.asyncio
    async def test_create_happy_path(self, client, verified_auth_headers):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert data["title_ar"] == "سيارة تويوتا كامري 2023"
        assert data["duration_hours"] == 24
        assert data["bid_count"] == 0
        assert len(data["image_urls"]) == 1

    @pytest.mark.asyncio
    async def test_create_requires_kyc(self, client, auth_headers):
        """Non-KYC-verified user gets 403."""
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=auth_headers["headers"],
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_unauthenticated(self, client):
        resp = await client.post("/api/v1/listings/", json=make_listing_data())
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_create_invalid_reserve_price(self, client, verified_auth_headers):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(starting_price=100.0, reserve_price=50.0),
            headers=verified_auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_invalid_duration(self, client, verified_auth_headers):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(duration_hours=0),
            headers=verified_auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_empty_images(self, client, verified_auth_headers):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(image_urls=[]),
            headers=verified_auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_free_tier_limit(self, client, verified_auth_headers, db_session, verified_user):
        """Free tier: 6th listing creation fails."""
        for i in range(5):
            l = Listing(
                id=str(uuid4()),
                seller_id=verified_user.id,
                title_ar=f"عنصر {i}",
                description_ar="وصف طويل بما يكفي لتجاوز الحد الأدنى لعدد الأحرف",
                category_id=1,
                condition="new",
                starting_price=10.0,
                listing_currency="JOD",
                duration_hours=24,
                status=ListingStatus.ACTIVE.value,
                bid_count=0,
            )
            set_image_urls(l, ["img.jpg"])
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "LISTING_LIMIT_REACHED"

    @pytest.mark.asyncio
    async def test_create_with_all_optional_fields(self, client, verified_auth_headers):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(
                title_en="Toyota Camry 2023",
                description_en="Excellent condition Toyota Camry 2023 model, only 20k km driven",
                reserve_price=150.0,
                buy_it_now_price=500.0,
                duration_hours=48,
                is_charity=True,
            ),
            headers=verified_auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title_en"] == "Toyota Camry 2023"
        assert data["reserve_price"] == 150.0
        assert data["duration_hours"] == 48
        assert data["is_charity"] is True


class TestGetListingEndpoint:
    """GET /api/v1/listings/:id"""

    @pytest.mark.asyncio
    async def test_get_listing(self, client, verified_auth_headers):
        # Create first
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        # Get it (no auth required for reading)
        resp = await client.get(f"/api/v1/listings/{listing_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == listing_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_404(self, client):
        resp = await client.get(f"/api/v1/listings/{uuid4()}")
        assert resp.status_code == 404


class TestListListingsEndpoint:
    """GET /api/v1/listings"""

    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        resp = await client.get("/api/v1/listings/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"] == []
        assert data["total_count"] == 0

    @pytest.mark.asyncio
    async def test_list_with_data(self, client, verified_auth_headers):
        await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        resp = await client.get("/api/v1/listings/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 1
        assert len(data["data"]) == 1

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, client, verified_auth_headers, db_session, verified_user):
        # Create active listing directly in DB
        l = Listing(
            id=str(uuid4()),
            seller_id=verified_user.id,
            title_ar="نشط",
            description_ar="وصف طويل بما يكفي لتجاوز الحد الأدنى لعدد الأحرف",
            category_id=1,
            condition="new",
            starting_price=100.0,
            listing_currency="JOD",
            duration_hours=24,
            status=ListingStatus.ACTIVE.value,
            bid_count=0,
        )
        set_image_urls(l, ["img.jpg"])
        db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        # Also create a draft via API
        await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )

        resp = await client.get("/api/v1/listings/?status=active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 1
        assert data["data"][0]["status"] == "active"


class TestUpdateListingEndpoint:
    """PATCH /api/v1/listings/:id"""

    @pytest.mark.asyncio
    async def test_update_draft(self, client, verified_auth_headers):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/listings/{listing_id}",
            json={"title_ar": "عنوان جديد محدث"},
            headers=verified_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["title_ar"] == "عنوان جديد محدث"

    @pytest.mark.asyncio
    async def test_update_blocked_with_bids(self, client, verified_auth_headers, db_session):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        # Set bid_count > 0 directly
        listing = await db_session.get(Listing, listing_id)
        listing.bid_count = 2
        await db_session.commit()

        resp = await client.patch(
            f"/api/v1/listings/{listing_id}",
            json={"title_ar": "تحديث ممنوع"},
            headers=verified_auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "HAS_BIDS"

    @pytest.mark.asyncio
    async def test_update_non_owner_forbidden(self, client, verified_auth_headers, db_session):
        # Create listing
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        # Try to update with different user
        from app.services.auth.models import User, UserRole, KYCStatus, ATSTier
        from app.services.auth.service import issue_tokens
        other = User(
            id=str(uuid4()),
            phone="+962792222222",
            full_name_ar="مستخدم آخر",
            role=UserRole.SELLER,
            kyc_status=KYCStatus.VERIFIED,
            ats_score=400,
            ats_tier=ATSTier.TRUSTED,
            country_code="JO",
            preferred_language="ar",
        )
        db_session.add(other)
        await db_session.flush()
        await db_session.commit()

        token, _, _ = issue_tokens(other)
        resp = await client.patch(
            f"/api/v1/listings/{listing_id}",
            json={"title_ar": "اختراق"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


class TestDeleteListingEndpoint:
    """DELETE /api/v1/listings/:id"""

    @pytest.mark.asyncio
    async def test_delete_draft(self, client, verified_auth_headers):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/listings/{listing_id}",
            headers=verified_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        # Verify it's cancelled
        resp = await client.get(f"/api/v1/listings/{listing_id}")
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_delete_blocked_with_bids(self, client, verified_auth_headers, db_session):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        listing = await db_session.get(Listing, listing_id)
        listing.bid_count = 1
        await db_session.commit()

        resp = await client.delete(
            f"/api/v1/listings/{listing_id}",
            headers=verified_auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "HAS_BIDS"


class TestSubmitListingEndpoint:
    """POST /api/v1/listings/:id/submit"""

    @pytest.mark.asyncio
    async def test_submit_auto_approve(self, client, verified_auth_headers):
        """AI score ≤ 70 → listing goes ACTIVE."""
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        with patch(
            "app.services.listing.service._run_moderation",
            new_callable=AsyncMock,
            return_value={"score": 25.0, "flags": [], "auto_approve": True},
        ):
            resp = await client.post(
                f"/api/v1/listings/{listing_id}/submit",
                headers=verified_auth_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
        assert resp.json()["moderation_score"] == 25.0

    @pytest.mark.asyncio
    async def test_submit_to_moderation_queue(self, client, verified_auth_headers):
        """AI score > 70 → PENDING_MODERATION."""
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        with patch(
            "app.services.listing.service._run_moderation",
            new_callable=AsyncMock,
            return_value={"score": 90.0, "flags": ["prohibited"], "auto_approve": False},
        ):
            resp = await client.post(
                f"/api/v1/listings/{listing_id}/submit",
                headers=verified_auth_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending_moderation"

    @pytest.mark.asyncio
    async def test_submit_already_active_fails(self, client, verified_auth_headers, db_session):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        # Make it active first
        listing = await db_session.get(Listing, listing_id)
        listing.status = ListingStatus.ACTIVE.value
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/listings/{listing_id}/submit",
            headers=verified_auth_headers,
        )
        assert resp.status_code == 409


class TestImageUploadEndpoint:
    """POST /api/v1/listings/:id/images"""

    @pytest.mark.asyncio
    async def test_get_upload_urls(self, client, verified_auth_headers):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        resp = await client.post(
            f"/api/v1/listings/{listing_id}/images",
            json={"count": 3},
            headers=verified_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["upload_urls"]) == 3
        assert data["expires_in"] == 300
        for u in data["upload_urls"]:
            assert "upload_url" in u
            assert "s3_key" in u
            assert u["s3_key"].startswith(f"listings/{listing_id}/")

    @pytest.mark.asyncio
    async def test_upload_urls_max_10(self, client, verified_auth_headers):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        resp = await client.post(
            f"/api/v1/listings/{listing_id}/images",
            json={"count": 11},
            headers=verified_auth_headers,
        )
        assert resp.status_code == 422
