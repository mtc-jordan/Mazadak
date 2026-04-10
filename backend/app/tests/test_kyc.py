"""
KYC verification tests — FR-AUTH-005, PM-02.

Covers:
  KYC eligibility:
    - Not-started user can submit
    - Already verified → 400
    - Pending review → 400
    - Max attempts reached → 400

  POST /auth/kyc/initiate:
    - Returns presigned URLs for id_front, id_back, selfie
    - Unauthenticated → 401

  POST /auth/kyc/submit — three confidence branches:
    - >= 85%: auto-approve → status=verified, ats_identity_score=100
    - 70-84%: manual review → status=pending_review
    - < 70%:  reject → status=rejected, retry allowed
    - Rekognition unavailable → manual review fallback
    - Max attempts exhausted

  Admin endpoints:
    - GET /admin/kyc/queue: lists pending reviews
    - POST /admin/kyc/{user_id}/approve: approves + ats_identity_score=100
    - POST /admin/kyc/{user_id}/reject: rejects with reason
    - Non-admin cannot access queue
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from jose import jwt

import app.core.security as sec
from app.services.auth import kyc_service
from app.services.auth.models import KYCStatus, User, UserRole, UserStatus
from app.tests.conftest import FakeRedis


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _make_token(user_id: str, role: str = "buyer", kyc: str = "not_started") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "kyc": kyc,
        "ats": 400,
        "jti": uuid4().hex,
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    return jwt.encode(payload, sec._private_key, algorithm="RS256")


async def _create_user(
    db,
    phone: str = "+962790000000",
    role: UserRole = UserRole.BUYER,
    kyc: KYCStatus = KYCStatus.NOT_STARTED,
) -> User:
    user = User(
        id=str(uuid4()),
        phone=phone,
        full_name_ar="اختبار",
        role=role,
        status=UserStatus.PENDING_KYC,
        kyc_status=kyc,
        ats_score=400,
        preferred_language="ar",
        fcm_tokens=[],
        is_pro_seller=False,
    )
    db.add(user)
    await db.flush()
    await db.commit()
    return user


def _mock_s3():
    """Return a mock S3 client for presigned URLs."""
    mock = MagicMock()
    mock.generate_presigned_url.return_value = "https://s3.example.com/presigned"
    mock.head_object.return_value = {"ContentLength": 1024}
    return mock


def _mock_rekognition(confidence: float | None):
    """Return a mock Rekognition client with the given confidence."""
    mock = MagicMock()
    if confidence is not None:
        mock.compare_faces.return_value = {
            "FaceMatches": [{"Similarity": confidence, "Face": {}}],
        }
    else:
        mock.compare_faces.side_effect = Exception("Rekognition unavailable")
    return mock


# ═══════════════════════════════════════════════════════════════════
# KYC eligibility (unit tests)
# ═══════════════════════════════════════════════════════════════════

class TestKYCEligibility:
    async def test_not_started_user_eligible(self, db_session):
        redis = FakeRedis()
        user = await _create_user(db_session)
        ok, err = await kyc_service.check_kyc_eligibility(user, redis)
        assert ok is True
        assert err is None

    async def test_verified_user_not_eligible(self, db_session):
        redis = FakeRedis()
        user = await _create_user(db_session, kyc=KYCStatus.VERIFIED)
        ok, err = await kyc_service.check_kyc_eligibility(user, redis)
        assert ok is False
        assert err == "ALREADY_VERIFIED"

    async def test_pending_review_not_eligible(self, db_session):
        redis = FakeRedis()
        user = await _create_user(db_session, kyc=KYCStatus.PENDING_REVIEW)
        ok, err = await kyc_service.check_kyc_eligibility(user, redis)
        assert ok is False
        assert err == "PENDING_REVIEW"

    async def test_max_attempts_not_eligible(self, db_session):
        redis = FakeRedis()
        user = await _create_user(db_session)
        # Set attempt count to max in Redis
        await redis.set(f"kyc:attempts:{user.id}", "2")
        ok, err = await kyc_service.check_kyc_eligibility(user, redis)
        assert ok is False
        assert err == "MAX_ATTEMPTS_REACHED"


# ═══════════════════════════════════════════════════════════════════
# KYC submit — three confidence branches (unit tests)
# ═══════════════════════════════════════════════════════════════════

class TestKYCSubmit:
    """Tests the core submit_kyc logic by mocking S3 + Rekognition."""

    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_auto_approve_above_85(self, mock_s3_head, mock_rek_fn, db_session):
        """PM-02: >= 85% → KYC_VERIFIED immediately, ats_identity_score=100."""
        mock_rek_fn.return_value = _mock_rekognition(92.5)
        redis = FakeRedis()
        user = await _create_user(db_session)

        result = await kyc_service.submit_kyc(
            user, "kyc/id_front.jpg", "kyc/id_back.jpg", "kyc/selfie.jpg",
            db_session, redis,
        )

        assert result["status"] == "verified"
        assert result["confidence"] == 92.5
        assert user.kyc_status == KYCStatus.VERIFIED
        assert user.ats_identity_score == 100
        assert user.kyc_reviewed_at is not None

    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_manual_review_70_to_84(self, mock_s3_head, mock_rek_fn, db_session):
        """PM-02: 70-84% → KYC_PENDING_REVIEW."""
        mock_rek_fn.return_value = _mock_rekognition(78.3)
        redis = FakeRedis()
        user = await _create_user(db_session)

        result = await kyc_service.submit_kyc(
            user, "kyc/id_front.jpg", "kyc/id_back.jpg", "kyc/selfie.jpg",
            db_session, redis,
        )

        assert result["status"] == "pending_review"
        assert result["confidence"] == 78.3
        assert user.kyc_status == KYCStatus.PENDING_REVIEW
        assert "24 hours" in result["message_en"]

    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_reject_below_70(self, mock_s3_head, mock_rek_fn, db_session):
        """PM-02: < 70% → rejected, 1 retry allowed."""
        mock_rek_fn.return_value = _mock_rekognition(45.2)
        redis = FakeRedis()
        user = await _create_user(db_session)

        result = await kyc_service.submit_kyc(
            user, "kyc/id_front.jpg", "kyc/id_back.jpg", "kyc/selfie.jpg",
            db_session, redis,
        )

        assert result["status"] == "rejected"
        assert result["confidence"] == 45.2
        assert "1 attempt(s) remaining" in result["message_en"]

    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_reject_max_attempts_exhausted(self, mock_s3_head, mock_rek_fn, db_session):
        """Second rejection → no more attempts."""
        mock_rek_fn.return_value = _mock_rekognition(30.0)
        redis = FakeRedis()
        user = await _create_user(db_session)

        # Pre-fill 1 attempt in Redis
        await redis.set(f"kyc:attempts:{user.id}", "1")

        result = await kyc_service.submit_kyc(
            user, "kyc/id_front.jpg", "kyc/id_back.jpg", "kyc/selfie.jpg",
            db_session, redis,
        )

        assert result["status"] == "rejected"
        assert "Maximum attempts reached" in result["message_en"]

    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_rekognition_unavailable_queues_manual(self, mock_s3_head, mock_rek_fn, db_session):
        """FR-AUTH-005 A5.1: Rekognition fails → manual review."""
        mock_rek_fn.return_value = _mock_rekognition(None)
        redis = FakeRedis()
        user = await _create_user(db_session)

        result = await kyc_service.submit_kyc(
            user, "kyc/id_front.jpg", "kyc/id_back.jpg", "kyc/selfie.jpg",
            db_session, redis,
        )

        assert result["status"] == "pending_review"
        assert result["confidence"] is None
        assert user.kyc_status == KYCStatus.PENDING_REVIEW

    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_exactly_85_auto_approves(self, mock_s3_head, mock_rek_fn, db_session):
        """Boundary: exactly 85.0 → auto-approve."""
        mock_rek_fn.return_value = _mock_rekognition(85.0)
        redis = FakeRedis()
        user = await _create_user(db_session)

        result = await kyc_service.submit_kyc(
            user, "kyc/id_front.jpg", "kyc/id_back.jpg", "kyc/selfie.jpg",
            db_session, redis,
        )
        assert result["status"] == "verified"

    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_exactly_70_manual_review(self, mock_s3_head, mock_rek_fn, db_session):
        """Boundary: exactly 70.0 → manual review."""
        mock_rek_fn.return_value = _mock_rekognition(70.0)
        redis = FakeRedis()
        user = await _create_user(db_session)

        result = await kyc_service.submit_kyc(
            user, "kyc/id_front.jpg", "kyc/id_back.jpg", "kyc/selfie.jpg",
            db_session, redis,
        )
        assert result["status"] == "pending_review"

    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_documents_stored_in_db(self, mock_s3_head, mock_rek_fn, db_session):
        """Three UserKycDocument rows created per submission."""
        mock_rek_fn.return_value = _mock_rekognition(90.0)
        redis = FakeRedis()
        user = await _create_user(db_session)

        await kyc_service.submit_kyc(
            user, "kyc/front.jpg", "kyc/back.jpg", "kyc/self.jpg",
            db_session, redis,
        )

        from sqlalchemy import select
        from app.services.auth.models import UserKycDocument
        result = await db_session.execute(
            select(UserKycDocument).where(UserKycDocument.user_id == user.id)
        )
        docs = result.scalars().all()
        assert len(docs) == 3
        types = {d.document_type for d in docs}
        assert types == {"id_front", "id_back", "selfie"}

    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=False)
    async def test_missing_s3_object_rejected(self, mock_s3_head, db_session):
        """S3 HEAD fails → rejected with re-upload message."""
        redis = FakeRedis()
        user = await _create_user(db_session)

        result = await kyc_service.submit_kyc(
            user, "kyc/front.jpg", "kyc/back.jpg", "kyc/self.jpg",
            db_session, redis,
        )
        assert result["status"] == "rejected"
        assert "re-upload" in result["message_en"].lower()


# ═══════════════════════════════════════════════════════════════════
# Admin review (unit tests)
# ═══════════════════════════════════════════════════════════════════

class TestAdminReview:
    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    @patch("app.services.auth.kyc_service._insert_audit_log")
    async def test_approve_sets_verified(self, mock_audit, mock_s3_head, mock_rek_fn, db_session):
        mock_rek_fn.return_value = _mock_rekognition(75.0)
        redis = FakeRedis()
        user = await _create_user(db_session)
        admin = await _create_user(db_session, phone="+962790000001", role=UserRole.ADMIN)

        # Submit → pending_review
        await kyc_service.submit_kyc(
            user, "kyc/f.jpg", "kyc/b.jpg", "kyc/s.jpg", db_session, redis,
        )
        assert user.kyc_status == KYCStatus.PENDING_REVIEW

        # Admin approves
        ok = await kyc_service.review_kyc(user.id, "approve", "", admin.id, db_session)
        assert ok is True

        await db_session.refresh(user)
        assert user.kyc_status == KYCStatus.VERIFIED
        assert user.ats_identity_score == 100
        assert user.kyc_reviewed_at is not None

    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    @patch("app.services.auth.kyc_service._insert_audit_log")
    async def test_reject_sets_rejected(self, mock_audit, mock_s3_head, mock_rek_fn, db_session):
        mock_rek_fn.return_value = _mock_rekognition(78.0)
        redis = FakeRedis()
        user = await _create_user(db_session)
        admin = await _create_user(db_session, phone="+962790000001", role=UserRole.ADMIN)

        await kyc_service.submit_kyc(
            user, "kyc/f.jpg", "kyc/b.jpg", "kyc/s.jpg", db_session, redis,
        )

        ok = await kyc_service.review_kyc(user.id, "reject", "Blurry ID", admin.id, db_session)
        assert ok is True

        await db_session.refresh(user)
        assert user.kyc_status == KYCStatus.REJECTED
        assert user.kyc_rejection_reason == "Blurry ID"

    async def test_review_nonexistent_user_returns_false(self, db_session):
        with patch("app.services.auth.kyc_service._insert_audit_log"):
            ok = await kyc_service.review_kyc(str(uuid4()), "approve", "", str(uuid4()), db_session)
        assert ok is False

    async def test_review_non_pending_user_returns_false(self, db_session):
        user = await _create_user(db_session, kyc=KYCStatus.VERIFIED)
        with patch("app.services.auth.kyc_service._insert_audit_log"):
            ok = await kyc_service.review_kyc(user.id, "reject", "", str(uuid4()), db_session)
        assert ok is False


# ═══════════════════════════════════════════════════════════════════
# Integration tests (HTTP endpoints)
# ═══════════════════════════════════════════════════════════════════

class TestKYCInitiateEndpoint:
    @patch("app.services.auth.kyc_service._get_s3_client")
    async def test_returns_presigned_urls(self, mock_s3_fn, client, db_session, fake_redis):
        mock_s3_fn.return_value = _mock_s3()
        user = await _create_user(db_session)
        token = _make_token(user.id)

        resp = await client.post(
            "/api/v1/auth/kyc/initiate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "upload_urls" in data
        assert set(data["upload_urls"].keys()) == {"id_front", "id_back", "selfie"}
        assert "s3_keys" in data
        assert set(data["s3_keys"].keys()) == {"id_front", "id_back", "selfie"}
        assert data["expires_in"] == 900  # 15 minutes per spec

    async def test_unauthenticated_returns_401(self, client):
        resp = await client.post("/api/v1/auth/kyc/initiate")
        assert resp.status_code in (401, 403)

    @patch("app.services.auth.kyc_service._get_s3_client")
    async def test_already_verified_returns_400(self, mock_s3_fn, client, db_session, fake_redis):
        mock_s3_fn.return_value = _mock_s3()
        user = await _create_user(db_session, kyc=KYCStatus.VERIFIED)
        token = _make_token(user.id, kyc="verified")

        resp = await client.post(
            "/api/v1/auth/kyc/initiate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "ALREADY_VERIFIED"

    @patch("app.services.auth.kyc_service._get_s3_client")
    async def test_max_attempts_returns_400(self, mock_s3_fn, client, db_session, fake_redis):
        mock_s3_fn.return_value = _mock_s3()
        user = await _create_user(db_session)
        # Set max attempts in Redis
        await fake_redis.set(f"kyc:attempts:{user.id}", "2")
        token = _make_token(user.id)

        resp = await client.post(
            "/api/v1/auth/kyc/initiate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "MAX_ATTEMPTS_REACHED"


class TestKYCSubmitEndpoint:
    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_auto_approve(self, mock_s3_head, mock_rek_fn, client, db_session, fake_redis):
        mock_rek_fn.return_value = _mock_rekognition(91.0)
        user = await _create_user(db_session)
        token = _make_token(user.id)

        resp = await client.post(
            "/api/v1/auth/kyc/submit",
            json={
                "id_front_key": "kyc/user/id_front.jpg",
                "id_back_key": "kyc/user/id_back.jpg",
                "selfie_key": "kyc/user/selfie.jpg",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "verified"
        assert data["confidence"] == 91.0

    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_manual_review(self, mock_s3_head, mock_rek_fn, client, db_session, fake_redis):
        mock_rek_fn.return_value = _mock_rekognition(77.5)
        user = await _create_user(db_session)
        token = _make_token(user.id)

        resp = await client.post(
            "/api/v1/auth/kyc/submit",
            json={
                "id_front_key": "kyc/user/id_front.jpg",
                "id_back_key": "kyc/user/id_back.jpg",
                "selfie_key": "kyc/user/selfie.jpg",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending_review"

    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_rejection(self, mock_s3_head, mock_rek_fn, client, db_session, fake_redis):
        mock_rek_fn.return_value = _mock_rekognition(40.0)
        user = await _create_user(db_session)
        token = _make_token(user.id)

        resp = await client.post(
            "/api/v1/auth/kyc/submit",
            json={
                "id_front_key": "kyc/user/id_front.jpg",
                "id_back_key": "kyc/user/id_back.jpg",
                "selfie_key": "kyc/user/selfie.jpg",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"
        assert data["confidence"] == 40.0


class TestAdminKYCEndpoints:
    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_queue_returns_pending_items(self, mock_s3_head, mock_rek_fn, client, db_session, fake_redis):
        mock_rek_fn.return_value = _mock_rekognition(75.0)
        redis_local = FakeRedis()
        user = await _create_user(db_session)
        admin = await _create_user(
            db_session, phone="+962790000001", role=UserRole.ADMIN,
        )

        # Submit KYC → pending_review
        await kyc_service.submit_kyc(
            user, "kyc/f.jpg", "kyc/b.jpg", "kyc/s.jpg", db_session, redis_local,
        )

        token = _make_token(admin.id, role="admin")
        resp = await client.get(
            "/api/v1/admin/kyc/queue",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 3  # 3 docs per submission
        assert items[0]["user_id"] == user.id
        assert items[0]["status"] == "pending_review"

    @patch("app.services.auth.kyc_service._insert_audit_log")
    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_approve_endpoint(self, mock_s3_head, mock_rek_fn, mock_audit, client, db_session, fake_redis):
        mock_rek_fn.return_value = _mock_rekognition(75.0)
        redis_local = FakeRedis()
        user = await _create_user(db_session)
        admin = await _create_user(
            db_session, phone="+962790000001", role=UserRole.ADMIN,
        )

        await kyc_service.submit_kyc(
            user, "kyc/f.jpg", "kyc/b.jpg", "kyc/s.jpg", db_session, redis_local,
        )

        token = _make_token(admin.id, role="admin")
        resp = await client.post(
            f"/api/v1/admin/kyc/{user.id}/approve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "verified"

        await db_session.refresh(user)
        assert user.kyc_status == KYCStatus.VERIFIED

    @patch("app.services.auth.kyc_service._insert_audit_log")
    @patch("app.services.auth.kyc_service._get_rekognition_client")
    @patch("app.services.auth.kyc_service._verify_s3_object_exists", return_value=True)
    async def test_reject_endpoint(self, mock_s3_head, mock_rek_fn, mock_audit, client, db_session, fake_redis):
        mock_rek_fn.return_value = _mock_rekognition(73.0)
        redis_local = FakeRedis()
        user = await _create_user(db_session)
        admin = await _create_user(
            db_session, phone="+962790000001", role=UserRole.ADMIN,
        )

        await kyc_service.submit_kyc(
            user, "kyc/f.jpg", "kyc/b.jpg", "kyc/s.jpg", db_session, redis_local,
        )

        token = _make_token(admin.id, role="admin")
        resp = await client.post(
            f"/api/v1/admin/kyc/{user.id}/reject",
            json={"decision": "reject", "reason": "ID photo too blurry"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

        await db_session.refresh(user)
        assert user.kyc_status == KYCStatus.REJECTED

    async def test_buyer_cannot_access_queue(self, client, db_session, fake_redis):
        user = await _create_user(db_session, role=UserRole.BUYER)
        token = _make_token(user.id, role="buyer")

        resp = await client.get(
            "/api/v1/admin/kyc/queue",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_approve_nonexistent_user_returns_404(
        self, client, db_session, fake_redis,
    ):
        admin = await _create_user(
            db_session, phone="+962790000001", role=UserRole.ADMIN,
        )
        token = _make_token(admin.id, role="admin")

        resp = await client.post(
            f"/api/v1/admin/kyc/{uuid4()}/approve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
