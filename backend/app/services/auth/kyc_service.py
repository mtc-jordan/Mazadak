"""
KYC verification business logic — FR-AUTH-005, PM-02.

Flow:
  1. Initiate: generate S3 presigned PUT URLs for id_front, id_back, selfie
  2. Submit: call Rekognition CompareFaces(selfie, id_front)
     - >= 85%: auto-approve → KYC_VERIFIED
     - 70-84%: manual review → KYC_PENDING_REVIEW
     - < 70%:  reject (allow 1 retry with different ID)
  3. Admin review: approve or reject pending_review documents

S3: SSE-S3 encryption, private ACL, no public access.
     Pre-signed URLs with 5-minute TTL for upload and reviewer access.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.auth.models import KYCDocument, KYCStatus, User

logger = logging.getLogger(__name__)


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
    SDD §6.2: SSE-S3, private ACL, 5-minute TTL.
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
                "ACL": "private",
            },
            ExpiresIn=settings.KYC_PRESIGNED_URL_EXPIRY,
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
# KYC submission — core decision logic
# ═══════════════════════════════════════════════════════════════════

async def check_kyc_eligibility(user: User) -> tuple[bool, str | None]:
    """Check if user is eligible to submit KYC.

    Returns (eligible, error_code).
    """
    kyc = user.kyc_status.value if hasattr(user.kyc_status, "value") else user.kyc_status

    if kyc == "verified":
        return False, "ALREADY_VERIFIED"
    if kyc == "pending_review":
        return False, "PENDING_REVIEW"
    if user.kyc_attempt_count >= settings.KYC_MAX_ATTEMPTS:
        return False, "MAX_ATTEMPTS_REACHED"
    return True, None


async def submit_kyc(
    user: User,
    id_front_key: str,
    id_back_key: str,
    selfie_key: str,
    db: AsyncSession,
) -> dict:
    """Process KYC submission: store documents, call Rekognition, decide.

    FR-AUTH-005 Decision Matrix:
      >= 85%:  KYC_VERIFIED immediately
      70-84%:  KYC_PENDING_REVIEW, add to admin queue
      < 70%:   rejected, allow 1 retry (different ID)
      None:    Rekognition unavailable → queue for manual review

    Returns {status, message_en, message_ar, confidence}.
    """
    # Increment attempt count
    user.kyc_attempt_count = (user.kyc_attempt_count or 0) + 1

    # Store KYC documents
    docs = []
    for doc_type, s3_key in [
        ("id_front", id_front_key),
        ("id_back", id_back_key),
        ("selfie", selfie_key),
    ]:
        doc = KYCDocument(
            id=str(uuid4()),
            user_id=user.id,
            document_type=doc_type,
            s3_key=s3_key,
            status="pending",
        )
        db.add(doc)
        docs.append(doc)

    # Call Rekognition
    confidence = await compare_faces(selfie_key, id_front_key)

    # Decision
    if confidence is not None and confidence >= settings.KYC_AUTO_APPROVE_THRESHOLD:
        # Auto-approve
        user.kyc_status = KYCStatus.VERIFIED
        user.kyc_verified_at = datetime.now(timezone.utc).isoformat()
        for doc in docs:
            doc.status = "approved"
            doc.rekognition_result = f"auto_approved:{confidence:.1f}"
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
            doc.status = "pending_review"
            doc.rekognition_result = f"manual_review:{confidence:.1f}"
        result = {
            "status": "pending_review",
            "message_en": "Your documents are under review. You'll be notified within 24 hours.",
            "message_ar": "مستنداتك قيد المراجعة. سيتم إشعارك خلال 24 ساعة.",
            "confidence": round(confidence, 1),
        }

    elif confidence is None:
        # Rekognition unavailable — queue for manual review (FR-AUTH-005 A5.1)
        user.kyc_status = KYCStatus.PENDING_REVIEW
        for doc in docs:
            doc.status = "pending_review"
            doc.rekognition_result = "rekognition_unavailable"
        result = {
            "status": "pending_review",
            "message_en": "Your documents are under review. You'll be notified within 24 hours.",
            "message_ar": "مستنداتك قيد المراجعة. سيتم إشعارك خلال 24 ساعة.",
            "confidence": None,
        }

    else:
        # Rejected (confidence < 70%)
        for doc in docs:
            doc.status = "rejected"
            doc.rekognition_result = f"rejected:{confidence:.1f}"
        remaining = settings.KYC_MAX_ATTEMPTS - user.kyc_attempt_count
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
    await db.commit()

    logger.info(
        "KYC submission: user=%s confidence=%s decision=%s attempt=%d",
        user.id, confidence, result["status"], user.kyc_attempt_count,
    )
    return result


# ═══════════════════════════════════════════════════════════════════
# Admin review
# ═══════════════════════════════════════════════════════════════════

async def get_pending_reviews(db: AsyncSession) -> list[dict]:
    """Get all KYC documents pending manual review, grouped by user."""
    result = await db.execute(
        select(KYCDocument, User.phone)
        .join(User, KYCDocument.user_id == User.id)
        .where(KYCDocument.status == "pending_review")
        .order_by(KYCDocument.created_at)
    )
    items = []
    for doc, phone in result.all():
        items.append({
            "id": doc.id,
            "user_id": doc.user_id,
            "user_phone": phone,
            "document_type": doc.document_type,
            "s3_key": doc.s3_key,
            "rekognition_confidence": _parse_confidence(doc.rekognition_result),
            "status": doc.status,
            "created_at": str(doc.created_at) if doc.created_at else "",
        })
    return items


def _parse_confidence(result_str: str | None) -> float | None:
    """Extract confidence from rekognition_result like 'manual_review:78.5'."""
    if not result_str or ":" not in result_str:
        return None
    try:
        return float(result_str.split(":")[-1])
    except (ValueError, IndexError):
        return None


async def review_kyc(
    user_id: str,
    decision: str,
    reason: str,
    reviewer_id: str,
    db: AsyncSession,
) -> bool:
    """Admin approves or rejects a pending KYC review.

    Updates all pending_review documents for the user and the user's kyc_status.
    Returns True if successful, False if no pending review found.
    """
    # Find user
    user = await db.get(User, user_id)
    if not user:
        return False

    kyc = user.kyc_status.value if hasattr(user.kyc_status, "value") else user.kyc_status
    if kyc != "pending_review":
        return False

    # Update documents
    new_doc_status = "approved" if decision == "approve" else "rejected"
    await db.execute(
        update(KYCDocument)
        .where(KYCDocument.user_id == user_id, KYCDocument.status == "pending_review")
        .values(status=new_doc_status)
    )

    # Update user
    if decision == "approve":
        user.kyc_status = KYCStatus.VERIFIED
        user.kyc_verified_at = datetime.now(timezone.utc).isoformat()
    else:
        user.kyc_status = KYCStatus.REJECTED

    await db.flush()
    await db.commit()

    logger.info(
        "KYC review: user=%s decision=%s reviewer=%s reason=%s",
        user_id, decision, reviewer_id, reason,
    )
    return True
