"""B2B Tender Rooms — FastAPI endpoints.

Two routers:
  - `router`       (prefix `/tenders`)       — bidder-facing, matches mobile contract
  - `admin_router` (prefix `/admin/tenders`) — admin management (require_role)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.types import UUIDPath
from app.services.auth.dependencies import get_current_user, require_role
from app.services.auth.models import User
from app.services.b2b import service
from app.services.b2b.dependencies import (
    get_tender_or_404,
    require_tender_access,
)
from app.services.b2b.models import B2BInvitation, B2BRoom
from app.services.b2b.schemas import (
    AdminRoomDetail,
    AdminRoomListResponse,
    AnnounceResultsRequest,
    BidSubmittedResponse,
    CsvImportResponse,
    InviteBiddersRequest,
    RoomAnalytics,
    RoomUpdateRequest,
    SubmitBidRequest,
    TenderRoomCreateRequest,
    TenderRoomResponse,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  Bidder-facing router — matches mobile tender_room_screen.dart
# ═══════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/tenders", tags=["tenders"])


@router.get("/{tender_id}", response_model=TenderRoomResponse)
async def get_tender_room(
    tender_id: UUIDPath,
    room: B2BRoom = Depends(get_tender_or_404),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenderRoomResponse:
    """Mobile GET /tenders/{id}.

    Returns the room state filtered for this bidder.
    `access="denied"` when user is not invited — mobile renders a pre-qual CTA.
    Sealed bid results are hidden until the room is `results_announced`.
    """
    invitation = await service.check_access(room, user, db)
    return await service.get_room_for_bidder(room, user, invitation, db)


@router.post(
    "/{tender_id}/bids",
    response_model=BidSubmittedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_tender_bid(
    tender_id: UUIDPath,
    body: SubmitBidRequest,
    access: tuple[B2BRoom, User, B2BInvitation] = Depends(require_tender_access),
    db: AsyncSession = Depends(get_db),
) -> BidSubmittedResponse:
    """Mobile POST /tenders/{id}/bids — one sealed bid per user, append-only."""
    room, user, _inv = access
    try:
        bid = await service.submit_bid(room, user, body, db)
    except service.TenderClosedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TENDER_CLOSED",
                "message_en": str(exc),
                "message_ar": "غرفة المناقصة مغلقة",
            },
        ) from exc
    except service.DuplicateBidError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_BID",
                "message_en": "You have already submitted a bid for this tender",
                "message_ar": "لقد قدمت عرضًا بالفعل لهذه المناقصة",
            },
        ) from exc
    except service.MinBidError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "BID_BELOW_MINIMUM",
                "message_en": str(exc),
                "message_ar": "مبلغ العرض أقل من الحد الأدنى",
            },
        ) from exc

    return service.bid_submitted_response(bid)


# ═══════════════════════════════════════════════════════════════════
#  Admin router
# ═══════════════════════════════════════════════════════════════════

admin_router = APIRouter(prefix="/admin/tenders", tags=["admin-tenders"])

_admin = require_role("admin", "superadmin")


@admin_router.get("/", response_model=AdminRoomListResponse)
async def admin_list_rooms(
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern=r"^(open|closed|cancelled|results_announced)$",
    ),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    _admin_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminRoomListResponse:
    return await service.list_rooms(
        db, status=status_filter, page=page, per_page=per_page
    )


@admin_router.post("/", response_model=AdminRoomDetail, status_code=status.HTTP_201_CREATED)
async def admin_create_room(
    body: TenderRoomCreateRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminRoomDetail:
    try:
        room = await service.create_room(body, admin, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "DUPLICATE_REFERENCE", "message_en": str(exc)},
        ) from exc

    # Re-fetch with relationships for detail builder
    full = await service.get_room(room.id, db)
    return await service.build_admin_room_detail(full, db)


@admin_router.get("/{room_id}", response_model=AdminRoomDetail)
async def admin_get_room(
    room_id: UUIDPath,
    room: B2BRoom = Depends(get_tender_or_404),
    _admin_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminRoomDetail:
    return await service.build_admin_room_detail(room, db)


@admin_router.patch("/{room_id}", response_model=AdminRoomDetail)
async def admin_update_room(
    room_id: UUIDPath,
    body: RoomUpdateRequest,
    room: B2BRoom = Depends(get_tender_or_404),
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminRoomDetail:
    await service.update_room(room, body, admin, db)
    full = await service.get_room(room.id, db)
    return await service.build_admin_room_detail(full, db)


@admin_router.post("/{room_id}/invite", status_code=status.HTTP_201_CREATED)
async def admin_invite_bidders(
    room_id: UUIDPath,
    body: InviteBiddersRequest,
    room: B2BRoom = Depends(get_tender_or_404),
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    created = await service.invite_bidders(room, body, admin, db)
    return {"created": len(created), "invitation_ids": [i.id for i in created]}


@admin_router.delete("/{room_id}/invitations/{invitation_id}")
async def admin_revoke_invitation(
    room_id: UUIDPath,
    invitation_id: UUIDPath,
    room: B2BRoom = Depends(get_tender_or_404),
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        inv = await service.revoke_invitation(room, invitation_id, admin, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "INVITATION_NOT_FOUND", "message_en": str(exc)},
        ) from exc
    return {"invitation_id": inv.id, "status": inv.status}


@admin_router.post("/{room_id}/announce", response_model=AdminRoomDetail)
async def admin_announce_results(
    room_id: UUIDPath,
    body: AnnounceResultsRequest,
    room: B2BRoom = Depends(get_tender_or_404),
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminRoomDetail:
    try:
        await service.announce_results(room, body, admin, db)
    except service.InvalidStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_STATUS", "message_en": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_WINNER", "message_en": str(exc)},
        ) from exc

    full = await service.get_room(room.id, db)
    return await service.build_admin_room_detail(full, db)


@admin_router.get("/{room_id}/analytics", response_model=RoomAnalytics)
async def admin_room_analytics(
    room_id: UUIDPath,
    room: B2BRoom = Depends(get_tender_or_404),
    _admin_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> RoomAnalytics:
    return await service.get_room_analytics(room, db)


@admin_router.get("/{room_id}/export/compliance-pdf")
async def admin_export_compliance_pdf(
    room_id: UUIDPath,
    room: B2BRoom = Depends(get_tender_or_404),
    _admin_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    pdf = await service.generate_compliance_pdf(room, db)
    filename = f"tender_{room.tender_reference}_compliance.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@admin_router.get("/{room_id}/export/award-letter/{bid_id}")
async def admin_export_award_letter(
    room_id: UUIDPath,
    bid_id: UUIDPath,
    room: B2BRoom = Depends(get_tender_or_404),
    _admin_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        pdf = await service.generate_award_letter_pdf(room, bid_id, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "BID_NOT_FOUND", "message_en": str(exc)},
        ) from exc

    filename = f"tender_{room.tender_reference}_award_{bid_id[:8]}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@admin_router.post("/import-csv", response_model=CsvImportResponse)
async def admin_import_csv(
    file: UploadFile = File(...),
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> CsvImportResponse:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_FILE", "message_en": "CSV file required"},
        )
    contents = await file.read()
    return await service.import_csv(contents, admin, db)
