"""
API v1 router — aggregates all service routers under /api/v1.
"""

from fastapi import APIRouter

from app.services.auth.router import router as auth_router
from app.services.auth.admin_router import router as admin_kyc_router
from app.services.listing.router import router as listing_router
from app.services.auction.router import router as auction_router
from app.services.escrow.router import router as escrow_router
from app.api.v1.webhooks import router as webhook_router
from app.services.notification.router import router as notification_router
from app.services.search.router import router as search_router
from app.services.ai.router import router as ai_router
from app.services.whatsapp_bot.router import router as wa_bot_router
from app.services.admin.router import router as admin_router
from app.services.bot.router import router as bot_router

router = APIRouter()

router.include_router(auth_router)
router.include_router(admin_kyc_router)
router.include_router(listing_router)
router.include_router(auction_router)
router.include_router(escrow_router)
router.include_router(webhook_router)
router.include_router(notification_router)
router.include_router(search_router)
router.include_router(ai_router)
router.include_router(wa_bot_router)
router.include_router(admin_router)
router.include_router(bot_router)
