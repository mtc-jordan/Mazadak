"""B2B Tender Rooms tests — FR-B2B-001..010.

Covers:
  - Room CRUD (admin only)
  - Invitation flow (invite, revoke, access check, pre-qualification)
  - Sealed bid submission (valid, duplicate, deadline, uninvited, min amount)
  - Sealed bid response suppression (hidden before announce, visible after)
  - Results announcement (winner flag + status transition)
  - Mobile GET /tenders/{id} endpoint shape
  - Analytics (participation rate, avg/min/max bid, price vs estimate)
  - CSV import
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.services.auth.models import KYCStatus, User, UserRole, UserStatus
from app.services.b2b import service as b2b_service
from app.services.b2b.models import (
    B2BBid,
    B2BInvitation,
    B2BInvitationStatus,
    B2BRoom,
    B2BRoomStatus,
)
from app.services.b2b.schemas import (
    AnnounceResultsRequest,
    InviteBidderItem,
    InviteBiddersRequest,
    RoomUpdateRequest,
    SubmitBidRequest,
    TenderRoomCreateRequest,
)
from app.services.admin.models import AdminAuditLog
from app.tests.conftest import _register_sqlite_functions


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
async def b2b_db():
    """Async SQLite session with auth + b2b + audit tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)

    tables = [
        User.__table__,
        B2BRoom.__table__,
        B2BBid.__table__,
        B2BInvitation.__table__,
        AdminAuditLog.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _make_user(
    db: AsyncSession,
    *,
    phone: str,
    role: UserRole = UserRole.BUYER,
    kyc: KYCStatus = KYCStatus.VERIFIED,
    ats_score: int = 500,
    full_name: str = "Test User",
) -> User:
    user = User(
        id=str(uuid4()),
        phone=phone,
        full_name=full_name,
        full_name_ar=full_name,
        role=role,
        status=UserStatus.ACTIVE,
        kyc_status=kyc,
        ats_score=ats_score,
        preferred_language="ar",
        fcm_tokens=[],
        is_pro_seller=False,
    )
    db.add(user)
    await db.flush()
    await db.commit()
    return user


async def _make_room(
    db: AsyncSession,
    admin: User,
    *,
    reference: str = "T-2026-001",
    sealed: bool = True,
    min_lot: int = 1_000_000,
    estimated: int | None = 5_000_000,
    deadline_days: int = 7,
) -> B2BRoom:
    data = TenderRoomCreateRequest(
        client_name="Ministry of Finance",
        tender_reference=reference,
        submission_deadline=datetime.now(timezone.utc)
        + timedelta(days=deadline_days),
        sealed=sealed,
        min_lot_amount=min_lot,
        estimated_value=estimated,
        description="Surplus vehicles disposal",
    )
    return await b2b_service.create_room(data, admin, db)


# ═══════════════════════════════════════════════════════════════════
# Room CRUD
# ═══════════════════════════════════════════════════════════════════


class TestRoomCrud:
    async def test_create_room_persists_all_fields(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)

        room = await _make_room(b2b_db, admin, reference="T-2026-100")

        assert room.id is not None
        assert room.client_name == "Ministry of Finance"
        assert room.tender_reference == "T-2026-100"
        assert room.status == B2BRoomStatus.OPEN.value
        assert room.sealed is True
        assert room.min_lot_amount == 1_000_000
        assert room.created_by == admin.id

    async def test_duplicate_reference_raises(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        await _make_room(b2b_db, admin, reference="T-DUP")

        with pytest.raises(ValueError, match="already exists"):
            await _make_room(b2b_db, admin, reference="T-DUP")

    async def test_update_room_patches_fields(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        room = await _make_room(b2b_db, admin)

        updated = await b2b_service.update_room(
            room,
            RoomUpdateRequest(description="Updated description", estimated_value=9_000_000),
            admin,
            b2b_db,
        )
        assert updated.description == "Updated description"
        assert updated.estimated_value == 9_000_000

    async def test_list_rooms_filters_by_status(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        await _make_room(b2b_db, admin, reference="T-A")
        r2 = await _make_room(b2b_db, admin, reference="T-B")
        r2.status = B2BRoomStatus.CLOSED.value
        await b2b_db.commit()

        resp = await b2b_service.list_rooms(b2b_db, status="open")
        assert resp.total == 1
        assert resp.items[0].tender_reference == "T-A"


# ═══════════════════════════════════════════════════════════════════
# Invitations + access
# ═══════════════════════════════════════════════════════════════════


class TestInvitations:
    async def test_invite_creates_pending(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        bidder = await _make_user(b2b_db, phone="+962790000002")
        room = await _make_room(b2b_db, admin)

        created = await b2b_service.invite_bidders(
            room,
            InviteBiddersRequest(
                invitations=[InviteBidderItem(user_id=bidder.id, min_ats_score=400)]
            ),
            admin,
            b2b_db,
        )
        assert len(created) == 1
        assert created[0].status == B2BInvitationStatus.PENDING.value

    async def test_access_denied_without_invitation(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        bidder = await _make_user(b2b_db, phone="+962790000002")
        room = await _make_room(b2b_db, admin)

        inv = await b2b_service.check_access(room, bidder, b2b_db)
        assert inv is None

    async def test_access_denied_when_ats_too_low(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        low_ats_bidder = await _make_user(
            b2b_db, phone="+962790000003", ats_score=100
        )
        room = await _make_room(b2b_db, admin)

        await b2b_service.invite_bidders(
            room,
            InviteBiddersRequest(
                invitations=[
                    InviteBidderItem(user_id=low_ats_bidder.id, min_ats_score=400)
                ]
            ),
            admin,
            b2b_db,
        )

        inv = await b2b_service.check_access(room, low_ats_bidder, b2b_db)
        assert inv is None  # ATS below threshold

    async def test_access_denied_when_kyc_not_verified(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        unverified = await _make_user(
            b2b_db,
            phone="+962790000004",
            kyc=KYCStatus.NOT_STARTED,
        )
        room = await _make_room(b2b_db, admin)

        await b2b_service.invite_bidders(
            room,
            InviteBiddersRequest(
                invitations=[
                    InviteBidderItem(
                        user_id=unverified.id, min_kyc_level="verified"
                    )
                ]
            ),
            admin,
            b2b_db,
        )

        inv = await b2b_service.check_access(room, unverified, b2b_db)
        assert inv is None

    async def test_revoke_invitation_denies_access(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        bidder = await _make_user(b2b_db, phone="+962790000002")
        room = await _make_room(b2b_db, admin)

        created = await b2b_service.invite_bidders(
            room,
            InviteBiddersRequest(invitations=[InviteBidderItem(user_id=bidder.id)]),
            admin,
            b2b_db,
        )
        assert await b2b_service.check_access(room, bidder, b2b_db) is not None

        await b2b_service.revoke_invitation(room, created[0].id, admin, b2b_db)
        # Re-fetch room to get updated relationships
        room = await b2b_service.get_room(room.id, b2b_db)
        assert await b2b_service.check_access(room, bidder, b2b_db) is None


# ═══════════════════════════════════════════════════════════════════
# Bid submission
# ═══════════════════════════════════════════════════════════════════


class TestBidSubmission:
    async def test_submit_valid_bid(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        bidder = await _make_user(b2b_db, phone="+962790000002")
        room = await _make_room(b2b_db, admin)

        await b2b_service.invite_bidders(
            room,
            InviteBiddersRequest(invitations=[InviteBidderItem(user_id=bidder.id)]),
            admin,
            b2b_db,
        )

        bid = await b2b_service.submit_bid(
            room,
            bidder,
            SubmitBidRequest(amount=15000.50, notes="ready to pay", validity_days=30),
            b2b_db,
        )
        assert bid.amount == 1_500_050  # cents
        assert bid.submission_ref is not None
        assert bid.submission_ref.startswith("TND-")

    async def test_duplicate_bid_rejected(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        bidder = await _make_user(b2b_db, phone="+962790000002")
        room = await _make_room(b2b_db, admin)

        await b2b_service.invite_bidders(
            room,
            InviteBiddersRequest(invitations=[InviteBidderItem(user_id=bidder.id)]),
            admin,
            b2b_db,
        )

        await b2b_service.submit_bid(
            room, bidder, SubmitBidRequest(amount=15000, validity_days=30), b2b_db
        )

        with pytest.raises(b2b_service.DuplicateBidError):
            await b2b_service.submit_bid(
                room,
                bidder,
                SubmitBidRequest(amount=20000, validity_days=30),
                b2b_db,
            )

    async def test_bid_below_minimum_rejected(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        bidder = await _make_user(b2b_db, phone="+962790000002")
        room = await _make_room(b2b_db, admin, min_lot=1_000_000)  # 10K JOD

        with pytest.raises(b2b_service.MinBidError):
            await b2b_service.submit_bid(
                room,
                bidder,
                SubmitBidRequest(amount=5000.00, validity_days=30),  # 5K JOD
                b2b_db,
            )

    async def test_bid_after_deadline_rejected(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        bidder = await _make_user(b2b_db, phone="+962790000002")
        room = await _make_room(b2b_db, admin)

        # Force deadline in the past
        room.submission_deadline = datetime.now(timezone.utc) - timedelta(hours=1)
        await b2b_db.commit()

        with pytest.raises(b2b_service.TenderClosedError):
            await b2b_service.submit_bid(
                room,
                bidder,
                SubmitBidRequest(amount=15000, validity_days=30),
                b2b_db,
            )

    async def test_bid_on_closed_room_rejected(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        bidder = await _make_user(b2b_db, phone="+962790000002")
        room = await _make_room(b2b_db, admin)
        room.status = B2BRoomStatus.CANCELLED.value
        await b2b_db.commit()

        with pytest.raises(b2b_service.TenderClosedError):
            await b2b_service.submit_bid(
                room,
                bidder,
                SubmitBidRequest(amount=15000, validity_days=30),
                b2b_db,
            )


# ═══════════════════════════════════════════════════════════════════
# Sealed bid suppression + mobile response
# ═══════════════════════════════════════════════════════════════════


class TestMobileResponse:
    async def test_sealed_bids_hidden_before_announce(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        bidder1 = await _make_user(b2b_db, phone="+962790000002")
        bidder2 = await _make_user(b2b_db, phone="+962790000003")
        room = await _make_room(b2b_db, admin, sealed=True)

        # Invite + place bids
        await b2b_service.invite_bidders(
            room,
            InviteBiddersRequest(
                invitations=[
                    InviteBidderItem(user_id=bidder1.id),
                    InviteBidderItem(user_id=bidder2.id),
                ]
            ),
            admin,
            b2b_db,
        )
        await b2b_service.submit_bid(
            room, bidder1, SubmitBidRequest(amount=15000, validity_days=30), b2b_db
        )
        await b2b_service.submit_bid(
            room, bidder2, SubmitBidRequest(amount=18000, validity_days=30), b2b_db
        )

        room = await b2b_service.get_room(room.id, b2b_db)
        inv1 = await b2b_service.check_access(room, bidder1, b2b_db)
        resp = await b2b_service.get_room_for_bidder(room, bidder1, inv1, b2b_db)

        assert resp.access == "invited"
        assert resp.phase == "submitted"
        assert resp.sealed_notice is True
        assert resp.results == []  # sealed — no visible results
        assert resp.submission_ref is not None

    async def test_bids_visible_after_announce(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        bidder1 = await _make_user(b2b_db, phone="+962790000002")
        bidder2 = await _make_user(b2b_db, phone="+962790000003")
        room = await _make_room(b2b_db, admin, sealed=True)

        await b2b_service.invite_bidders(
            room,
            InviteBiddersRequest(
                invitations=[
                    InviteBidderItem(user_id=bidder1.id),
                    InviteBidderItem(user_id=bidder2.id),
                ]
            ),
            admin,
            b2b_db,
        )
        await b2b_service.submit_bid(
            room, bidder1, SubmitBidRequest(amount=15000, validity_days=30), b2b_db
        )
        winning = await b2b_service.submit_bid(
            room, bidder2, SubmitBidRequest(amount=18000, validity_days=30), b2b_db
        )

        room = await b2b_service.get_room(room.id, b2b_db)
        await b2b_service.announce_results(
            room, AnnounceResultsRequest(winner_bid_id=winning.id), admin, b2b_db
        )

        room = await b2b_service.get_room(room.id, b2b_db)
        inv2 = await b2b_service.check_access(room, bidder2, b2b_db)
        resp = await b2b_service.get_room_for_bidder(room, bidder2, inv2, b2b_db)

        assert resp.phase == "results"
        assert resp.bid_result == "won"
        # amount=18000 JOD → 1_800_000 cents → 18000.0 JOD display
        assert resp.winning_amount == 18000.0
        assert len(resp.results) == 2
        # Highest ranked first (amount DESC)
        assert resp.results[0].rank == 1
        assert resp.results[0].is_awarded is True

        inv1 = await b2b_service.check_access(room, bidder1, b2b_db)
        loser_resp = await b2b_service.get_room_for_bidder(
            room, bidder1, inv1, b2b_db
        )
        assert loser_resp.bid_result == "lost"

    async def test_uninvited_user_sees_denied(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        stranger = await _make_user(b2b_db, phone="+962790000099")
        room = await _make_room(b2b_db, admin)

        resp = await b2b_service.get_room_for_bidder(room, stranger, None, b2b_db)
        assert resp.access == "denied"


# ═══════════════════════════════════════════════════════════════════
# Results announcement
# ═══════════════════════════════════════════════════════════════════


class TestAnnounceResults:
    async def test_announce_marks_winner_and_transitions_status(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        bidder = await _make_user(b2b_db, phone="+962790000002")
        room = await _make_room(b2b_db, admin)

        await b2b_service.invite_bidders(
            room,
            InviteBiddersRequest(invitations=[InviteBidderItem(user_id=bidder.id)]),
            admin,
            b2b_db,
        )
        bid = await b2b_service.submit_bid(
            room, bidder, SubmitBidRequest(amount=15000, validity_days=30), b2b_db
        )

        room = await b2b_service.get_room(room.id, b2b_db)
        updated = await b2b_service.announce_results(
            room, AnnounceResultsRequest(winner_bid_id=bid.id), admin, b2b_db
        )

        assert updated.status == B2BRoomStatus.RESULTS_ANNOUNCED.value
        assert updated.results_announced_at is not None

        await b2b_db.refresh(bid)
        assert bid.is_winner is True

    async def test_announce_wrong_bid_id_raises(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        room = await _make_room(b2b_db, admin)

        with pytest.raises(ValueError, match="does not belong"):
            await b2b_service.announce_results(
                room,
                AnnounceResultsRequest(winner_bid_id=str(uuid4())),
                admin,
                b2b_db,
            )

    async def test_announce_after_already_announced_rejected(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        bidder = await _make_user(b2b_db, phone="+962790000002")
        room = await _make_room(b2b_db, admin)
        await b2b_service.invite_bidders(
            room,
            InviteBiddersRequest(invitations=[InviteBidderItem(user_id=bidder.id)]),
            admin,
            b2b_db,
        )
        bid = await b2b_service.submit_bid(
            room, bidder, SubmitBidRequest(amount=15000, validity_days=30), b2b_db
        )

        room = await b2b_service.get_room(room.id, b2b_db)
        await b2b_service.announce_results(
            room, AnnounceResultsRequest(winner_bid_id=bid.id), admin, b2b_db
        )

        room = await b2b_service.get_room(room.id, b2b_db)
        with pytest.raises(b2b_service.InvalidStatusError):
            await b2b_service.announce_results(
                room, AnnounceResultsRequest(winner_bid_id=bid.id), admin, b2b_db
            )


# ═══════════════════════════════════════════════════════════════════
# Analytics
# ═══════════════════════════════════════════════════════════════════


class TestAnalytics:
    async def test_analytics_with_bids(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        b1 = await _make_user(b2b_db, phone="+962790000002")
        b2 = await _make_user(b2b_db, phone="+962790000003")
        b3 = await _make_user(b2b_db, phone="+962790000004")
        room = await _make_room(b2b_db, admin, estimated=2_000_000)  # 20K JOD

        await b2b_service.invite_bidders(
            room,
            InviteBiddersRequest(
                invitations=[
                    InviteBidderItem(user_id=b1.id),
                    InviteBidderItem(user_id=b2.id),
                    InviteBidderItem(user_id=b3.id),
                ]
            ),
            admin,
            b2b_db,
        )
        # 2 of 3 bid
        await b2b_service.submit_bid(
            room, b1, SubmitBidRequest(amount=15000, validity_days=30), b2b_db
        )
        winner = await b2b_service.submit_bid(
            room, b2, SubmitBidRequest(amount=25000, validity_days=30), b2b_db
        )

        room = await b2b_service.get_room(room.id, b2b_db)
        await b2b_service.announce_results(
            room, AnnounceResultsRequest(winner_bid_id=winner.id), admin, b2b_db
        )

        room = await b2b_service.get_room(room.id, b2b_db)
        analytics = await b2b_service.get_room_analytics(room, b2b_db)

        assert analytics.invited_count == 3
        assert analytics.bid_count == 2
        assert abs(analytics.participation_rate - (2 / 3)) < 0.001
        assert analytics.min_bid_amount == 1_500_000
        assert analytics.max_bid_amount == 2_500_000
        assert analytics.avg_bid_amount == 2_000_000
        assert analytics.winner_amount == 2_500_000
        # Winner 25K / estimated 20K = 1.25
        assert analytics.price_vs_estimate_ratio == 1.25


# ═══════════════════════════════════════════════════════════════════
# CSV import
# ═══════════════════════════════════════════════════════════════════


class TestCsvImport:
    async def test_import_csv_creates_rooms(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        future = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()

        csv_content = (
            "tender_reference,client_name,submission_deadline,min_lot_amount,estimated_value,description,sealed\n"
            f"T-CSV-001,Client A,{future},1000000,5000000,First import,true\n"
            f"T-CSV-002,Client B,{future},2000000,8000000,Second import,false\n"
        ).encode("utf-8")

        result = await b2b_service.import_csv(csv_content, admin, b2b_db)

        assert result.created_count == 2
        assert len(result.created_ids) == 2
        assert result.errors == []

    async def test_import_csv_rejects_below_minimum(self, b2b_db):
        admin = await _make_user(b2b_db, phone="+962790000001", role=UserRole.ADMIN)
        future = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()

        csv_content = (
            "tender_reference,client_name,submission_deadline,min_lot_amount,estimated_value,description,sealed\n"
            f"T-LOW,Client A,{future},500000,1000000,Below min,true\n"
        ).encode("utf-8")

        result = await b2b_service.import_csv(csv_content, admin, b2b_db)
        assert result.created_count == 0
        assert len(result.errors) == 1
        assert "below 10K JOD" in result.errors[0]
