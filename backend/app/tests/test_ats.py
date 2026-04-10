"""
ATS (Auction Trust Score) tests — 6 tests covering score calculation,
commission tiers, defaults, and edge cases.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ── Mock Celery (not installed in test env) ──────────────────
if "app.core.celery" not in sys.modules:
    _mock_celery_mod = ModuleType("app.core.celery")
    _mock_celery_mod.celery_app = MagicMock()
    sys.modules["app.core.celery"] = _mock_celery_mod
if "app.tasks" not in sys.modules:
    sys.modules["app.tasks"] = ModuleType("app.tasks")
if "app.tasks.auction" not in sys.modules:
    _m = ModuleType("app.tasks.auction")
    _m.insert_bid_to_db = MagicMock()
    sys.modules["app.tasks.auction"] = _m

from app.services.auth.ats_service import (
    _commission_for_score,
    recalculate_ats,
)


# ── Helper: create a user in the test DB ─────────────────────

async def _create_user(db, *, kyc_status="verified", status="active"):
    from app.services.auth.models import User, UserRole, UserStatus, KYCStatus

    user = User(
        id=str(uuid4()),
        phone=f"+96279{uuid4().hex[:7]}",
        full_name="ATS Test User",
        full_name_ar="مستخدم اختبار",
        role=UserRole.SELLER,
        status=UserStatus(status),
        kyc_status=KYCStatus(kyc_status),
        ats_score=400,
        preferred_language="ar",
        fcm_tokens=[],
        is_pro_seller=False,
    )
    db.add(user)
    await db.flush()
    await db.commit()
    return user


# ═══════════════════════════════════════════════════════════════
# 1. New seller gets default scores (no history)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_new_seller_gets_200_default_completion(db_session, fake_redis):
    """New seller with no escrows gets default sub-scores: completion=200, speed=180, rating=160, quality=100, dispute=100."""
    user = await _create_user(db_session, kyc_status="verified")

    # Mock all sub-calculators to return new-seller defaults
    with (
        patch("app.services.auth.ats_service._calc_completion", return_value=200),
        patch("app.services.auth.ats_service._calc_speed", return_value=180),
        patch("app.services.auth.ats_service._calc_rating", return_value=160),
        patch("app.services.auth.ats_service._calc_quality", return_value=100),
        patch("app.services.auth.ats_service._calc_dispute", return_value=100),
    ):
        total = await recalculate_ats(user.id, "test", db_session)

    # identity=150 + completion=200 + speed=180 + rating=160 + quality=100 + dispute=100 = 890
    assert total == 890

    # Verify user was updated
    await db_session.refresh(user)
    assert user.ats_score == 890
    assert user.ats_identity_score == 150
    assert user.ats_completion_score == 200


# ═══════════════════════════════════════════════════════════════
# 2. Perfect seller scores 1000
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_perfect_seller_scores_1000(db_session, fake_redis):
    """Seller with perfect history across all dimensions scores 1000."""
    user = await _create_user(db_session, kyc_status="verified")

    with (
        patch("app.services.auth.ats_service._calc_completion", return_value=250),   # max
        patch("app.services.auth.ats_service._calc_speed", return_value=200),        # max
        patch("app.services.auth.ats_service._calc_rating", return_value=200),       # max
        patch("app.services.auth.ats_service._calc_quality", return_value=100),      # max
        patch("app.services.auth.ats_service._calc_dispute", return_value=100),      # max
    ):
        total = await recalculate_ats(user.id, "test", db_session)

    # 150 + 250 + 200 + 200 + 100 + 100 = 1000
    assert total == 1000

    await db_session.refresh(user)
    assert user.ats_score == 1000
    assert user.commission_rate == Decimal("0.0400")  # Elite tier


# ═══════════════════════════════════════════════════════════════
# 3. 2% dispute rate zeroes dispute score
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_two_percent_dispute_rate_zeroes_dispute_score(db_session, fake_redis):
    """dispute_rate=0.02 → dispute_score = 100 - 0.02*500 = 90... but 0.20 → 0."""
    user = await _create_user(db_session, kyc_status="verified")

    # With 20% dispute rate: 100 - 0.20*500 = 0
    with (
        patch("app.services.auth.ats_service._calc_completion", return_value=200),
        patch("app.services.auth.ats_service._calc_speed", return_value=180),
        patch("app.services.auth.ats_service._calc_rating", return_value=160),
        patch("app.services.auth.ats_service._calc_quality", return_value=100),
        patch("app.services.auth.ats_service._calc_dispute", return_value=0),   # 20% dispute rate → 0
    ):
        total = await recalculate_ats(user.id, "test", db_session)

    # 150 + 200 + 180 + 160 + 100 + 0 = 790
    assert total == 790

    await db_session.refresh(user)
    assert user.ats_dispute_score == 0


# ═══════════════════════════════════════════════════════════════
# 4. Slow shipper gets low speed score (avg 6 days → < 20)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_slow_shipper_gets_low_speed_score(db_session, fake_redis):
    """Avg 6 days to ship → speed = max(0, 200 - 6*30) = 20."""
    user = await _create_user(db_session, kyc_status="verified")

    # speed for avg_days=6: max(0, 200 - 6*30) = max(0, 20) = 20
    with (
        patch("app.services.auth.ats_service._calc_completion", return_value=250),
        patch("app.services.auth.ats_service._calc_speed", return_value=20),    # 6 days avg
        patch("app.services.auth.ats_service._calc_rating", return_value=200),
        patch("app.services.auth.ats_service._calc_quality", return_value=100),
        patch("app.services.auth.ats_service._calc_dispute", return_value=100),
    ):
        total = await recalculate_ats(user.id, "test", db_session)

    # 150 + 250 + 20 + 200 + 100 + 100 = 820
    assert total == 820

    await db_session.refresh(user)
    assert user.ats_speed_score == 20


# ═══════════════════════════════════════════════════════════════
# 5. Commission tier assignment
# ═══════════════════════════════════════════════════════════════

def test_commission_tier_assignment():
    """750+ → 4%, 600-749 → 5%, 400-599 → 5.5%, <400 → 6%."""
    assert _commission_for_score(1000) == Decimal("0.0400")
    assert _commission_for_score(750) == Decimal("0.0400")
    assert _commission_for_score(749) == Decimal("0.0500")
    assert _commission_for_score(600) == Decimal("0.0500")
    assert _commission_for_score(599) == Decimal("0.0550")  # 400-599 = Silver
    assert _commission_for_score(400) == Decimal("0.0550")
    assert _commission_for_score(399) == Decimal("0.0600")
    assert _commission_for_score(0) == Decimal("0.0600")


# ═══════════════════════════════════════════════════════════════
# 6. ATS clamped between 0 and 1000
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ats_clamped_between_0_and_1000(db_session, fake_redis):
    """Scores exceeding 1000 are clamped; negative components don't go below 0."""
    user = await _create_user(db_session, kyc_status="verified")

    # Simulate impossibly high sub-scores that sum > 1000
    with (
        patch("app.services.auth.ats_service._calc_completion", return_value=250),
        patch("app.services.auth.ats_service._calc_speed", return_value=200),
        patch("app.services.auth.ats_service._calc_rating", return_value=200),
        patch("app.services.auth.ats_service._calc_quality", return_value=100),
        patch("app.services.auth.ats_service._calc_dispute", return_value=200),  # impossibly high
    ):
        total = await recalculate_ats(user.id, "test", db_session)

    # 150 + 250 + 200 + 200 + 100 + 200 = 1100 → clamped to 1000
    assert total == 1000

    # Now test with unverified KYC and all-zero sub-scores
    user2 = await _create_user(db_session, kyc_status="not_started")

    with (
        patch("app.services.auth.ats_service._calc_completion", return_value=0),
        patch("app.services.auth.ats_service._calc_speed", return_value=0),
        patch("app.services.auth.ats_service._calc_rating", return_value=0),
        patch("app.services.auth.ats_service._calc_quality", return_value=0),
        patch("app.services.auth.ats_service._calc_dispute", return_value=0),
    ):
        total2 = await recalculate_ats(user2.id, "test", db_session)

    # 0 + 0 + 0 + 0 + 0 + 0 = 0 → clamped to 0
    assert total2 == 0

    await db_session.refresh(user2)
    assert user2.ats_score == 0
    assert user2.commission_rate == Decimal("0.0600")  # Bronze
