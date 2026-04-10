"""
Listing Celery tasks — FR-LIST-005 (image processing), FR-LIST-007 (pHash),
FR-LIST-012 (Meilisearch sync within 10s).

Image processing: Pillow resize to WebP, 3 thumbnails (100/400/800px),
pHash computation on primary image (display_order=0).
"""

from __future__ import annotations

import io
import json
import logging

from app.core.celery import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.process_listing_image", bind=True, max_retries=3)
def process_listing_image(self, listing_id: str, s3_key: str) -> None:
    """Process a single listing image: convert to WebP, generate thumbnails, compute pHash.

    FR-LIST-005: Server converts to WebP, generates 100px, 400px, 800px thumbnails.
    FR-LIST-007: pHash computed on primary image (display_order=0), compared against existing.
    """
    logger.info("Processing image %s for listing %s", s3_key, listing_id)

    try:
        import boto3
        from PIL import Image
        import imagehash

        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        bucket = settings.S3_BUCKET_MEDIA

        # Download original from S3
        obj = s3.get_object(Bucket=bucket, Key=s3_key)
        img_bytes = obj["Body"].read()
        img = Image.open(io.BytesIO(img_bytes))

        # Generate thumbnails and upload
        thumb_keys = {}
        for size in settings.LISTING_THUMBNAIL_SIZES:
            thumb = img.copy()
            thumb.thumbnail((size, size), Image.LANCZOS)
            thumb_key = s3_key.rsplit(".", 1)[0] + f"_thumb_{size}.webp"
            thumb_buf = io.BytesIO()
            thumb.save(thumb_buf, format="WEBP", quality=80)
            thumb_buf.seek(0)
            s3.put_object(
                Bucket=bucket,
                Key=thumb_key,
                Body=thumb_buf.getvalue(),
                ContentType="image/webp",
                ServerSideEncryption="AES256",
            )
            thumb_keys[size] = thumb_key

        # Update listing_images record with thumbnail keys
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session

        sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
        sync_engine = create_engine(sync_url)

        with Session(sync_engine) as session:
            session.execute(
                text(
                    "UPDATE listing_images "
                    "SET s3_key_thumb_100 = :t100, s3_key_thumb_400 = :t400, s3_key_thumb_800 = :t800 "
                    "WHERE listing_id = :listing_id AND s3_key = :s3_key"
                ),
                {
                    "listing_id": listing_id,
                    "s3_key": s3_key,
                    "t100": thumb_keys.get(100, ""),
                    "t400": thumb_keys.get(400, ""),
                    "t800": thumb_keys.get(800, ""),
                },
            )

            # Check if this is the primary image (display_order=0) for pHash
            row = session.execute(
                text(
                    "SELECT display_order FROM listing_images "
                    "WHERE listing_id = :listing_id AND s3_key = :s3_key"
                ),
                {"listing_id": listing_id, "s3_key": s3_key},
            ).fetchone()

            if row and row[0] == 0:
                # Compute pHash on primary image
                primary_phash = str(imagehash.phash(img))
                session.execute(
                    text("UPDATE listings SET phash = :phash WHERE id = :id"),
                    {"id": listing_id, "phash": primary_phash},
                )
                # Check for duplicates
                _check_duplicates_sync(session, listing_id, primary_phash)

            session.commit()

        logger.info("Image processing complete: %s for listing %s", s3_key, listing_id)

    except Exception as exc:
        logger.exception("Image processing failed: %s for listing %s", s3_key, listing_id)
        raise self.retry(exc=exc, countdown=30)


# Keep backward compat alias
@celery_app.task(name="tasks.process_listing_images", bind=True, max_retries=3)
def process_listing_images(self, listing_id: str) -> None:
    """Process all images for a listing (legacy entry point)."""
    logger.info("Processing all images for listing %s", listing_id)

    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session

        sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
        sync_engine = create_engine(sync_url)

        with Session(sync_engine) as session:
            rows = session.execute(
                text(
                    "SELECT s3_key FROM listing_images "
                    "WHERE listing_id = :listing_id ORDER BY display_order"
                ),
                {"listing_id": listing_id},
            ).fetchall()

            for row in rows:
                process_listing_image.delay(listing_id, row[0])

    except Exception as exc:
        logger.exception("Failed to queue image processing for listing %s", listing_id)
        raise self.retry(exc=exc, countdown=30)


