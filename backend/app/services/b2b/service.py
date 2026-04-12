"""B2B Tender Rooms service layer — FR-B2B-001..010, SDD §5.12.

Responsibilities
----------------
1. Room CRUD (admin) with audit logging
2. Invitation management (pre-qualification via ATS + KYC)
3. Sealed bid submission (append-only, one per bidder)
4. Results announcement (sets winner, moves to results_announced)
5. Mobile-facing GET /tenders/{id} response (sealed bid suppression)
6. Analytics (participation, avg bid, price vs estimate)
7. Compliance PDF export (Jinja2 → WeasyPrint)
8. CSV catalogue import

Sealed bid rule (FR-B2B-004)
----------------------------
Bid amounts are plaintext in DB (compliance audit requirement).
They are suppressed in the API response layer when:
    room.sealed=True AND room.status != "results_announced"
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.admin.service import _audit
from app.services.auth.models import KYCStatus, User
from app.services.b2b.models import (
    B2BBid,
    B2BInvitation,
    B2BInvitationStatus,
    B2BRoom,
    B2BRoomStatus,
)
from app.services.b2b.schemas import (
    AdminBidItem,
    AdminInvitationItem,
    AdminRoomDetail,
    AdminRoomListItem,
    AdminRoomListResponse,
    AnnounceResultsRequest,
    BidSubmittedResponse,
    CsvImportResponse,
    InviteBiddersRequest,
    RoomAnalytics,
    RoomUpdateRequest,
    SubmitBidRequest,
    TenderDocument,
    TenderRoomCreateRequest,
    TenderRoomResponse,
    TenderResultItem,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  Custom exceptions
# ═══════════════════════════════════════════════════════════════════


class TenderNotFoundError(Exception):
    """Room does not exist."""


class TenderClosedError(Exception):
    """Submission deadline passed or room status != open."""


class NotInvitedError(Exception):
    """User is not invited (or invitation revoked) for this room."""


class PreQualificationError(Exception):
    """User does not meet pre-qualification thresholds (ATS or KYC)."""


class DuplicateBidError(Exception):
    """User already submitted a bid for this room."""


class MinBidError(Exception):
    """Bid amount below min_lot_amount."""


class InvalidStatusError(Exception):
    """Operation not allowed in current room status."""


# ═══════════════════════════════════════════════════════════════════
#  Room CRUD (admin)
# ═══════════════════════════════════════════════════════════════════


async def create_room(
    data: TenderRoomCreateRequest,
    admin: User,
    db: AsyncSession,
) -> B2BRoom:
    """Create a private tender room.

    FR-B2B-001: admin-only.
    FR-B2B-002: min lot 10K JOD = 1,000,000 cents (enforced by schema).
    FR-B2B-006: (subscription billing hook — deferred to billing service)
    """
    room = B2BRoom(
        id=str(uuid4()),
        client_name=data.client_name,
        client_name_ar=data.client_name_ar,
        tender_reference=data.tender_reference,
        description=data.description,
        submission_deadline=data.submission_deadline,
        sealed=data.sealed,
        min_lot_amount=data.min_lot_amount,
        estimated_value=data.estimated_value,
        client_logo_url=data.client_logo_url,
        documents=data.documents,
        status=B2BRoomStatus.OPEN.value,
        created_by=admin.id,
    )
    db.add(room)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(
            f"tender_reference '{data.tender_reference}' already exists"
        ) from exc

    await _audit(
        admin.id,
        "b2b.room.create",
        db,
        entity_type="b2b_room",
        entity_id=room.id,
        after_state={
            "tender_reference": room.tender_reference,
            "client_name": room.client_name,
            "min_lot_amount": room.min_lot_amount,
            "sealed": room.sealed,
        },
    )
    await db.commit()
    await db.refresh(room)
    return room


async def get_room(room_id: str, db: AsyncSession) -> B2BRoom | None:
    """Fetch room with bids + invitations eagerly loaded."""
    q = (
        select(B2BRoom)
        .where(B2BRoom.id == room_id)
        .options(
            selectinload(B2BRoom.bids),
            selectinload(B2BRoom.invitations),
        )
    )
    result = await db.execute(q)
    return result.scalar_one_or_none()


async def list_rooms(
    db: AsyncSession,
    *,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> AdminRoomListResponse:
    """Paginated admin room list with bid/invitation counts."""
    per_page = min(per_page, 100)
    offset = (page - 1) * per_page

    q = select(B2BRoom)
    if status:
        q = q.where(B2BRoom.status == status)

    # Count
    count_q = select(func.count(B2BRoom.id))
    if status:
        count_q = count_q.where(B2BRoom.status == status)
    total = (await db.execute(count_q)).scalar() or 0

    q = q.order_by(B2BRoom.created_at.desc()).offset(offset).limit(per_page)
    q = q.options(
        selectinload(B2BRoom.bids),
        selectinload(B2BRoom.invitations),
    )
    rows = (await db.execute(q)).scalars().all()

    items = [
        AdminRoomListItem(
            id=r.id,
            client_name=r.client_name,
            client_name_ar=r.client_name_ar,
            tender_reference=r.tender_reference,
            status=r.status,
            submission_deadline=r.submission_deadline,
            sealed=r.sealed,
            min_lot_amount=r.min_lot_amount,
            estimated_value=r.estimated_value,
            bid_count=len(r.bids),
            invitation_count=len(r.invitations),
            created_at=r.created_at,
        )
        for r in rows
    ]
    return AdminRoomListResponse(
        items=items, total=total, page=page, per_page=per_page
    )


async def update_room(
    room: B2BRoom,
    data: RoomUpdateRequest,
    admin: User,
    db: AsyncSession,
) -> B2BRoom:
    """Patch mutable fields (admin only)."""
    before = {
        "status": room.status,
        "submission_deadline": room.submission_deadline.isoformat() if room.submission_deadline else None,
        "description": room.description,
        "estimated_value": room.estimated_value,
    }
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(room, field, value)

    await _audit(
        admin.id,
        "b2b.room.update",
        db,
        entity_type="b2b_room",
        entity_id=room.id,
        before_state=before,
        after_state=update_data,
    )
    await db.commit()
    await db.refresh(room)
    return room


# ═══════════════════════════════════════════════════════════════════
#  Invitations
# ═══════════════════════════════════════════════════════════════════


async def invite_bidders(
    room: B2BRoom,
    data: InviteBiddersRequest,
    admin: User,
    db: AsyncSession,
) -> list[B2BInvitation]:
    """Create invitations for multiple users (idempotent on existing).

    FR-B2B-003: pre-qualification thresholds stored per invitation.
    """
    created: list[B2BInvitation] = []

    # Pre-load existing invitations to avoid duplicates
    existing_q = select(B2BInvitation).where(B2BInvitation.room_id == room.id)
    existing = {
        inv.user_id: inv
        for inv in (await db.execute(existing_q)).scalars().all()
    }

    for item in data.invitations:
        if item.user_id in existing:
            # Re-activate if revoked; otherwise skip
            inv = existing[item.user_id]
            if inv.status == B2BInvitationStatus.REVOKED.value:
                inv.status = B2BInvitationStatus.PENDING.value
                inv.invited_at = datetime.now(timezone.utc)
                inv.responded_at = None
            continue

        inv = B2BInvitation(
            id=str(uuid4()),
            room_id=room.id,
            user_id=item.user_id,
            invited_by=admin.id,
            status=B2BInvitationStatus.PENDING.value,
            min_ats_score=item.min_ats_score,
            min_kyc_level=item.min_kyc_level,
        )
        db.add(inv)
        created.append(inv)

    await _audit(
        admin.id,
        "b2b.invitations.create",
        db,
        entity_type="b2b_room",
        entity_id=room.id,
        after_state={"invited_user_ids": [i.user_id for i in data.invitations]},
    )
    await db.commit()

    # Dispatch notifications (best-effort)
    try:
        from app.tasks.notification import send_b2b_invitation_notification
        for inv in created:
            send_b2b_invitation_notification.delay(room.id, inv.user_id)
    except Exception:
        logger.debug("b2b invitation notification dispatch skipped")

    return created


async def revoke_invitation(
    room: B2BRoom,
    invitation_id: str,
    admin: User,
    db: AsyncSession,
) -> B2BInvitation:
    """Revoke a pending invitation — user loses access to the room."""
    inv = await db.get(B2BInvitation, invitation_id)
    if inv is None or inv.room_id != room.id:
        raise ValueError("invitation not found for this room")

    inv.status = B2BInvitationStatus.REVOKED.value
    inv.responded_at = datetime.now(timezone.utc)

    await _audit(
        admin.id,
        "b2b.invitation.revoke",
        db,
        entity_type="b2b_invitation",
        entity_id=invitation_id,
        after_state={"room_id": room.id, "user_id": inv.user_id},
    )
    await db.commit()
    await db.refresh(inv)
    return inv


async def check_access(
    room: B2BRoom,
    user: User,
    db: AsyncSession,
) -> B2BInvitation | None:
    """Return the active invitation for this user, or None if denied.

    Denies if:
      - no invitation exists
      - invitation is revoked/declined
      - user's ATS < min_ats_score
      - user's KYC status below required level
    """
    q = select(B2BInvitation).where(
        and_(
            B2BInvitation.room_id == room.id,
            B2BInvitation.user_id == user.id,
        )
    )
    inv = (await db.execute(q)).scalar_one_or_none()
    if inv is None:
        return None

    if inv.status in (
        B2BInvitationStatus.REVOKED.value,
        B2BInvitationStatus.DECLINED.value,
    ):
        return None

    # Pre-qualification checks
    if inv.min_ats_score is not None and user.ats_score < inv.min_ats_score:
        return None

    if inv.min_kyc_level is not None:
        user_kyc = (
            user.kyc_status.value
            if hasattr(user.kyc_status, "value")
            else user.kyc_status
        )
        if inv.min_kyc_level == "verified" and user_kyc != "verified":
            return None

    return inv


# ═══════════════════════════════════════════════════════════════════
#  Bid submission
# ═══════════════════════════════════════════════════════════════════


def _generate_submission_ref() -> str:
    """Short human-friendly submission reference."""
    return f"TND-{uuid4().hex[:10].upper()}"


async def submit_bid(
    room: B2BRoom,
    user: User,
    data: SubmitBidRequest,
    db: AsyncSession,
) -> B2BBid:
    """Submit a sealed bid — append-only, one per bidder.

    Validates:
      - room status == open
      - submission_deadline not passed
      - user has active invitation (access check via dependency)
      - no existing bid from this user
      - amount >= min_lot_amount
    """
    # Room state
    if room.status != B2BRoomStatus.OPEN.value:
        raise TenderClosedError(f"room status is {room.status}")

    now = datetime.now(timezone.utc)
    deadline = room.submission_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline <= now:
        raise TenderClosedError("submission deadline has passed")

    # Convert JOD float to cents integer
    amount_cents = int(round(data.amount * 100))

    if amount_cents < room.min_lot_amount:
        raise MinBidError(
            f"amount {amount_cents} below min_lot_amount {room.min_lot_amount}"
        )

    # Duplicate check
    dup_q = select(B2BBid.id).where(
        and_(B2BBid.room_id == room.id, B2BBid.bidder_id == user.id)
    )
    if (await db.execute(dup_q)).scalar_one_or_none():
        raise DuplicateBidError("user already submitted a bid for this room")

    bid = B2BBid(
        id=str(uuid4()),
        room_id=room.id,
        bidder_id=user.id,
        amount=amount_cents,
        notes=data.notes or None,
        validity_days=data.validity_days,
        attachments=[{"path": p} for p in data.attachment_paths],
        submission_ref=_generate_submission_ref(),
    )
    db.add(bid)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateBidError("duplicate bid") from exc

    await db.commit()
    await db.refresh(bid)
    return bid


def bid_submitted_response(bid: B2BBid) -> BidSubmittedResponse:
    return BidSubmittedResponse(
        submitted_at=bid.submitted_at.isoformat(),
        submission_ref=bid.submission_ref or "",
    )


# ═══════════════════════════════════════════════════════════════════
#  Results announcement
# ═══════════════════════════════════════════════════════════════════


async def announce_results(
    room: B2BRoom,
    data: AnnounceResultsRequest,
    admin: User,
    db: AsyncSession,
) -> B2BRoom:
    """Mark the winning bid and move room to results_announced.

    FR-B2B-005: once announced, all bids become visible to invited users.
    """
    if room.status not in (
        B2BRoomStatus.OPEN.value,
        B2BRoomStatus.CLOSED.value,
    ):
        raise InvalidStatusError(
            f"cannot announce results in status {room.status}"
        )

    # Verify winner bid belongs to this room
    winner = await db.get(B2BBid, data.winner_bid_id)
    if winner is None or winner.room_id != room.id:
        raise ValueError("winner_bid_id does not belong to this room")

    # Clear any previous winner flags
    prev_q = select(B2BBid).where(
        and_(B2BBid.room_id == room.id, B2BBid.is_winner.is_(True))
    )
    for prev in (await db.execute(prev_q)).scalars().all():
        prev.is_winner = False

    winner.is_winner = True
    room.status = B2BRoomStatus.RESULTS_ANNOUNCED.value
    room.results_announced_at = datetime.now(timezone.utc)

    await _audit(
        admin.id,
        "b2b.results.announce",
        db,
        entity_type="b2b_room",
        entity_id=room.id,
        after_state={"winner_bid_id": winner.id, "winner_amount": winner.amount},
    )
    await db.commit()
    await db.refresh(room)

    # Notify all bidders (best-effort)
    try:
        from app.tasks.notification import send_b2b_results_announcement
        send_b2b_results_announcement.delay(room.id)
    except Exception:
        logger.debug("b2b results announcement notification dispatch skipped")

    return room


# ═══════════════════════════════════════════════════════════════════
#  Bidder-facing mobile response builder
# ═══════════════════════════════════════════════════════════════════


def _phase_for(room: B2BRoom, user_bid: B2BBid | None) -> str:
    """Derive mobile screen phase from room state + user bid presence."""
    if room.status == B2BRoomStatus.RESULTS_ANNOUNCED.value:
        return "results"
    if user_bid is not None:
        return "submitted"
    return "open"


def _results_visible(room: B2BRoom) -> bool:
    """Sealed bid rule (FR-B2B-004): bids hidden unless results announced."""
    if room.status == B2BRoomStatus.RESULTS_ANNOUNCED.value:
        return True
    return not room.sealed


async def get_room_for_bidder(
    room: B2BRoom,
    user: User,
    invitation: B2BInvitation | None,
    db: AsyncSession,
) -> TenderRoomResponse:
    """Build the mobile GET /tenders/{id} response.

    Honours sealed bid rule — amounts hidden until status=results_announced.
    """
    # Fetch this bidder's own bid (if any)
    own_q = select(B2BBid).where(
        and_(B2BBid.room_id == room.id, B2BBid.bidder_id == user.id)
    )
    own_bid = (await db.execute(own_q)).scalar_one_or_none()

    access = "invited" if invitation is not None else "denied"
    phase = _phase_for(room, own_bid)

    docs = [
        TenderDocument(
            name=d.get("name", ""),
            size=d.get("size", ""),
            url=d.get("url", ""),
        )
        for d in (room.documents or [])
    ]

    submitted_at = own_bid.submitted_at.isoformat() if own_bid else None
    submission_ref = own_bid.submission_ref if own_bid else None

    # Results (only when visible)
    results: list[TenderResultItem] = []
    bid_result = "pending"
    winning_amount: float | None = None

    if _results_visible(room):
        bids_q = (
            select(B2BBid)
            .where(B2BBid.room_id == room.id)
            .order_by(B2BBid.amount.desc())
        )
        ordered = (await db.execute(bids_q)).scalars().all()
        for rank, bid in enumerate(ordered, start=1):
            results.append(
                TenderResultItem(
                    rank=rank,
                    amount=bid.amount / 100.0,
                    is_awarded=bid.is_winner,
                    is_you=(bid.bidder_id == user.id),
                )
            )
            if bid.is_winner:
                winning_amount = bid.amount / 100.0

        if own_bid is not None and winning_amount is not None:
            bid_result = "won" if own_bid.is_winner else "lost"

    return TenderRoomResponse(
        access=access,
        phase=phase,
        client_name=room.client_name,
        client_logo_url=room.client_logo_url,
        reference=room.tender_reference,
        deadline=room.submission_deadline.isoformat(),
        sealed_notice=bool(room.sealed),
        documents=docs,
        submitted_at=submitted_at,
        submission_ref=submission_ref,
        bid_result=bid_result,
        results=results,
        winning_amount=winning_amount,
    )


# ═══════════════════════════════════════════════════════════════════
#  Admin room detail builder
# ═══════════════════════════════════════════════════════════════════


async def build_admin_room_detail(
    room: B2BRoom,
    db: AsyncSession,
) -> AdminRoomDetail:
    """Build full admin detail view — always shows amounts regardless of sealed flag."""
    # Eager-load bidders for display names
    bidder_ids = [b.bidder_id for b in room.bids]
    invitee_ids = [i.user_id for i in room.invitations]
    all_user_ids = list(set(bidder_ids + invitee_ids))

    users_by_id: dict[str, User] = {}
    if all_user_ids:
        uq = select(User).where(User.id.in_(all_user_ids))
        for u in (await db.execute(uq)).scalars().all():
            users_by_id[u.id] = u

    bids_sorted = sorted(room.bids, key=lambda b: b.amount, reverse=True)
    bid_items = [
        AdminBidItem(
            id=b.id,
            bidder_id=b.bidder_id,
            bidder_name=(users_by_id.get(b.bidder_id).full_name
                         if users_by_id.get(b.bidder_id) else None),
            amount=b.amount,
            notes=b.notes,
            validity_days=b.validity_days,
            is_winner=b.is_winner,
            submitted_at=b.submitted_at,
            submission_ref=b.submission_ref,
        )
        for b in bids_sorted
    ]

    inv_items = [
        AdminInvitationItem(
            id=i.id,
            user_id=i.user_id,
            user_name=(users_by_id.get(i.user_id).full_name
                       if users_by_id.get(i.user_id) else None),
            status=i.status,
            min_ats_score=i.min_ats_score,
            min_kyc_level=i.min_kyc_level,
            invited_at=i.invited_at,
            responded_at=i.responded_at,
        )
        for i in room.invitations
    ]

    return AdminRoomDetail(
        id=room.id,
        client_name=room.client_name,
        client_name_ar=room.client_name_ar,
        tender_reference=room.tender_reference,
        description=room.description,
        status=room.status,
        submission_deadline=room.submission_deadline,
        results_announced_at=room.results_announced_at,
        sealed=room.sealed,
        min_lot_amount=room.min_lot_amount,
        estimated_value=room.estimated_value,
        client_logo_url=room.client_logo_url,
        documents=room.documents or [],
        created_at=room.created_at,
        bids=bid_items,
        invitations=inv_items,
    )


# ═══════════════════════════════════════════════════════════════════
#  Analytics
# ═══════════════════════════════════════════════════════════════════


async def get_room_analytics(room: B2BRoom, db: AsyncSession) -> RoomAnalytics:
    """Compute participation rate, avg/min/max bid, price vs estimate."""
    invited_count = len(room.invitations)
    bid_count = len(room.bids)

    participation = (bid_count / invited_count) if invited_count > 0 else 0.0

    amounts = [b.amount for b in room.bids]
    avg_amount = int(sum(amounts) / len(amounts)) if amounts else None
    min_amount = min(amounts) if amounts else None
    max_amount = max(amounts) if amounts else None

    winner = next((b for b in room.bids if b.is_winner), None)
    winner_amount = winner.amount if winner else None
    ratio: float | None = None
    if winner_amount is not None and room.estimated_value and room.estimated_value > 0:
        ratio = round(winner_amount / room.estimated_value, 4)

    time_to_close: float | None = None
    if room.results_announced_at is not None:
        created = room.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        announced = room.results_announced_at
        if announced.tzinfo is None:
            announced = announced.replace(tzinfo=timezone.utc)
        time_to_close = round(
            (announced - created).total_seconds() / 3600.0, 2
        )

    return RoomAnalytics(
        room_id=room.id,
        invited_count=invited_count,
        bid_count=bid_count,
        participation_rate=round(participation, 4),
        avg_bid_amount=avg_amount,
        min_bid_amount=min_amount,
        max_bid_amount=max_amount,
        price_vs_estimate_ratio=ratio,
        winner_amount=winner_amount,
        time_to_close_hours=time_to_close,
    )


# ═══════════════════════════════════════════════════════════════════
#  PDF generation (WeasyPrint + Jinja2)
# ═══════════════════════════════════════════════════════════════════


def _render_template(template_name: str, context: dict) -> str:
    """Render a Jinja2 template from services/b2b/templates/."""
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader, select_autoescape

    templates_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    return env.get_template(template_name).render(**context)


def _html_to_pdf(html: str) -> bytes:
    """Convert HTML to PDF bytes using WeasyPrint (falls back to HTML bytes in tests)."""
    try:
        from weasyprint import HTML  # type: ignore

        return HTML(string=html).write_pdf()
    except Exception as exc:  # pragma: no cover - dev/test fallback
        logger.warning("WeasyPrint unavailable (%s) — returning HTML as bytes", exc)
        return html.encode("utf-8")


async def generate_compliance_pdf(room: B2BRoom, db: AsyncSession) -> bytes:
    """Compliance report — full bid table, winner highlight, audit trail."""
    detail = await build_admin_room_detail(room, db)
    context = {
        "room": detail,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    html = _render_template("compliance_report.html", context)
    return _html_to_pdf(html)


async def generate_award_letter_pdf(
    room: B2BRoom,
    bid_id: str,
    db: AsyncSession,
) -> bytes:
    """Formal award letter for a winning bid."""
    bid = await db.get(B2BBid, bid_id)
    if bid is None or bid.room_id != room.id:
        raise ValueError("bid not found for this room")

    bidder = await db.get(User, bid.bidder_id)
    context = {
        "room": room,
        "bid": bid,
        "bidder": bidder,
        "bid_amount_jod": bid.amount / 100.0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    html = _render_template("award_letter.html", context)
    return _html_to_pdf(html)


# ═══════════════════════════════════════════════════════════════════
#  CSV catalogue import (FR-B2B-008)
# ═══════════════════════════════════════════════════════════════════


async def import_csv(
    csv_bytes: bytes,
    admin: User,
    db: AsyncSession,
) -> CsvImportResponse:
    """Bulk create rooms from CSV.

    Expected columns: tender_reference, client_name, submission_deadline (ISO),
    min_lot_amount (cents), estimated_value, description, sealed (true/false).
    """
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    created_ids: list[str] = []
    errors: list[str] = []

    for idx, row in enumerate(reader, start=2):  # header = line 1
        try:
            deadline_raw = (row.get("submission_deadline") or "").strip()
            deadline = datetime.fromisoformat(deadline_raw.replace("Z", "+00:00"))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)

            min_lot = int(row.get("min_lot_amount") or 1_000_000)
            if min_lot < 1_000_000:
                raise ValueError("min_lot_amount below 10K JOD")

            estimated = row.get("estimated_value")
            estimated_int = int(estimated) if estimated else None

            sealed_raw = (row.get("sealed") or "true").strip().lower()
            sealed = sealed_raw in ("true", "1", "yes", "y")

            client_name = (row.get("client_name") or "").strip()
            tender_reference = (row.get("tender_reference") or "").strip()
            if not client_name or not tender_reference:
                raise ValueError("client_name and tender_reference are required")

            room = B2BRoom(
                id=str(uuid4()),
                client_name=client_name,
                tender_reference=tender_reference,
                description=(row.get("description") or None),
                submission_deadline=deadline,
                sealed=sealed,
                min_lot_amount=min_lot,
                estimated_value=estimated_int,
                documents=[],
                status=B2BRoomStatus.OPEN.value,
                created_by=admin.id,
            )

            # Savepoint so a failing INSERT (e.g. unique violation) rolls
            # back this row only, leaving the outer session usable for
            # subsequent rows.
            async with db.begin_nested():
                db.add(room)
                await db.flush()
            created_ids.append(room.id)
        except Exception as exc:
            errors.append(f"row {idx}: {exc}")

    if created_ids:
        await _audit(
            admin.id,
            "b2b.import_csv",
            db,
            entity_type="b2b_room",
            entity_id=None,
            after_state={"created_count": len(created_ids)},
        )
        await db.commit()

    return CsvImportResponse(
        created_count=len(created_ids),
        created_ids=created_ids,
        errors=errors,
    )
