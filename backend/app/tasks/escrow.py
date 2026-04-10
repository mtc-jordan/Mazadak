"""Escrow Celery tasks — deadline enforcement & notifications."""

import asyncio
import logging

import httpx

from app.core.celery import celery_app

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  State-transition notification dispatch
# ═══════════════════════════════════════════════════════════════════

# Maps escrow state → notification event_type understood by templates.py
_STATE_EVENT_MAP: dict[str, str] = {
    "payment_pending": "payment_deadline_warning",
    "funds_held": "payment_received",
    "shipping_requested": "shipping_requested",
    "label_generated": "label_generated",
    "shipped": "item_shipped",
    "in_transit": "item_in_transit",
    "delivered": "item_delivered",
    "inspection_period": "inspection_started",
    "released": "escrow_released",
    "resolved_released": "escrow_released",
    "resolved_refunded": "escrow_refunded",
    "resolved_split": "escrow_split",
    "disputed": "dispute_opened",
    "under_review": "dispute_under_review",
    "cancelled": "payment_failed",
}


@celery_app.task(
    name="app.tasks.escrow.dispatch_escrow_notifications",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def dispatch_escrow_notifications(
    self,
    escrow_id: str,
    from_state: str = "",
    to_state: str = "",
    trigger: str = "",
    metadata: dict | None = None,
):
    """Send push / SMS / email notifications after an escrow state transition.

    Called by fsm.transition_escrow() after each successful commit.
    Notifies both buyer and seller of the state change.
    """
    # Support both old (positional) and new (keyword) calling conventions
    new_state = to_state or from_state  # fallback for legacy callers
    asyncio.run(_dispatch_escrow_notifications_async(escrow_id, new_state))


async def _dispatch_escrow_notifications_async(
    escrow_id: str, new_state: str,
) -> None:
    from app.core.database import async_session_factory
    from app.core.redis import get_redis_client
    from app.services.escrow.service import get_escrow
    from app.services.notification.service import queue_notification

    event_type = _STATE_EVENT_MAP.get(new_state)
    if not event_type:
        logger.debug("No notification mapped for escrow state: %s", new_state)
        return

    redis = await get_redis_client()
    try:
        async with async_session_factory() as db:
            escrow = await get_escrow(escrow_id, db)
            if not escrow:
                logger.warning("Escrow %s not found for notification", escrow_id)
                return

            data = {
                "escrow_id": escrow_id,
                "state": new_state,
                "amount": str(escrow.amount),
                "currency": getattr(escrow, "currency", "JOD"),
            }

            # Notify buyer (winner)
            if escrow.winner_id:
                await queue_notification(
                    escrow.winner_id, event_type, escrow_id, data, redis=redis,
                )

            # Notify seller
            if escrow.seller_id:
                await queue_notification(
                    escrow.seller_id, f"{event_type}", escrow_id, data, redis=redis,
                )

            logger.info(
                "Escrow notifications dispatched: escrow=%s state=%s event=%s",
                escrow_id, new_state, event_type,
            )
    finally:
        await redis.aclose()


# ═══════════════════════════════════════════════════════════════════
#  Second-highest bidder fallback
# ═══════════════════════════════════════════════════════════════════

@celery_app.task(
    name="app.tasks.escrow.notify_second_bidder",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def notify_second_bidder(self, auction_id: str):
    """Notify the second-highest bidder after winner payment cancellation.

    Called by webhook handler when payment retries are exhausted.
    Creates a new escrow for the second bidder with a fresh payment window.
    """
    asyncio.run(_notify_second_bidder_async(auction_id))


# Alias used by checkout_handler.py (spec name)
notify_second_place_bidder = notify_second_bidder


async def _notify_second_bidder_async(auction_id: str) -> None:
    from sqlalchemy import select, desc

    from app.core.database import async_session_factory
    from app.core.redis import get_redis_client
    from app.services.auction.models import Auction, Bid
    from app.services.escrow.service import create_escrow, get_escrow_by_auction
    from app.services.notification.service import queue_notification

    redis = await get_redis_client()
    try:
        async with async_session_factory() as db:
            # Get the auction
            auction = await db.get(Auction, auction_id)
            if not auction or not auction.winner_id:
                logger.warning("No auction/winner for second-bidder fallback: %s", auction_id)
                return

            original_winner = auction.winner_id

            # Find second-highest distinct bidder
            result = await db.execute(
                select(Bid)
                .where(
                    Bid.auction_id == auction_id,
                    Bid.user_id != original_winner,
                )
                .order_by(desc(Bid.amount))
                .limit(1)
            )
            second_bid = result.scalar_one_or_none()

            if not second_bid:
                logger.info("No second bidder for auction %s — item unsold", auction_id)
                return

            # Get listing seller_id
            from app.services.listing.models import Listing
            listing = await db.get(Listing, auction.listing_id)
            if not listing:
                return

            # Create new escrow for second bidder
            # second_bid.amount is stored in cents; escrow.amount must be JOD
            amount_jod = round(float(second_bid.amount) / 100, 2)
            escrow = await create_escrow(
                auction_id=auction_id,
                winner_id=second_bid.user_id,
                seller_id=listing.seller_id,
                amount=amount_jod,
                currency=second_bid.currency,
                db=db,
            )

            # Update auction winner
            auction.winner_id = second_bid.user_id
            auction.final_price = float(second_bid.amount)
            await db.commit()

            # Notify second bidder
            await queue_notification(
                second_bid.user_id,
                "auction_won",
                auction_id,
                {
                    "auction_id": auction_id,
                    "amount": str(second_bid.amount),
                    "escrow_id": escrow.id,
                },
                redis=redis,
            )

            logger.info(
                "Second bidder %s awarded auction %s at %s",
                second_bid.user_id, auction_id, second_bid.amount,
            )
    finally:
        await redis.aclose()


# ═══════════════════════════════════════════════════════════════════
#  Payment-failed notification
# ═══════════════════════════════════════════════════════════════════

@celery_app.task(
    name="app.tasks.escrow.notify_payment_failed",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def notify_payment_failed(self, buyer_id: str, retry_count: int = 0):
    """Notify buyer that payment has failed.

    Called by checkout webhook handler on each decline (before max retries)
    so the buyer knows to retry with a different card.
    """
    asyncio.run(_notify_payment_failed_async(buyer_id, retry_count))


async def _notify_payment_failed_async(buyer_id: str, retry_count: int) -> None:
    from app.core.redis import get_redis_client
    from app.services.notification.service import queue_notification

    redis = await get_redis_client()
    try:
        data = {
            "retry_count": retry_count,
            "max_retries": 3,
        }

        await queue_notification(
            buyer_id, "payment_failed", buyer_id, data, redis=redis,
        )

        logger.info(
            "Payment-failed notification sent to buyer %s (retry %d/3)",
            buyer_id, retry_count,
        )
    finally:
        await redis.aclose()


# ═══════════════════════════════════════════════════════════════════
#  Void Checkout.com payment intent
# ═══════════════════════════════════════════════════════════════════

@celery_app.task(
    name="app.tasks.escrow.void_payment_intent",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def void_payment_intent(self, payment_intent_id: str):
    """Void a Checkout.com payment intent after deadline cancellation.

    Calls the Checkout.com API to void the payment so the hold
    on the buyer's card is released immediately.
    """
    asyncio.run(_void_payment_intent_async(payment_intent_id))


async def _void_payment_intent_async(payment_intent_id: str) -> None:
    from app.core.config import settings

    if not settings.CHECKOUT_SECRET_KEY:
        logger.warning("CHECKOUT_SECRET_KEY not set — skipping void for %s", payment_intent_id)
        return

    url = f"https://api.checkout.com/payments/{payment_intent_id}/voids"
    headers = {
        "Authorization": f"Bearer {settings.CHECKOUT_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json={"reference": payment_intent_id})

        if resp.status_code in (200, 201, 202):
            logger.info("Payment intent voided: %s", payment_intent_id)
        else:
            logger.warning(
                "Checkout.com void failed %d for %s: %s",
                resp.status_code, payment_intent_id, resp.text[:200],
            )
    except Exception as exc:
        logger.error("Void payment intent error for %s: %s", payment_intent_id, exc)


@celery_app.task(
    name="app.tasks.escrow.check_deadlines",
    bind=True,
    max_retries=1,
    queue="high",
)
def check_deadlines(self):
    """Beat task (every 5 min, queue='high'): scan escrows with expired deadlines.

    Delegates to the async deadline monitor which handles:
    - PAYMENT_PENDING  → CANCELLED         (payment deadline)
    - SHIPPING_REQUESTED → DISPUTED        (shipping deadline + 15 min)
    - INSPECTION_PERIOD  → RELEASED        (inspection deadline + 15 min)
    - UNDER_REVIEW       → escalate / propose / auto-execute (72/120/144 h)
    """
    asyncio.run(_run_check_deadlines())


async def _run_check_deadlines():
    from app.core.database import async_session_factory
    from app.services.escrow.deadline_monitor import check_escrow_deadlines

    async with async_session_factory() as db:
        await check_escrow_deadlines(db)


# ═══════════════════════════════════════════════════════════════════
#  Void Checkout.com payment (alias for deadline_monitor)
# ═══════════════════════════════════════════════════════════════════

void_checkout_payment = void_payment_intent


# ═══════════════════════════════════════════════════════════════════
#  ATS score update
# ═══════════════════════════════════════════════════════════════════

@celery_app.task(
    name="app.tasks.escrow.update_ats_score",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def update_ats_score(self, user_id: str, reason: str):
    """Full ATS recalculation for a user after a trigger event.

    Triggers: escrow_released, resolved_refunded, kyc_approved,
    rating_submitted, listing_rejected, shipping_deadline_missed.
    """
    asyncio.run(_update_ats_score_async(user_id, reason))


async def _update_ats_score_async(user_id: str, reason: str) -> None:
    from app.core.database import async_session_factory
    from app.services.auth.ats_service import recalculate_ats

    async with async_session_factory() as db:
        await recalculate_ats(user_id, reason, db)


@celery_app.task(
    name="app.tasks.escrow.recalculate_all_ats",
    bind=True,
    max_retries=1,
)
def recalculate_all_ats(self):
    """Beat task (weekly Sunday 2am): full ATS recalculation for all active sellers."""
    asyncio.run(_recalculate_all_ats_async())


async def _recalculate_all_ats_async() -> None:
    from app.core.database import async_session_factory
    from app.services.auth.ats_service import recalculate_all_sellers

    async with async_session_factory() as db:
        await recalculate_all_sellers(db, batch_size=100)


# ═══════════════════════════════════════════════════════════════════
#  Checkout.com refund helper
# ═══════════════════════════════════════════════════════════════════

async def _checkout_refund(
    checkout_payment_id: str,
    amount_minor: int,
    currency: str,
    reference: str,
) -> dict:
    """Issue a partial or full refund via Checkout.com Payments API.

    Returns the parsed JSON response on success, raises on failure.
    ``amount_minor`` is in the currency's minor units (e.g. fils for JOD,
    where 1 JOD = 1000 fils).
    """
    from app.core.config import settings

    url = f"https://api.checkout.com/payments/{checkout_payment_id}/refunds"
    headers = {
        "Authorization": f"Bearer {settings.CHECKOUT_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    body: dict = {"reference": reference}
    if amount_minor:  # 0 / None → full refund
        body["amount"] = amount_minor

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=body)

    if resp.status_code in (200, 201, 202):
        logger.info(
            "Checkout.com refund succeeded: payment=%s amount=%s %s ref=%s",
            checkout_payment_id, amount_minor, currency, reference,
        )
        return resp.json()

    error_text = resp.text[:300]
    logger.error(
        "Checkout.com refund failed %d: payment=%s ref=%s — %s",
        resp.status_code, checkout_payment_id, reference, error_text,
    )
    raise RuntimeError(
        f"Checkout.com refund failed ({resp.status_code}): {error_text}"
    )


def _jod_to_minor(amount: float) -> int:
    """Convert JOD amount to minor units (fils). 1 JOD = 1000 fils."""
    return int(round(amount * 1000))


# ═══════════════════════════════════════════════════════════════════
#  Seller payout
# ═══════════════════════════════════════════════════════════════════

@celery_app.task(
    name="app.tasks.escrow.trigger_seller_payout",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def trigger_seller_payout(self, escrow_id: str):
    """Trigger payout to seller after escrow release.

    MVP: calculates the platform fee, logs the pending payout, and
    notifies the seller.  Actual bank transfer requires seller bank
    details (not yet in the model) and will use the Checkout.com
    Transfers API once available.
    """
    try:
        asyncio.run(_seller_payout_async(escrow_id))
    except Exception as exc:
        logger.error("Seller payout failed for escrow %s: %s", escrow_id, exc)
        raise self.retry(exc=exc)


async def _seller_payout_async(escrow_id: str) -> None:
    from app.core.config import settings
    from app.core.database import async_session_factory
    from app.core.redis import get_redis_client
    from app.services.escrow.models import EscrowEvent, ActorType
    from app.services.escrow.service import get_escrow
    from app.services.notification.service import queue_notification

    if not settings.CHECKOUT_SECRET_KEY:
        logger.warning(
            "CHECKOUT_SECRET_KEY not set — skipping seller payout for escrow %s",
            escrow_id,
        )
        return

    redis = await get_redis_client()
    try:
        async with async_session_factory() as db:
            escrow = await get_escrow(escrow_id, db)
            if not escrow:
                logger.error("Escrow %s not found for seller payout", escrow_id)
                return

            if escrow.state not in ("released", "resolved_released"):
                logger.warning(
                    "Escrow %s in state %s — expected released/resolved_released, skipping payout",
                    escrow_id, escrow.state,
                )
                return

            # Calculate amounts
            total = float(escrow.amount)
            fee_pct = settings.PLATFORM_FEE_PERCENT
            platform_fee = round(total * fee_pct / 100, 3)
            seller_net = round(total - platform_fee, 3)

            # Use pre-calculated seller_amount if set, otherwise compute
            if escrow.seller_amount is not None:
                seller_net = float(escrow.seller_amount)

            logger.info(
                "Payout pending: seller=%s amount=%.3f %s "
                "(total=%.3f fee=%.1f%%) escrow=%s",
                escrow.seller_id, seller_net, escrow.currency,
                total, fee_pct, escrow_id,
            )

            # Record the payout event in the audit trail
            event = EscrowEvent(
                escrow_id=escrow_id,
                from_state=escrow.state,
                to_state=escrow.state,
                actor_type=ActorType.SYSTEM,
                trigger="seller_payout_queued",
                meta={
                    "total_amount": str(total),
                    "platform_fee_percent": fee_pct,
                    "platform_fee": str(platform_fee),
                    "seller_net": str(seller_net),
                    "currency": escrow.currency,
                    "status": "pending_bank_details",
                },
            )
            db.add(event)
            await db.commit()

            # Notify seller
            await queue_notification(
                escrow.seller_id,
                "seller_payout_pending",
                escrow_id,
                {
                    "escrow_id": escrow_id,
                    "amount": str(seller_net),
                    "currency": escrow.currency,
                },
                redis=redis,
            )
    finally:
        await redis.aclose()


# ═══════════════════════════════════════════════════════════════════
#  Split payout (dispute resolution)
# ═══════════════════════════════════════════════════════════════════

@celery_app.task(
    name="app.tasks.escrow.trigger_split_payout",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def trigger_split_payout(self, escrow_id: str, split_ratio_buyer: int = 50):
    """Trigger split payout after dispute resolution.

    Issues a partial refund to the buyer via Checkout.com for their share,
    and logs the seller's share as a pending payout.
    """
    try:
        asyncio.run(_split_payout_async(escrow_id, split_ratio_buyer))
    except Exception as exc:
        logger.error(
            "Split payout failed for escrow %s: %s", escrow_id, exc,
        )
        raise self.retry(exc=exc)


async def _split_payout_async(escrow_id: str, split_ratio_buyer: int) -> None:
    from app.core.config import settings
    from app.core.database import async_session_factory
    from app.core.redis import get_redis_client
    from app.services.escrow.models import EscrowEvent, ActorType
    from app.services.escrow.service import get_escrow
    from app.services.notification.service import queue_notification

    if not settings.CHECKOUT_SECRET_KEY:
        logger.warning(
            "CHECKOUT_SECRET_KEY not set — skipping split payout for escrow %s",
            escrow_id,
        )
        return

    redis = await get_redis_client()
    try:
        async with async_session_factory() as db:
            escrow = await get_escrow(escrow_id, db)
            if not escrow:
                logger.error("Escrow %s not found for split payout", escrow_id)
                return

            if escrow.state != "resolved_split":
                logger.warning(
                    "Escrow %s in state %s — expected resolved_split, skipping",
                    escrow_id, escrow.state,
                )
                return

            if not escrow.checkout_payment_id:
                logger.error(
                    "Escrow %s has no checkout_payment_id — cannot refund buyer",
                    escrow_id,
                )
                return

            total = float(escrow.amount)
            buyer_refund_amount = round(total * split_ratio_buyer / 100, 3)
            seller_payout_amount = round(total - buyer_refund_amount, 3)

            # Issue partial refund to buyer via Checkout.com
            buyer_refund_minor = _jod_to_minor(buyer_refund_amount)
            refund_result = await _checkout_refund(
                checkout_payment_id=escrow.checkout_payment_id,
                amount_minor=buyer_refund_minor,
                currency=escrow.currency,
                reference=f"split-buyer-{escrow_id}",
            )

            logger.info(
                "Split payout: escrow=%s buyer_refund=%.3f seller_payout=%.3f %s "
                "(ratio=%d/%d)",
                escrow_id, buyer_refund_amount, seller_payout_amount,
                escrow.currency, split_ratio_buyer, 100 - split_ratio_buyer,
            )

            # Record audit event
            event = EscrowEvent(
                escrow_id=escrow_id,
                from_state=escrow.state,
                to_state=escrow.state,
                actor_type=ActorType.SYSTEM,
                trigger="split_payout_executed",
                meta={
                    "total_amount": str(total),
                    "buyer_refund": str(buyer_refund_amount),
                    "seller_payout": str(seller_payout_amount),
                    "split_ratio_buyer": split_ratio_buyer,
                    "currency": escrow.currency,
                    "checkout_refund_id": refund_result.get("action_id", ""),
                    "seller_payout_status": "pending_bank_details",
                },
            )
            db.add(event)
            await db.commit()

            # Notify buyer
            await queue_notification(
                escrow.winner_id,
                "buyer_refund_processed",
                escrow_id,
                {
                    "escrow_id": escrow_id,
                    "amount": str(buyer_refund_amount),
                    "currency": escrow.currency,
                    "type": "split",
                },
                redis=redis,
            )

            # Notify seller
            await queue_notification(
                escrow.seller_id,
                "seller_payout_pending",
                escrow_id,
                {
                    "escrow_id": escrow_id,
                    "amount": str(seller_payout_amount),
                    "currency": escrow.currency,
                    "type": "split",
                },
                redis=redis,
            )
    finally:
        await redis.aclose()


# ═══════════════════════════════════════════════════════════════════
#  Buyer refund (dispute resolved in buyer's favor)
# ═══════════════════════════════════════════════════════════════════

@celery_app.task(
    name="app.tasks.escrow.trigger_buyer_refund",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def trigger_buyer_refund(self, escrow_id: str):
    """Trigger full Checkout.com refund to buyer after dispute resolution."""
    try:
        asyncio.run(_buyer_refund_async(escrow_id))
    except Exception as exc:
        logger.error("Buyer refund failed for escrow %s: %s", escrow_id, exc)
        raise self.retry(exc=exc)


async def _buyer_refund_async(escrow_id: str) -> None:
    from app.core.config import settings
    from app.core.database import async_session_factory
    from app.core.redis import get_redis_client
    from app.services.escrow.models import EscrowEvent, ActorType
    from app.services.escrow.service import get_escrow
    from app.services.notification.service import queue_notification

    if not settings.CHECKOUT_SECRET_KEY:
        logger.warning(
            "CHECKOUT_SECRET_KEY not set — skipping buyer refund for escrow %s",
            escrow_id,
        )
        return

    redis = await get_redis_client()
    try:
        async with async_session_factory() as db:
            escrow = await get_escrow(escrow_id, db)
            if not escrow:
                logger.error("Escrow %s not found for buyer refund", escrow_id)
                return

            if escrow.state != "resolved_refunded":
                logger.warning(
                    "Escrow %s in state %s — expected resolved_refunded, skipping",
                    escrow_id, escrow.state,
                )
                return

            if not escrow.checkout_payment_id:
                logger.error(
                    "Escrow %s has no checkout_payment_id — cannot issue refund",
                    escrow_id,
                )
                return

            total = float(escrow.amount)

            # Full refund — pass 0 to omit amount field (Checkout.com
            # treats missing amount as full refund)
            refund_result = await _checkout_refund(
                checkout_payment_id=escrow.checkout_payment_id,
                amount_minor=0,
                currency=escrow.currency,
                reference=f"refund-{escrow_id}",
            )

            logger.info(
                "Full buyer refund issued: escrow=%s amount=%.3f %s",
                escrow_id, total, escrow.currency,
            )

            # Record audit event
            event = EscrowEvent(
                escrow_id=escrow_id,
                from_state=escrow.state,
                to_state=escrow.state,
                actor_type=ActorType.SYSTEM,
                trigger="buyer_refund_executed",
                meta={
                    "amount": str(total),
                    "currency": escrow.currency,
                    "checkout_refund_id": refund_result.get("action_id", ""),
                    "type": "full_refund",
                },
            )
            db.add(event)
            await db.commit()

            # Notify buyer
            await queue_notification(
                escrow.winner_id,
                "buyer_refund_processed",
                escrow_id,
                {
                    "escrow_id": escrow_id,
                    "amount": str(total),
                    "currency": escrow.currency,
                    "type": "full",
                },
                redis=redis,
            )
    finally:
        await redis.aclose()


# ═══════════════════════════════════════════════════════════════════
#  Mediator SLA notifications
# ═══════════════════════════════════════════════════════════════════

@celery_app.task(
    name="app.tasks.escrow.notify_mediator_sla_breach",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def notify_mediator_sla_breach(self, escrow_id: str):
    """Notify admin of 72h mediator SLA breach — escalate."""
    logger.info("Mediator SLA 72h breach notification for escrow %s", escrow_id)


@celery_app.task(
    name="app.tasks.escrow.notify_mediator_propose_split",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def notify_mediator_propose_split(self, mediator_id: str, escrow_id: str):
    """Notify mediator to propose 50/50 split at 120h SLA."""
    logger.info(
        "Mediator SLA 120h propose-split notification: mediator=%s escrow=%s",
        mediator_id, escrow_id,
    )
