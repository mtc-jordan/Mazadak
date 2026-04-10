"""
Celery application — async task queue for:
- Bid persistence (Redis → PostgreSQL)
- Auction deadline monitoring
- Escrow deadline enforcement (Celery Beat)
- Notification dispatch (FCM, SMS, WhatsApp, email)
- ATS score recomputation
- Meilisearch index sync
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "mzadak",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Beat schedule — escrow deadline checks every 5 minutes (SDD §3.3)
    beat_schedule={
        "activate-scheduled-auctions": {
            "task": "app.tasks.auction.activate_scheduled_auctions",
            "schedule": 30.0,  # 30 seconds (SDD §3.2.1)
        },
        "check-escrow-deadlines": {
            "task": "app.tasks.escrow.check_deadlines",
            "schedule": 300.0,  # 5 minutes
            "options": {"queue": "high"},
        },
        "sync-meilisearch": {
            "task": "app.tasks.search.sync_pending",
            "schedule": 10.0,  # 10 seconds (SDD §4.2 CDC target)
        },
        "check-stale-auctions": {
            "task": "app.tasks.auction.check_stale_auctions",
            "schedule": 300.0,  # 5 minutes — failsafe for missed expirations
        },
        "retrain-price-oracle": {
            "task": "tasks.retrain_price_model",
            "schedule": crontab(hour=0, minute=0, day_of_week=1),  # Monday 3am Amman (UTC+3) = Monday 00:00 UTC
        },
        "weekly-ats-recalculation": {
            "task": "app.tasks.escrow.recalculate_all_ats",
            "schedule": crontab(hour=23, minute=0, day_of_week=6),  # Sunday 2am Amman (UTC+3) = Saturday 23:00 UTC
        },
    },
)

celery_app.autodiscover_tasks(["app.tasks"])
