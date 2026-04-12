"""
Aramex shipping integration — P1-8.

Provides:
  create_shipment(escrow, seller_address, buyer_address) -> ShipmentResult
  track_shipment(tracking_number) -> TrackingResult
  generate_label_pdf(tracking_number) -> bytes

Uses Aramex SOAP/JSON API v2:
  - CreateShipments for label generation
  - TrackShipments for tracking updates

Fallback: if Aramex creds not configured, returns a mock shipment
for local development/testing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Address:
    line1: str
    line2: str = ""
    city: str = "Amman"
    state: str = ""
    postal_code: str = ""
    country_code: str = "JO"
    contact_name: str = ""
    phone: str = ""
    email: str = ""


@dataclass
class ShipmentResult:
    success: bool
    tracking_number: str = ""
    label_url: str = ""
    shipment_id: str = ""
    error: str = ""


@dataclass
class TrackingEvent:
    timestamp: datetime
    location: str
    description: str
    code: str


@dataclass
class TrackingResult:
    success: bool
    tracking_number: str = ""
    current_status: str = ""
    delivered: bool = False
    events: list[TrackingEvent] = field(default_factory=list)
    error: str = ""


def _aramex_client_info() -> dict:
    """Build the Aramex ClientInfo block used in all API calls."""
    return {
        "UserName": settings.ARAMEX_USERNAME,
        "Password": settings.ARAMEX_PASSWORD,
        "Version": "v2.0",
        "AccountNumber": settings.ARAMEX_ACCOUNT_NUMBER,
        "AccountPin": settings.ARAMEX_ACCOUNT_PIN,
        "AccountEntity": settings.ARAMEX_ACCOUNT_ENTITY,
        "AccountCountryCode": settings.ARAMEX_ACCOUNT_COUNTRY_CODE,
        "Source": 24,  # Third-party integration
    }


def _build_address(addr: Address) -> dict:
    return {
        "Line1": addr.line1,
        "Line2": addr.line2,
        "City": addr.city,
        "StateOrProvinceCode": addr.state,
        "PostCode": addr.postal_code,
        "CountryCode": addr.country_code,
    }


def _build_contact(addr: Address) -> dict:
    return {
        "PersonName": addr.contact_name,
        "PhoneNumber1": addr.phone,
        "EmailAddress": addr.email,
        "CompanyName": "MZADAK",
    }


async def create_shipment(
    seller_address: Address,
    buyer_address: Address,
    weight_kg: float = 1.0,
    description: str = "Auction item",
    reference: str = "",
    num_pieces: int = 1,
    currency: str = "JOD",
    declared_value: float = 0.0,
) -> ShipmentResult:
    """Create an Aramex domestic/international shipment and get tracking number.

    Returns ShipmentResult with tracking_number and label_url on success.
    """
    if not settings.ARAMEX_USERNAME:
        logger.warning("Aramex not configured — returning mock shipment")
        return ShipmentResult(
            success=True,
            tracking_number=f"MOCK-{reference[:8]}",
            label_url="",
            shipment_id=f"mock-{reference}",
        )

    # Determine product type: domestic vs international
    is_domestic = (
        seller_address.country_code == buyer_address.country_code
    )
    product_group = "DOM" if is_domestic else "EXP"
    product_type = "OND" if is_domestic else "PPX"  # OnDemand / Priority Parcel Express

    payload = {
        "ClientInfo": _aramex_client_info(),
        "LabelInfo": {
            "ReportID": 9201,  # Standard A4 label
            "ReportType": "URL",
        },
        "Shipments": [
            {
                "Reference1": reference,
                "Shipper": {
                    "Reference1": reference,
                    "PartyAddress": _build_address(seller_address),
                    "Contact": _build_contact(seller_address),
                },
                "Consignee": {
                    "Reference1": reference,
                    "PartyAddress": _build_address(buyer_address),
                    "Contact": _build_contact(buyer_address),
                },
                "ShippingDateTime": f"/Date({int(datetime.now(timezone.utc).timestamp() * 1000)})/",
                "DueDate": f"/Date({int(datetime.now(timezone.utc).timestamp() * 1000 + 86400000 * 3)})/",
                "Details": {
                    "Dimensions": None,
                    "ActualWeight": {"Unit": "KG", "Value": weight_kg},
                    "ProductGroup": product_group,
                    "ProductType": product_type,
                    "PaymentType": "P",  # Prepaid
                    "NumberOfPieces": num_pieces,
                    "DescriptionOfGoods": description,
                    "GoodsOriginCountry": seller_address.country_code,
                    "Items": [],
                },
            }
        ],
    }

    # Add customs value for international shipments
    if not is_domestic and declared_value > 0:
        payload["Shipments"][0]["Details"]["CustomsValueAmount"] = {
            "CurrencyCode": currency,
            "Value": declared_value,
        }

    url = f"{settings.ARAMEX_API_URL}/CreateShipments"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)

        if resp.status_code != 200:
            logger.error("Aramex API returned %d: %s", resp.status_code, resp.text[:300])
            return ShipmentResult(success=False, error=f"HTTP {resp.status_code}")

        data = resp.json()

        if data.get("HasErrors"):
            notifications = data.get("Notifications", [])
            error_msg = "; ".join(n.get("Message", "") for n in notifications)
            logger.error("Aramex CreateShipments error: %s", error_msg)
            return ShipmentResult(success=False, error=error_msg)

        shipments = data.get("Shipments", [])
        if not shipments:
            return ShipmentResult(success=False, error="No shipment returned")

        shipment = shipments[0]
        tracking = shipment.get("ID", "")
        label_url = shipment.get("ShipmentLabel", {}).get("LabelURL", "")

        logger.info(
            "Aramex shipment created: tracking=%s ref=%s domestic=%s",
            tracking, reference, is_domestic,
        )

        return ShipmentResult(
            success=True,
            tracking_number=str(tracking),
            label_url=label_url,
            shipment_id=str(tracking),
        )

    except Exception as exc:
        logger.error("Aramex CreateShipments exception: %s", exc)
        return ShipmentResult(success=False, error=str(exc))


async def track_shipment(tracking_number: str) -> TrackingResult:
    """Track an Aramex shipment by AWB number.

    Returns TrackingResult with events list and current status.
    """
    if not settings.ARAMEX_USERNAME:
        return TrackingResult(
            success=True,
            tracking_number=tracking_number,
            current_status="mock_in_transit",
        )

    payload = {
        "ClientInfo": _aramex_client_info(),
        "Shipments": [tracking_number],
        "GetLastTrackingUpdateOnly": False,
    }

    url = f"{settings.ARAMEX_TRACKING_URL}/TrackShipments"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)

        if resp.status_code != 200:
            return TrackingResult(
                success=False,
                tracking_number=tracking_number,
                error=f"HTTP {resp.status_code}",
            )

        data = resp.json()

        if data.get("HasErrors"):
            notifications = data.get("Notifications", [])
            error_msg = "; ".join(n.get("Message", "") for n in notifications)
            return TrackingResult(
                success=False,
                tracking_number=tracking_number,
                error=error_msg,
            )

        results = data.get("TrackingResults", [])
        if not results:
            return TrackingResult(
                success=False,
                tracking_number=tracking_number,
                error="No tracking results",
            )

        result = results[0]
        events = []
        delivered = False

        for update in result.get("Value", []):
            code = update.get("UpdateCode", "")
            desc = update.get("UpdateDescription", "")
            location = update.get("UpdateLocation", "")

            # Parse Aramex date format /Date(timestamp)/
            ts_str = update.get("UpdateDateTime", "")
            ts = _parse_aramex_date(ts_str)

            events.append(TrackingEvent(
                timestamp=ts,
                location=location,
                description=desc,
                code=code,
            ))

            if code in ("SH005", "SH239"):  # Delivered codes
                delivered = True

        current_status = events[0].code if events else "unknown"

        return TrackingResult(
            success=True,
            tracking_number=tracking_number,
            current_status=current_status,
            delivered=delivered,
            events=events,
        )

    except Exception as exc:
        logger.error("Aramex TrackShipments exception: %s", exc)
        return TrackingResult(
            success=False,
            tracking_number=tracking_number,
            error=str(exc),
        )


def _parse_aramex_date(date_str: str) -> datetime:
    """Parse Aramex /Date(1234567890000)/ format to datetime."""
    try:
        if "/Date(" in date_str:
            ts_ms = int(date_str.split("(")[1].split(")")[0].split("+")[0].split("-")[0])
            return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    except (ValueError, IndexError):
        pass
    return datetime.now(timezone.utc)
