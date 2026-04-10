"""
Listing tests — FR-LIST-001 -> FR-LIST-013.

Covers: creation validation, price constraints (INTEGER cents), Free-tier cap,
bid-count guards, AI moderation routing (publish), pHash duplicate detection,
image upload/confirm flow, CRUD operations, filter/sort/pagination, auth.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.listing.models import Listing, ListingImage, ListingStatus
from app.services.listing.service import (
    create_listing,
    update_listing,
    delete_listing,
    publish_listing,
    get_listings,
    confirm_images,
    request_image_upload,
    check_phash_duplicates,
    _hamming_similarity,
    ListingLimitError,
    BidCountError,
    StatusError,
    ImageLimitError,
)
from app.services.listing.schemas import CreateListingRequest, UpdateListingRequest
from app.tests.conftest import make_listing_data


# ── Helpers for building Listing ORM objects in tests ─────────

def _future(minutes: int = 10) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def _make_listing(seller_id: str, **overrides) -> Listing:
    """Build a Listing ORM object with new-schema defaults."""
    defaults = dict(
        id=str(uuid4()),
        seller_id=seller_id,
        title_ar="عنصر اختبار",
        title_en="Test item",
        category_id=1,
        condition="like_new",
        starting_price=10000,
        min_increment=2500,
        starts_at=_future(10),
        ends_at=_future(60 * 25),
        status=ListingStatus.DRAFT.value,
        bid_count=0,
        watcher_count=0,
        location_country="JO",
        moderation_status="pending",
        moderation_flags=[],
    )
    defaults.update(overrides)
    return Listing(**defaults)


# ── Schema Validation ─────────────────────────────────────────

class TestListingSchemaValidation:
    """FR-LIST-001: Input validation rules."""

    def test_title_ar_required(self):
        with pytest.raises(Exception):
            CreateListingRequest(**make_listing_data(title_ar=""))

    def test_starting_price_min_100_cents(self):
        """Minimum price is 100 cents (1 JOD)."""
        with pytest.raises(Exception):
            CreateListingRequest(**make_listing_data(starting_price=50))

    def test_valid_starting_price(self):
        req = CreateListingRequest(**make_listing_data(starting_price=100))
        assert req.starting_price == 100

    def test_reserve_must_be_gte_starting(self):
        with pytest.raises(Exception):
            CreateListingRequest(**make_listing_data(
                starting_price=10000, reserve_price=5000
            ))

    def test_reserve_equal_to_starting_is_valid(self):
        req = CreateListingRequest(**make_listing_data(
            starting_price=10000, reserve_price=10000
        ))
        assert req.reserve_price == 10000

    def test_buy_it_now_must_exceed_starting(self):
        with pytest.raises(Exception):
            CreateListingRequest(**make_listing_data(
                starting_price=10000, buy_it_now_price=10000
            ))

    def test_buy_it_now_above_starting_valid(self):
        req = CreateListingRequest(**make_listing_data(
            starting_price=10000, buy_it_now_price=20000
        ))
        assert req.buy_it_now_price == 20000

    def test_condition_must_be_valid_enum(self):
        with pytest.raises(Exception):
            CreateListingRequest(**make_listing_data(condition="broken"))

    def test_valid_conditions(self):
        for cond in ("brand_new", "like_new", "very_good", "good", "acceptable"):
            req = CreateListingRequest(**make_listing_data(condition=cond))
            assert req.condition.value == cond

    def test_starts_at_must_be_future(self):
        """starts_at must be at least 5 minutes in the future."""
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with pytest.raises(Exception):
            CreateListingRequest(**make_listing_data(starts_at=past))

    def test_duration_min_1_hour(self):
        now = datetime.now(timezone.utc)
        starts = (now + timedelta(minutes=10)).isoformat()
        ends = (now + timedelta(minutes=40)).isoformat()  # 30 min < 1h
        with pytest.raises(Exception):
            CreateListingRequest(**make_listing_data(starts_at=starts, ends_at=ends))

    def test_duration_max_7_days(self):
        now = datetime.now(timezone.utc)
        starts = (now + timedelta(minutes=10)).isoformat()
        ends = (now + timedelta(days=8)).isoformat()
        with pytest.raises(Exception):
            CreateListingRequest(**make_listing_data(starts_at=starts, ends_at=ends))

    def test_charity_requires_ngo_id(self):
        with pytest.raises(Exception):
            CreateListingRequest(**make_listing_data(is_charity=True))

    def test_charity_with_ngo_id_valid(self):
        req = CreateListingRequest(**make_listing_data(is_charity=True, ngo_id=1))
        assert req.is_charity is True
        assert req.ngo_id == 1

    def test_title_ar_must_contain_arabic(self):
        """title_ar must contain at least one Arabic character."""
        with pytest.raises(Exception, match="Arabic"):
            CreateListingRequest(**make_listing_data(title_ar="BMW X5 2023"))

    def test_title_min_length_3(self):
        """Titles must be at least 3 characters."""
        with pytest.raises(Exception):
            CreateListingRequest(**make_listing_data(title_ar="اب"))
        with pytest.raises(Exception):
            CreateListingRequest(**make_listing_data(title_en="AB"))

    def test_description_en_min_10_chars(self):
        """description_en must be at least 10 characters when provided."""
        with pytest.raises(Exception):
            CreateListingRequest(**make_listing_data(description_en="Short"))

    def test_description_en_valid(self):
        req = CreateListingRequest(**make_listing_data(
            description_en="This is a valid description that is long enough"
        ))
        assert len(req.description_en) > 10

    def test_valid_listing_passes(self):
        req = CreateListingRequest(**make_listing_data())
        assert req.title_ar == "سيارة تويوتا كامري 2023"
        assert req.starting_price == 10000
        assert req.condition.value == "like_new"


# ── Service: Create Listing ──────────────────────────────────

class TestCreateListing:
    """FR-LIST-001/002: Creation + Free-tier cap."""

    @pytest.mark.asyncio
    async def test_creates_draft_listing(self, db_session, verified_user):
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        assert listing.status == "draft"
        assert listing.seller_id == verified_user.id
        assert listing.title_ar == data.title_ar
        assert listing.starting_price == 10000
        assert listing.bid_count == 0
        assert listing.condition == "like_new"

    @pytest.mark.asyncio
    async def test_free_tier_max_5_active(self, db_session, verified_user):
        """Free tier: max 5 active listings."""
        for i in range(5):
            l = _make_listing(
                verified_user.id,
                title_ar=f"عنصر {i}",
                status=ListingStatus.ACTIVE.value,
            )
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        data = CreateListingRequest(**make_listing_data())
        with pytest.raises(ListingLimitError):
            await create_listing(verified_user.id, data, db_session)

    @pytest.mark.asyncio
    async def test_pro_seller_exempt_from_cap(self, db_session, verified_user):
        """Pro sellers are exempt from the 5-listing cap."""
        for i in range(5):
            l = _make_listing(
                verified_user.id,
                title_ar=f"عنصر {i}",
                status=ListingStatus.ACTIVE.value,
            )
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(
            verified_user.id, data, db_session, is_pro_seller=True
        )
        assert listing.status == "draft"

    @pytest.mark.asyncio
    async def test_draft_doesnt_count_toward_limit(self, db_session, verified_user):
        for i in range(5):
            l = _make_listing(
                verified_user.id,
                title_ar=f"مسودة {i}",
                status=ListingStatus.DRAFT.value,
            )
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        assert listing.status == "draft"


# ── Service: Update Listing ──────────────────────────────────

class TestUpdateListing:
    """FR-LIST-010: Edit blocked if bid_count > 0."""

    @pytest.mark.asyncio
    async def test_update_draft_succeeds(self, db_session, verified_user):
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        update = UpdateListingRequest(title_ar="عنوان محدث جديد")
        updated = await update_listing(listing, update, db_session)
        assert updated.title_ar == "عنوان محدث جديد"

    @pytest.mark.asyncio
    async def test_update_blocked_with_bids(self, db_session, verified_user):
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        listing.bid_count = 1
        await db_session.commit()

        update = UpdateListingRequest(title_ar="تحديث")
        with pytest.raises(BidCountError):
            await update_listing(listing, update, db_session)

    @pytest.mark.asyncio
    async def test_update_active_allowed(self, db_session, verified_user):
        """Active listings with 0 bids can be edited."""
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        listing.status = ListingStatus.ACTIVE.value
        await db_session.commit()

        update = UpdateListingRequest(title_ar="عنوان محدث")
        updated = await update_listing(listing, update, db_session)
        assert updated.title_ar == "عنوان محدث"

    @pytest.mark.asyncio
    async def test_update_ended_blocked(self, db_session, verified_user):
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        listing.status = ListingStatus.ENDED.value
        await db_session.commit()

        update = UpdateListingRequest(title_ar="تحديث")
        with pytest.raises(StatusError):
            await update_listing(listing, update, db_session)

    @pytest.mark.asyncio
    async def test_update_validates_reserve_price(self, db_session, verified_user):
        data = CreateListingRequest(**make_listing_data(starting_price=10000))
        listing = await create_listing(verified_user.id, data, db_session)

        update = UpdateListingRequest(reserve_price=5000)
        with pytest.raises(ValueError, match="reserve_price"):
            await update_listing(listing, update, db_session)


# ── Service: Delete Listing ──────────────────────────────────

class TestDeleteListing:
    """FR-LIST-011: Delete blocked if bid_count > 0."""

    @pytest.mark.asyncio
    async def test_delete_sets_cancelled(self, db_session, verified_user):
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        await delete_listing(listing, db_session)
        assert listing.status == ListingStatus.CANCELLED.value

    @pytest.mark.asyncio
    async def test_delete_active_rejected(self, db_session, verified_user):
        """Active listings cannot be deleted — use 'end early' instead."""
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        listing.status = ListingStatus.ACTIVE.value
        await db_session.commit()

        with pytest.raises(StatusError, match="end early"):
            await delete_listing(listing, db_session)

    @pytest.mark.asyncio
    async def test_delete_blocked_with_bids(self, db_session, verified_user):
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        listing.bid_count = 3
        await db_session.commit()

        with pytest.raises(BidCountError):
            await delete_listing(listing, db_session)


# ── Service: Publish Listing ─────────────────────────────────

class TestPublishListing:
    """FR-LIST-006: AI moderation on publish. Requires images."""

    @pytest.mark.asyncio
    async def test_publish_no_images_blocked(self, db_session, verified_user):
        """Cannot publish without at least 1 confirmed image."""
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        with pytest.raises(StatusError, match="image"):
            await publish_listing(listing, db_session)

    @pytest.mark.asyncio
    async def test_publish_low_score_goes_active(self, db_session, verified_user):
        """AI score <= 70 -> listing goes directly to ACTIVE."""
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        # Add an image
        img = ListingImage(
            id=str(uuid4()), listing_id=listing.id,
            s3_key="media/test/img.jpg", display_order=0,
        )
        db_session.add(img)
        await db_session.flush()
        await db_session.commit()

        with patch(
            "app.services.listing.service._run_moderation",
            new_callable=AsyncMock,
            return_value={"score": 30.0, "flags": [], "auto_approve": True},
        ):
            result = await publish_listing(listing, db_session)

        assert result.status == ListingStatus.ACTIVE.value
        assert result.moderation_score == 30.0
        assert result.moderation_status == "approved"

    @pytest.mark.asyncio
    async def test_publish_high_score_goes_pending_review(self, db_session, verified_user):
        """AI score > 70 -> listing goes to PENDING_REVIEW."""
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        img = ListingImage(
            id=str(uuid4()), listing_id=listing.id,
            s3_key="media/test/img.jpg", display_order=0,
        )
        db_session.add(img)
        await db_session.flush()
        await db_session.commit()

        with patch(
            "app.services.listing.service._run_moderation",
            new_callable=AsyncMock,
            return_value={"score": 85.0, "flags": ["prohibited_item"], "auto_approve": False},
        ):
            result = await publish_listing(listing, db_session)

        assert result.status == ListingStatus.PENDING_REVIEW.value
        assert result.moderation_score == 85.0
        assert result.moderation_status == "flagged"

    @pytest.mark.asyncio
    async def test_publish_boundary_70_goes_active(self, db_session, verified_user):
        """Exactly 70.0 -> active (threshold is > 70, not >=)."""
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        img = ListingImage(
            id=str(uuid4()), listing_id=listing.id,
            s3_key="media/test/img.jpg", display_order=0,
        )
        db_session.add(img)
        await db_session.flush()
        await db_session.commit()

        with patch(
            "app.services.listing.service._run_moderation",
            new_callable=AsyncMock,
            return_value={"score": 70.0, "flags": [], "auto_approve": True},
        ):
            result = await publish_listing(listing, db_session)

        assert result.status == ListingStatus.ACTIVE.value

    @pytest.mark.asyncio
    async def test_publish_non_draft_raises(self, db_session, verified_user):
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)
        listing.status = ListingStatus.ACTIVE.value
        await db_session.commit()

        with pytest.raises(StatusError):
            await publish_listing(listing, db_session)


# ── pHash Duplicate Detection ────────────────────────────────

class TestPHashDetection:
    """FR-LIST-007: pHash similarity >= 92% -> flag."""

    def test_identical_hashes_100_percent(self):
        assert _hamming_similarity("abcdef01", "abcdef01") == 100.0

    def test_completely_different_hashes(self):
        assert _hamming_similarity("00000000", "ffffffff") == 0.0

    def test_similar_hashes_high_percentage(self):
        sim = _hamming_similarity("abcdef0f", "abcdef0e")
        assert sim > 90.0

    def test_different_lengths_returns_zero(self):
        assert _hamming_similarity("abcd", "abcdef") == 0.0

    @pytest.mark.asyncio
    async def test_phash_duplicate_found(self, db_session, verified_user):
        """Listings with similar pHash are flagged."""
        existing = _make_listing(
            verified_user.id,
            status=ListingStatus.ACTIVE.value,
            phash="abcdef0123456789",
        )
        db_session.add(existing)
        await db_session.flush()
        await db_session.commit()

        dupes = await check_phash_duplicates("abcdef0123456789", str(uuid4()), db_session)
        assert len(dupes) == 1
        assert dupes[0]["similarity"] == 100.0

    @pytest.mark.asyncio
    async def test_phash_no_duplicate_below_threshold(self, db_session, verified_user):
        existing = _make_listing(
            verified_user.id,
            status=ListingStatus.ACTIVE.value,
            phash="0000000000000000",
        )
        db_session.add(existing)
        await db_session.flush()
        await db_session.commit()

        dupes = await check_phash_duplicates("ffffffffffffffff", str(uuid4()), db_session)
        assert len(dupes) == 0


# ── Image Upload Flow ────────────────────────────────────────

class TestImageUpload:
    """FR-LIST-005: Presigned S3 PUT, confirm, max 10 images."""

    @pytest.mark.asyncio
    async def test_request_upload_urls(self, db_session, verified_user):
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        urls = await request_image_upload(listing.id, 3, db_session)
        assert len(urls) == 3
        for u in urls:
            assert "upload_url" in u
            assert "s3_key" in u
            assert u["s3_key"].startswith(f"media/{listing.id}/")

    @pytest.mark.asyncio
    async def test_request_upload_exceeds_limit(self, db_session, verified_user):
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        with pytest.raises(ImageLimitError):
            await request_image_upload(listing.id, 11, db_session)

    @pytest.mark.asyncio
    async def test_confirm_images_creates_records(self, db_session, verified_user):
        data = CreateListingRequest(**make_listing_data())
        listing = await create_listing(verified_user.id, data, db_session)

        keys = [f"media/{listing.id}/img_{uuid4()}.jpg" for _ in range(3)]
        with patch("boto3.client") as mock_client:
            mock_s3 = mock_client.return_value
            mock_s3.head_object.return_value = {}
            confirmed = await confirm_images(listing.id, keys, db_session)
        assert confirmed == 3

        # Verify records created
        from sqlalchemy import select, func
        count = (await db_session.execute(
            select(func.count(ListingImage.id)).where(
                ListingImage.listing_id == listing.id
            )
        )).scalar()
        assert count == 3


# ── List Listings (Filter/Sort/Pagination) ───────────────────

class TestListListings:
    """FR-LIST-003: GET /listings with filters."""

    @pytest.mark.asyncio
    async def test_list_empty(self, db_session):
        listings, total = await get_listings(db_session)
        assert listings == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self, db_session, verified_user):
        for status_val in [ListingStatus.ACTIVE.value, ListingStatus.DRAFT.value]:
            l = _make_listing(verified_user.id, status=status_val)
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        active, total = await get_listings(db_session, status="active")
        assert len(active) == 1
        assert total == 1

    @pytest.mark.asyncio
    async def test_list_with_category_filter(self, db_session, verified_user):
        for cat in [1, 2, 1]:
            l = _make_listing(verified_user.id, category_id=cat, status=ListingStatus.ACTIVE.value)
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        result, total = await get_listings(db_session, category_id=1)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_with_price_range(self, db_session, verified_user):
        for price in [5000, 10000, 20000, 50000]:
            l = _make_listing(
                verified_user.id,
                starting_price=price,
                status=ListingStatus.ACTIVE.value,
            )
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        result, _ = await get_listings(db_session, min_price=10000, max_price=20000)
        assert len(result) == 2
        assert all(10000 <= r.starting_price <= 20000 for r in result)

    @pytest.mark.asyncio
    async def test_list_pagination(self, db_session, verified_user):
        for i in range(5):
            l = _make_listing(
                verified_user.id,
                title_ar=f"عنصر {i}",
                status=ListingStatus.ACTIVE.value,
            )
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        page1, total = await get_listings(db_session, limit=2, offset=0)
        assert len(page1) == 2
        assert total == 5

        page2, _ = await get_listings(db_session, limit=2, offset=2)
        assert len(page2) == 2

    @pytest.mark.asyncio
    async def test_list_seller_filter(self, db_session, verified_user):
        other_id = str(uuid4())
        for sid in [verified_user.id, other_id, verified_user.id]:
            l = _make_listing(sid, status=ListingStatus.ACTIVE.value)
            db_session.add(l)
        await db_session.flush()
        await db_session.commit()

        result, total = await get_listings(db_session, seller_id=verified_user.id)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_limit_max_50(self, db_session, verified_user):
        """Limit is capped at 50."""
        result, _ = await get_listings(db_session, limit=100)
        # Should not error; internally capped


# ── Endpoint Tests ───────────────────────────────────────────

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
        assert data["starting_price"] == 10000
        assert data["bid_count"] == 0
        assert data["condition"] == "like_new"

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
            json=make_listing_data(starting_price=10000, reserve_price=5000),
            headers=verified_auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_free_tier_limit(self, client, verified_auth_headers, db_session, verified_user):
        """Free tier: 6th listing creation fails."""
        for i in range(5):
            l = _make_listing(
                verified_user.id,
                title_ar=f"عنصر {i}",
                status=ListingStatus.ACTIVE.value,
            )
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


class TestGetListingEndpoint:
    """GET /api/v1/listings/:id"""

    @pytest.mark.asyncio
    async def test_get_listing(self, client, verified_auth_headers):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        resp = await client.get(f"/api/v1/listings/{listing_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == listing_id
        assert "seller" in resp.json()  # Includes seller summary

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
        assert "limit" in data
        assert "offset" in data

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
        l = _make_listing(verified_user.id, status=ListingStatus.ACTIVE.value)
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
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        from app.services.auth.models import User, UserRole, UserStatus, KYCStatus
        from app.services.auth.service import issue_tokens
        other = User(
            id=str(uuid4()),
            phone="+962792222222",
            full_name_ar="مستخدم آخر",
            full_name="Other User",
            role=UserRole.SELLER,
            status=UserStatus.ACTIVE,
            kyc_status=KYCStatus.VERIFIED,
            ats_score=400,
            preferred_language="ar",
            fcm_tokens=[],
            is_pro_seller=False,
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

    @pytest.mark.asyncio
    async def test_delete_active_listing_rejected(self, client, verified_auth_headers, db_session):
        """Active listings cannot be deleted via API — use 'end early'."""
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        listing = await db_session.get(Listing, listing_id)
        listing.status = ListingStatus.ACTIVE.value
        await db_session.commit()

        resp = await client.delete(
            f"/api/v1/listings/{listing_id}",
            headers=verified_auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_STATUS"


class TestPublishListingEndpoint:
    """POST /api/v1/listings/:id/publish"""

    @pytest.mark.asyncio
    async def test_publish_auto_approve(self, client, verified_auth_headers, db_session):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        # Add an image
        img = ListingImage(
            id=str(uuid4()), listing_id=listing_id,
            s3_key="media/test/img.jpg", display_order=0,
        )
        db_session.add(img)
        await db_session.flush()
        await db_session.commit()

        with patch(
            "app.services.listing.service._run_moderation",
            new_callable=AsyncMock,
            return_value={"score": 25.0, "flags": [], "auto_approve": True},
        ):
            resp = await client.post(
                f"/api/v1/listings/{listing_id}/publish",
                headers=verified_auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["moderation_score"] == 25.0
        assert data["moderation_status"] == "approved"

    @pytest.mark.asyncio
    async def test_publish_to_moderation_queue(self, client, verified_auth_headers, db_session):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        img = ListingImage(
            id=str(uuid4()), listing_id=listing_id,
            s3_key="media/test/img.jpg", display_order=0,
        )
        db_session.add(img)
        await db_session.flush()
        await db_session.commit()

        with patch(
            "app.services.listing.service._run_moderation",
            new_callable=AsyncMock,
            return_value={"score": 90.0, "flags": ["prohibited"], "auto_approve": False},
        ):
            resp = await client.post(
                f"/api/v1/listings/{listing_id}/publish",
                headers=verified_auth_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending_review"

    @pytest.mark.asyncio
    async def test_publish_no_images_fails(self, client, verified_auth_headers):
        resp = await client.post(
            "/api/v1/listings/",
            json=make_listing_data(),
            headers=verified_auth_headers,
        )
        listing_id = resp.json()["id"]

        resp = await client.post(
            f"/api/v1/listings/{listing_id}/publish",
            headers=verified_auth_headers,
        )
        assert resp.status_code == 409
