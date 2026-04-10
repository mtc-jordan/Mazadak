"""
Webhook endpoints — no JWT, verified by provider-specific signatures.

POST /api/v1/webhooks/checkout  — Checkout.com payment events (HMAC-SHA256)
"""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.webhook.checkout_handler import (
    handle_checkout_webhook,
    verify_checkout_signature,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/checkout")
async def checkout_webhook(
    raw_body: bytes = Depends(verify_checkout_signature),
    db: AsyncSession = Depends(get_db),
):
    """Checkout.com payment webhook — HMAC-SHA256 verified, idempotent."""
    return await handle_checkout_webhook(raw_body, db)
