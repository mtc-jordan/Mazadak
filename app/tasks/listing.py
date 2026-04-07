"""
Listing Celery tasks — FR-LIST-005 (image processing), FR-LIST-007 (pHash),
FR-LIST-012 (Meilisearch sync within 10s).
"""

from __future__ import annotations

import io
import json
import logging

from app.core.celery import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.process_listing_images", bind=True, max_retries=3)
def process_listing_images(self, listing_id: str) -> None:
    """Download images from S3, convert to WebP, generate thumbnails, compute pHash.

    FR-LIST-005: Server converts to WebP, generates 100px, 400px, 800px thumbnails.
    FR-LIST-007: pHash computed on primary image, compared against existing listings.
    """
    logger.info("Processing images for listing %s", listing_id)

    try:
        import boto3
        from PIL import Image
        import imagehash

        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        bucket = settings.S3_BUCKET_MEDIA

        # Load listing from DB (sync context — Celery worker)
        from app.core.database import engine as async_engine
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session

        # Use sync connection for Celery
        sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
        sync_engine = create_engine(sync_url)

        with Session(sync_engine) as session:
            row = session.execute(
                text("SELECT id, image_urls FROM listings WHERE id = :id"),
                {"id": listing_id},
            ).fetchone()
            if not row:
                logger.error("Listing %s not found", listing_id)
                return

            raw_urls = row[1]
            image_keys = json.loads(raw_urls) if isinstance(raw_urls, str) else raw_urls

            processed_urls = []
            primary_phash = None

            for idx, key in enumerate(image_keys):
                # Download original
                obj = s3.get_object(Bucket=bucket, Key=key)
                img_bytes = obj["Body"].read()
                img = Image.open(io.BytesIO(img_bytes))

                # Convert to WebP (full size)
                webp_key = key.rsplit(".", 1)[0] + ".webp"
                webp_buf = io.BytesIO()
                img.save(webp_buf, format="WEBP", quality=85)
                webp_buf.seek(0)
                s3.put_object(
                    Bucket=bucket, Key=webp_key,
                    Body=webp_buf.getvalue(),
                    ContentType="image/webp",
                    ServerSideEncryption="AES256",
                )
                processed_urls.append(webp_key)

                # Generate thumbnails (100, 400, 800)
                for size in settings.LISTING_THUMBNAIL_SIZES:
                    thumb = img.copy()
                    thumb.thumbnail((size, size), Image.LANCZOS)
                    thumb_key = key.rsplit(".", 1)[0] + f"_thumb_{size}.webp"
                    thumb_buf = io.BytesIO()
                    thumb.save(thumb_buf, format="WEBP", quality=80)
                    thumb_buf.seek(0)
                    s3.put_object(
                        Bucket=bucket, Key=thumb_key,
                        Body=thumb_buf.getvalue(),
                        ContentType="image/webp",
                        ServerSideEncryption="AES256",
                    )

                # Compute pHash on primary image
                if idx == 0:
                    primary_phash = str(imagehash.phash(img))

            # Update listing with processed URLs and pHash
            updates = {"image_urls": json.dumps(processed_urls)}
            if primary_phash:
                updates["phash"] = primary_phash

            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates["id"] = listing_id
            session.execute(
                text(f"UPDATE listings SET {set_clause} WHERE id = :id"),
                updates,
            )
            session.commit()

            # Check for pHash duplicates
            if primary_phash:
                _check_duplicates_sync(session, listing_id, primary_phash)

        logger.info("Image processing complete for listing %s", listing_id)

    except Exception as exc:
        logger.exception("Image processing failed for listing %s", listing_id)
        raise self.retry(exc=exc, countdown=30)


def _check_duplicates_sync(session, listing_id: str, phash_value: str) -> None:
    """Check pHash duplicates in sync context (Celery worker)."""
    from sqlalchemy import text

    rows = session.execute(
        text(
            "SELECT id, phash FROM listings "
            "WHERE phash IS NOT NULL AND id != :id "
            "AND status IN ('active', 'pending_moderation')"
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
                    "UPDATE listings SET status = 'pending_moderation', "
                    "moderation_flags = :flags WHERE id = :id"
                ),
                {
                    "id": listing_id,
                    "flags": json.dumps(["phash_duplicate", f"similar_to:{row_id}"]),
                },
            )
            session.commit()
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
                    "l.listing_currency, l.status, l.seller_id, l.is_charity, "
                    "l.image_urls, l.created_at, l.brand, l.city, "
                    "l.authentication_cert_id, l.bid_count, a.ends_at "
                    "FROM listings l "
                    "LEFT JOIN auctions a ON a.listing_id = l.id "
                    "WHERE l.id = :id"
                ),
                {"id": listing_id},
            ).fetchone()

            if not row:
                logger.error("Listing %s not found for Meilisearch sync", listing_id)
                return

            image_urls = json.loads(row[12]) if isinstance(row[12], str) else (row[12] or [])

            doc = {
                "id": row[0],
                "title_ar": row[1],
                "title_en": row[2],
                "description_ar": row[3],
                "description_en": row[4],
                "category_id": row[5],
                "condition": row[6],
                "starting_price": float(row[7]),
                "listing_currency": row[8],
                "status": row[9],
                "seller_id": row[10],
                "is_charity": bool(row[11]),
                "image_url": image_urls[0] if image_urls else "",
                "created_at": str(row[13]),
                "brand": row[14],
                "city": row[15],
                "is_authenticated": row[16] is not None,
                "bid_count": row[17] or 0,
                "ends_at": str(row[18]) if row[18] else None,
            }

            index.add_documents([doc])
            logger.info("Indexed listing %s in Meilisearch", listing_id)

    except Exception as exc:
        logger.exception("Meilisearch sync failed for listing %s", listing_id)
        raise self.retry(exc=exc, countdown=5)
