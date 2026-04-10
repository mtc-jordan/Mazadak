"""
KYC verification business logic — FR-AUTH-005, PM-02.

Flow:
  1. Initiate: generate S3 presigned PUT URLs for id_front, id_back, selfie
  2. Submit: verify S3 HEAD, call Rekognition CompareFaces(selfie, id_front)
     - >= 85%: auto-approve → KYC_VERIFIED, ats_identity_score = 100
     - 70-84%: manual review → KYC_PENDING_REVIEW
     - < 70%:  reject (allow retry tracked via Redis)
  3. Admin review: approve or reject pending_review documents

S3: SSE-S3 encryption, private ACL, no public access.
     Pre-signed URLs with 900s TTL for upload, 300s for reviewer.
Redis: kyc:attempts:{user_id} — tracks submission attempts (TTL 24h).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.auth.models import KYCStatus, UserKycDocument, User

logger = logging.getLogger(__name__)

KYC_ATTEMPT_KEY = "kyc:attempts:{user_id}"
KYC_ATTEMPT_TTL = 86400  # 24 hours


# ═══════════════════════════════════════════════════════════════════
# S3 presigned URL generation
# ═══════════════════════════════════════════════════════════════════

def _get_s3_client():
    """Return a boto3 S3 client. Imported lazily so tests can mock."""
    import boto3
    return boto3.client(
        "s3",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


async def generate_upload_urls(user_id: str) -> dict:
    """Generate presigned PUT URLs for KYC document upload.

    Returns {upload_urls: {id_front, id_back, selfie}, s3_keys: {...}}.
    SDD §6.2: SSE-S3, private ACL, 900-second (15 min) TTL.
    """
    prefix = f"kyc/{user_id}/{uuid4().hex[:8]}"
    slots = {
        "id_front": f"{prefix}/id_front.jpg",
        "id_back": f"{prefix}/id_back.jpg",
        "selfie": f"{prefix}/selfie.jpg",
    }

    s3 = _get_s3_client()
    upload_urls = {}
    for name, key in slots.items():
        upload_urls[name] = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.S3_BUCKET_KYC,
                "Key": key,
                "ContentType": "image/jpeg",
                "ServerSideEncryption": "AES256",
                "Metadata": {
                    "user_id": user_id,
                    "document_type": name,
                },
            },
            ExpiresIn=900,
        )

    return {"upload_urls": upload_urls, "s3_keys": slots}


def generate_reviewer_url(s3_key: str) -> str:
    """Generate a presigned GET URL for admin reviewer (5-min TTL)."""
    s3 = _get_s3_client()
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET_KYC, "Key": s3_key},
        ExpiresIn=settings.KYC_REVIEWER_URL_EXPIRY,
    )


# ═══════════════════════════════════════════════════════════════════
# S3 HEAD verification
# ═══════════════════════════════════════════════════════════════════

def _verify_s3_object_exists(s3_key: str) -> bool:
    """Verify an S3 object exists via HEAD request."""
    try:
        s3 = _get_s3_client()
        s3.head_object(Bucket=settings.S3_BUCKET_KYC, Key=s3_key)
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
# Rekognition face comparison
# ═══════════════════════════════════════════════════════════════════

def _get_rekognition_client():
    """Return a boto3 Rekognition client. Imported lazily so tests can mock."""
    import boto3
    return boto3.client(
        "rekognition",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


async def compare_faces(selfie_key: str, id_front_key: str) -> float | None:
    """Call Rekognition CompareFaces and return similarity confidence.

    Returns None if Rekognition fails or finds no face matches.
    PM-02 Step 7: CompareFaces(selfie vs ID front).
    """
    try:
        client = _get_rekognition_client()
        response = client.compare_faces(
            SourceImage={
                "S3Object": {"Bucket": settings.S3_BUCKET_KYC, "Name": selfie_key}
            },
            TargetImage={
                "S3Object": {"Bucket": settings.S3_BUCKET_KYC, "Name": id_front_key}
            },
            SimilarityThreshold=0.0,
        )
        if response.get("FaceMatches"):
            return response["FaceMatches"][0]["Similarity"]
        return None
    except Exception:
        logger.exception("Rekognition CompareFaces failed")
        return None


# ═══════════════════════════════════════════════════════════════════
# KYC eligibility check (Redis-based attempt tracking)
# ═══════════════════════════════════════════════════════════════════

async def check_kyc_eligibility(
    user: User, redis: Redis,
) -> tuple[bool, str | None]:
    """Check if user is eligible to submit KYC.

    Returns (eligible, error_code).
    Tracks attempts via Redis (24h TTL) instead of DB column.
    """
    kyc = user.kyc_status.value if hasattr(user.kyc_status, "value") else user.kyc_status

    if kyc == "verified":
        return False, "ALREADY_VERIFIED"
    if kyc == "pending_review":
        return False, "PENDING_REVIEW"

    # Check Redis attempt counter
    key = KYC_ATTEMPT_KEY.format(user_id=user.id)
    count = await redis.get(key)
    if count and int(count) >= settings.KYC_MAX_ATTEMPTS:
        return False, "MAX_ATTEMPTS_REACHED"

    return True, None


async def _increment_kyc_attempts(user_id: str, redis: Redis) -> int:
    """Increment and return KYC attempt count in Redis."""
    key = KYC_ATTEMPT_KEY.format(user_id=user_id)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, KYC_ATTEMPT_TTL)
    return count


# ═══════════════════════════════════════════════════════════════════
# Admin audit log helper
# ═══════════════════════════════════════════════════════════════════

async def _insert_audit_log(
    db: AsyncSession,
    admin_id: str,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict | None = None,
) -> None:
    """Insert a row into admin_audit_log (append-only)."""
    await db.execute(
        text("""
            INSERT INTO admin_audit_log (id, admin_id, action, target_type, target_id, detail)
            VALUES (:id, :admin_id, :action, :target_type, :target_id, :detail::jsonb)
        """),
        {
            "id": str(uuid4()),
            "admin_id": admin_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "detail": str(detail) if detail else None,
        },
    )


# ═══════════════════════════════════════════════════════════════════
# KYC submission — core decision logic
# ═══════════════════════════════════════════════════════════════════

async def submit_kyc(
    user: User,
    id_front_key: str,
    id_back_key: str,
    selfie_key: str,
    db: AsyncSession,
    redis: Redis,
) -> dict:
    """Process KYC submission: verify S3 uploads, call Rekognition, decide.

    FR-AUTH-005 Decision Matrix:
      >= 85%:  KYC_VERIFIED immediately, ats_identity_score = 100
      70-84%:  KYC_PENDING_REVIEW, add to admin queue
      < 70%:   rejected, allow retry (tracked in Redis)
      None:    Rekognition unavailable → queue for manual review

    Returns {status, message_en, message_ar, confidence}.
    """
    # Increment attempt count in Redis
    attempt_count = await _increment_kyc_attempts(user.id, redis)

    # Verify all S3 objects exist via HEAD
    for label, key in [("id_front", id_front_key), ("id_back", id_back_key), ("selfie", selfie_key)]:
        if not _verify_s3_object_exists(key):
            logger.warning("kyc_s3_missing user=%s doc=%s key=%s", user.id, label, key)
            return {
                "status": "rejected",
                "message_en": f"Upload not found: {label}. Please re-upload.",
                "message_ar": f"الملف غير موجود: {label}. يرجى إعادة الرفع.",
                "confidence": None,
            }

    # Update kyc_submitted_at
    user.kyc_submitted_at = datetime.now(timezone.utc)

    # Store KYC documents
    docs = []
    for doc_type, s3_key in [
        ("id_front", id_front_key),
        ("id_back", id_back_key),
        ("selfie", selfie_key),
    ]:
        doc = UserKycDocument(
            id=str(uuid4()),
            user_id=user.id,
            document_type=doc_type,
            s3_key=s3_key,
        )
        db.add(doc)
        docs.append(doc)

    # Call Rekognition
    confidence = await compare_faces(selfie_key, id_front_key)

    # Decision
    if confidence is not None and confidence >= settings.KYC_AUTO_APPROVE_THRESHOLD:
        # Auto-approve
        user.kyc_status = KYCStatus.VERIFIED
        user.kyc_reviewed_at = datetime.now(timezone.utc)
        user.ats_identity_score = 100
        for doc in docs:
            doc.rekognition_confidence = Decimal(str(round(confidence, 2)))
        result = {
            "status": "verified",
            "message_en": "Identity verified! You can now create listings.",
            "message_ar": "تم التحقق من هويتك! يمكنك الآن إنشاء إعلانات.",
            "confidence": round(confidence, 1),
        }

    elif confidence is not None and confidence >= settings.KYC_MANUAL_REVIEW_THRESHOLD:
        # Manual review
        user.kyc_status = KYCStatus.PENDING_REVIEW
        for doc in docs:
            doc.rekognition_confidence = Decimal(str(round(confidence, 2)))
        result = {
            "status": "pending_review",
            "message_en": "Your documents are under review. You'll be notified within 24 hours.",
            "message_ar": "مستنداتك قيد المراجعة. سيتم إشعارك خلال 24 ساعة.",
            "confidence": round(confidence, 1),
        }

    elif confidence is None:
        # Rekognition unavailable — queue for manual review (FR-AUTH-005 A5.1)
        user.kyc_status = KYCStatus.PENDING_REVIEW
        result = {
            "status": "pending_review",
            "message_en": "Your documents are under review. You'll be notified within 24 hours.",
            "message_ar": "مستنداتك قيد المراجعة. سيتم إشعارك خلال 24 ساعة.",
            "confidence": None,
        }

    else:
        # Rejected (confidence < 70%)
        for doc in docs:
            doc.rekognition_confidence = Decimal(str(round(confidence, 2)))
        remaining = settings.KYC_MAX_ATTEMPTS - attempt_count
        if remaining > 0:
            result = {
                "status": "rejected",
                "message_en": (
                    f"Verification failed. You have {remaining} attempt(s) remaining. "
                    "Please use a different, clear photo of your ID."
                ),
                "message_ar": (
                    f"فشل التحقق. لديك {remaining} محاولة متبقية. "
                    "يرجى استخدام صورة مختلفة وواضحة لهويتك."
                ),
                "confidence": round(confidence, 1),
            }
        else:
            result = {
                "status": "rejected",
                "message_en": "Verification failed. Maximum attempts reached. Please contact support.",
                "message_ar": "فشل التحقق. تم الوصول للحد الأقصى من المحاولات. يرجى التواصل مع الدعم.",
                "confidence": round(confidence, 1),
            }

    await db.flush()

    logger.info(
        "kyc_submission user=%s confidence=%s decision=%s attempt=%d",
        user.id, confidence, result["status"], attempt_count,
    )
    return result


# ═══════════════════════════════════════════════════════════════════
# Admin review
# ═══════════════════════════════════════════════════════════════════

async def get_pending_reviews(db: AsyncSession) -> list[dict]:
    """Get all KYC documents pending manual review, grouped by user."""
    result = await db.execute(
        select(UserKycDocument, User.phone)
        .join(User, UserKycDocument.user_id == User.id)
        .where(User.kyc_status == KYCStatus.PENDING_REVIEW)
        .order_by(UserKycDocument.uploaded_at)
    )
    items = []
    for doc, phone in result.all():
        items.append({
            "id": doc.id,
            "user_id": doc.user_id,
            "user_phone": phone,
            "document_type": doc.document_type,
            "s3_key": doc.s3_key,
            "rekognition_confidence": (
                float(doc.rekognition_confidence)
                if doc.rekognition_confidence is not None
                else None
            ),
            "status": "pending_review",
            "uploaded_at": str(doc.uploaded_at) if doc.uploaded_at else "",
        })
    return items


async def review_kyc(
    user_id: str,
    decision: str,
    reason: str,
    reviewer_id: str,
    db: AsyncSession,
) -> bool:
    """Admin approves or rejects a pending KYC review.

    Updates user's kyc_status + kyc_reviewed_at.
    Inserts admin_audit_log entry.
    Returns True if successful, False if no pending review found.
    """
    user = await db.get(User, user_id)
    if not user:
        return False

    kyc = user.kyc_status.value if hasattr(user.kyc_status, "value") else user.kyc_status
    if kyc != "pending_review":
        return False

    now = datetime.now(timezone.utc)

    if decision == "approve":
        user.kyc_status = KYCStatus.VERIFIED
        user.kyc_reviewed_at = now
        user.ats_identity_score = 100
    else:
        user.kyc_status = KYCStatus.REJECTED
        user.kyc_reviewed_at = now
        user.kyc_rejection_reason = reason

    # Insert audit log entry
    try:
        await _insert_audit_log(
            db=db,
            admin_id=reviewer_id,
            action=f"kyc_{decision}",
            target_type="user",
            target_id=user_id,
            detail={"reason": reason} if reason else None,
        )
    except Exception:
        logger.warning("Failed to insert audit log for KYC review", exc_info=True)

    await db.flush()

    logger.info(
        "kyc_review user=%s decision=%s reviewer=%s reason=%s",
        user_id, decision, reviewer_id, reason,
    )
    return True
