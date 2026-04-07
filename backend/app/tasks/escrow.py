"""Escrow Celery tasks — deadline enforcement & notifications."""

import asyncio
import logging

from app.core.celery import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.escrow.dispatch_escrow_notifications",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def dispatch_escrow_notifications(self, escrow_id: str, new_state: str):
    """Send push / SMS / email notifications after an escrow state transition.

    Called by fsm.transition_escrow() after each successful commit.
    """
    # TODO: Implement notification dispatch (push, SMS, email)
    pass


@celery_app.task(
    name="app.tasks.escrow.notify_second_bidder",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def notify_second_bidder(self, auction_id: str):
    """Notify the second-highest bidder after winner payment cancellation.

    Called by webhook handler when payment retries are exhausted.
    The second bidder gets a new payment window for the item.
    """
    # TODO: Look up second-highest bid, create new escrow, send notification
    pass


@celery_app.task(
    name="app.tasks.escrow.void_payment_intent",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def void_payment_intent(self, payment_intent_id: str):
    """Void a Checkout.com payment intent after deadline cancellation."""
    # TODO: Call Checkout.com API to void the intent
    pass


@celery_app.task(
    name="app.tasks.escrow.check_deadlines",
    bind=True,
    max_retries=1,
)
def check_deadlines(self):
    """Beat task (every 5 min): scan escrows with expired deadlines.

    Delegates to the async deadline scanner which handles:
    - PAYMENT_PENDING  → CANCELLED         (payment deadline)
    - SHIPPING_REQUESTED → DISPUTED        (shipping deadline + 15 min)
    - INSPECTION_PERIOD  → RELEASED        (inspection deadline + 15 min)
    - UNDER_REVIEW       → escalate / propose / auto-execute (72/120/144 h)
    """
    asyncio.run(_run_check_deadlines())


async def _run_check_deadlines():
    from app.core.database import async_session_factory
    from app.services.escrow.deadlines import check_escrow_deadlines

    async with async_session_factory() as db:
        results = await check_escrow_deadlines(db)
    total = sum(results.values())
    if total:
        logger.info("Deadline scan complete: %s", results)
