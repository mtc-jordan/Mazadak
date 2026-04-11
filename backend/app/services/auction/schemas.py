"""Auction request/response schemas — SDD §5.4."""

from datetime import datetime

from pydantic import BaseModel, Field


class AuctionCreateRequest(BaseModel):
    listing_id: str
    starts_at: str  # ISO 8601
    ends_at: str
    min_increment: float = Field(default=25.0, gt=0)


class AuctionOut(BaseModel):
    id: str
    listing_id: str
    status: str
    starts_at: datetime
    ends_at: datetime
    current_price: float
    min_increment: float
    bid_count: int
    extension_count: int
    winner_id: str | None = None
    final_price: float | None = None
    reserve_met: bool | None = None

    model_config = {"from_attributes": True}


class PlaceBidRequest(BaseModel):
    amount: float = Field(..., gt=0)


class BidOut(BaseModel):
    id: str
    auction_id: str
    user_id: str
    amount: float
    currency: str
    is_proxy: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class BidAcceptedResponse(BaseModel):
    status: str  # ACCEPTED
    bid: BidOut
    new_price: float


class BidRejectedResponse(BaseModel):
    status: str  # REJECTED
    reason: str  # BID_TOO_LOW | AUCTION_NOT_ACTIVE | SELLER_CANNOT_BID | BIDDER_BANNED


class ProxyBidRequest(BaseModel):
    max_amount: float = Field(..., gt=0)


class MyAuctionItem(BaseModel):
    id: str
    listing_id: str
    title_ar: str
    title_en: str | None = None
    image_url: str = ""
    starting_price: float
    current_price: float
    currency: str = "JOD"
    bid_count: int = 0
    status: str
    ends_at: datetime | None = None
    winner_name: str | None = None
    is_live: bool = False


class MyAuctionsResponse(BaseModel):
    active: list[MyAuctionItem] = []
    ended: list[MyAuctionItem] = []
    won: list[MyAuctionItem] = []


class AuctionListItem(BaseModel):
    """Public auction card for browse/home screen."""
    id: str
    listing_id: str
    title_ar: str
    title_en: str | None = None
    image_url: str = ""
    category_id: int
    condition: str
    starting_price: int
    current_price: float
    currency: str = "JOD"
    min_increment: float
    bid_count: int = 0
    status: str
    starts_at: datetime
    ends_at: datetime
    is_charity: bool = False
    is_certified: bool = False
    location_city: str | None = None
    location_country: str = "JO"


class AuctionListResponse(BaseModel):
    data: list[AuctionListItem]
    total_count: int
    limit: int
    offset: int


class AuctionRoomState(BaseModel):
    """WebSocket current_state event payload."""
    auction_id: str
    current_price: float
    status: str
    bid_count: int
    watcher_count: int
    extension_count: int
    last_bidder: str | None = None
