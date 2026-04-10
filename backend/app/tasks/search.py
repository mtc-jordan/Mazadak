"""Meilisearch sync tasks — CDC within 10s of listing status change."""

import logging

from app.core.celery import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.search.sync_pending", bind=True, max_retries=3)
def sync_pending(self):
    """Sync recently changed listings to Meilisearch index.

    Scans listings with updated_at > last sync marker stored in Redis.
    Runs as a Celery Beat task every 10 seconds for near-real-time CDC.
    """
    try:
        import meilisearch
        import redis as redis_lib

        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session

        r = redis_lib.from_url(settings.REDIS_URL)
        last_sync = r.get("meilisearch:last_sync") or b"1970-01-01T00:00:00"
        last_sync_str = last_sync.decode() if isinstance(last_sync, bytes) else last_sync

        sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
        sync_engine = create_engine(sync_url)

        client = meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_API_KEY)
        index = client.index("listings")

        with Session(sync_engine) as session:
            rows = session.execute(
                text(
                    "SELECT l.id, l.title_ar, l.title_en, l.description_ar, "
                    "l.description_en, l.category_id, l.condition, l.starting_price, "
                    "l.current_price, l.status, l.seller_id, l.is_charity, "
                    "l.is_certified, l.bid_count, l.starts_at, l.ends_at, "
                    "l.location_city, l.location_country, l.view_count, "
                    "l.updated_at, l.created_at, "
                    "u.ats_score AS seller_ats "
                    "FROM listings l "
                    "LEFT JOIN users u ON u.id = l.seller_id "
                    "WHERE l.updated_at > :last_sync "
                    "ORDER BY l.updated_at ASC "
                    "LIMIT 500"
                ),
                {"last_sync": last_sync_str},
            ).fetchall()

            if not rows:
                return

            docs_to_index = []
            docs_to_remove = []
            max_updated_at = last_sync_str

            for row in rows:
                listing_id = row[0]
                status = row[9]
                updated_at = str(row[19])

                if updated_at > max_updated_at:
                    max_updated_at = updated_at

                # Remove cancelled/draft listings from index
                if status in ("cancelled", "draft"):
                    docs_to_remove.append(listing_id)
                    continue

                # Get primary image thumbnail
                img_row = session.execute(
                    text(
                        "SELECT s3_key_thumb_400 FROM listing_images "
                        "WHERE listing_id = :id ORDER BY display_order LIMIT 1"
                    ),
                    {"id": listing_id},
                ).fetchone()

                # Compute Unix timestamps
                ends_at = row[15]
                created_at = row[20]
                ends_at_ts = int(ends_at.timestamp()) if ends_at else None
                created_at_ts = int(created_at.timestamp()) if created_at else None

                docs_to_index.append({
                    "id": listing_id,
                    "title_ar": row[1],
                    "title_en": row[2],
                    "description_ar": row[3],
                    "description_en": row[4],
                    "category_id": row[5],
                    "condition": row[6],
                    "starting_price": row[7],
                    "current_price": row[8] or row[7],
                    "status": status,
                    "seller_id": row[10],
                    "seller_ats": row[21] or 0,
                    "is_charity": bool(row[11]),
                    "is_certified": bool(row[12]),
                    "bid_count": row[13] or 0,
                    "ends_at_timestamp": ends_at_ts,
                    "created_at_timestamp": created_at_ts,
                    "location_city": row[16],
                    "location_country": row[17],
                    "image_url": img_row[0] if img_row and img_row[0] else "",
                })

            if docs_to_index:
                index.add_documents(docs_to_index)
            for doc_id in docs_to_remove:
                index.delete_document(doc_id)

            r.set("meilisearch:last_sync", max_updated_at)

            logger.info(
                "Meilisearch sync_pending: indexed=%d removed=%d",
                len(docs_to_index), len(docs_to_remove),
            )

    except Exception as exc:
        logger.exception("Meilisearch sync_pending failed")
        raise self.retry(exc=exc, countdown=10)