def _check_duplicates_sync(session, listing_id: str, phash_value: str) -> None:
    """Check pHash duplicates in sync context (Celery worker)."""
    from sqlalchemy import text

    rows = session.execute(
        text(
            "SELECT id, phash FROM listings "
            "WHERE phash IS NOT NULL AND id != :id "
            "AND status IN ('active', 'pending_review')"
        ),
        {"id": listing_id},
    ).fetchall()

    for row_id, row_phash in rows:
        similarity = _hamming_similarity(phash_value, row_phash)
        if similarity >= settings.LISTING_PHASH_THRESHOLD:
            logger.warning(
                "pHash duplicate detected: listing=%s matches=%s similarity=%.1f%%",
                listing_id, row_id, similarity,
            )
            # Flag listing for moderation review
            session.execute(
                text(
                    "UPDATE listings SET status = 'pending_review', "
                    "moderation_status = 'flagged', "
                    "moderation_flags = :flags WHERE id = :id"
                ),
                {
                    "id": listing_id,
                    "flags": json.dumps(["phash_duplicate", f"similar_to:{row_id}"]),
                },
            )
            break  # Flag once is enough


def _hamming_similarity(hash1: str, hash2: str) -> float:
    """Compute similarity percentage between two hex pHash strings."""
    if len(hash1) != len(hash2):
        return 0.0
    try:
        val1 = int(hash1, 16)
        val2 = int(hash2, 16)
    except ValueError:
        return 0.0
    xor = val1 ^ val2
    diff_bits = bin(xor).count("1")
    total_bits = len(hash1) * 4
    return round((1.0 - diff_bits / total_bits) * 100, 2) if total_bits else 0.0


@celery_app.task(name="tasks.sync_listing_to_meilisearch", bind=True, max_retries=3)
def sync_listing_to_meilisearch(self, listing_id: str, action: str = "index") -> None:
    """Sync a single listing to Meilisearch within 10s of status change.

    FR-LIST-012: CDC sync.
    action: "index" to add/update, "remove" to delete from index.
    """
    logger.info("Meilisearch sync: listing=%s action=%s", listing_id, action)

    try:
        import meilisearch
        client = meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_API_KEY)
        index = client.index("listings")

        if action == "remove":
            index.delete_document(listing_id)
            logger.info("Removed listing %s from Meilisearch", listing_id)
            return

        # Load listing from DB
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session

        sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
        sync_engine = create_engine(sync_url)

        with Session(sync_engine) as session:
            row = session.execute(
                text(
                    "SELECT l.id, l.title_ar, l.title_en, l.description_ar, "
                    "l.description_en, l.category_id, l.condition, l.starting_price, "
                    "l.current_price, l.status, l.seller_id, l.is_charity, "
                    "l.is_certified, l.bid_count, l.starts_at, l.ends_at, "
                    "l.location_city, l.location_country, l.watcher_count, l.view_count "
                    "FROM listings l WHERE l.id = :id"
                ),
                {"id": listing_id},
            ).fetchone()

            if not row:
                logger.error("Listing %s not found for Meilisearch sync", listing_id)
                return

            # Get primary image
            img_row = session.execute(
                text(
                    "SELECT s3_key_thumb_400 FROM listing_images "
                    "WHERE listing_id = :id ORDER BY display_order LIMIT 1"
                ),
                {"id": listing_id},
            ).fetchone()

            doc = {
                "id": row[0],
                "title_ar": row[1],
                "title_en": row[2],
                "description_ar": row[3],
                "description_en": row[4],
                "category_id": row[5],
                "condition": row[6],
                "starting_price": row[7],
                "current_price": row[8],
                "status": row[9],
                "seller_id": row[10],
                "is_charity": bool(row[11]),
                "is_certified": bool(row[12]),
                "bid_count": row[13] or 0,
                "starts_at": str(row[14]) if row[14] else None,
                "ends_at": str(row[15]) if row[15] else None,
                "location_city": row[16],
                "location_country": row[17],
                "watcher_count": row[18] or 0,
                "view_count": row[19] or 0,
                "image_url": img_row[0] if img_row and img_row[0] else "",
            }

            index.add_documents([doc])
            logger.info("Indexed listing %s in Meilisearch", listing_id)

    except Exception as exc:
        logger.exception("Meilisearch sync failed for listing %s", listing_id)
        raise self.retry(exc=exc, countdown=5)
