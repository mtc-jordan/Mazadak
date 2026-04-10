"""Auction request/response schemas — SDD §5.4."""

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
    starts_at: str
    ends_at: str
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
    created_at: str

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
    ends_at: str | None = None
    winner_name: str | None = None
    is_live: bool = False


class MyAuctionsResponse(BaseModel):
    active: list[MyAuctionItem] = []
    ended: list[MyAuctionItem] = []
    won: list[MyAuctionItem] = []


class AuctionRoomState(BaseModel):
    """WebSocket current_state event payload."""
    auction_id: str
    current_price: float
    status: str
    bid_count: int
    watcher_count: int
    extension_count: int
    last_bidder: str | None = None
