"""
Webhook endpoints — no JWT, verified by provider-specific signatures.

POST /api/v1/webhooks/checkout  — Checkout.com payment events (HMAC-SHA256)
"""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.services.escrow.webhook import handle_webhook, verify_signature

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/checkout")
async def checkout_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Checkout.com payment webhook — HMAC-SHA256 verified, idempotent."""
    body = await request.body()
    signature = request.headers.get("cko-signature", "")

    if not verify_signature(body, signature, settings.CHECKOUT_WEBHOOK_SECRET):
        return Response(
            content='{"detail":"invalid_signature"}',
            status_code=status.HTTP_401_UNAUTHORIZED,
            media_type="application/json",
        )

    payload = await request.json()
    event_type = payload.get("type", "")
    data = payload.get("data", {})

    result = await handle_webhook(event_type, data, db)
    return result
