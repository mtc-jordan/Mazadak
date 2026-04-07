"""Initial schema — all SDD §4.2 tables, enums, indexes, and REVOKE statements.

Revision ID: 001_initial
Revises: None
Create Date: 2026-04-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ═══════════════════════════════════════════════════════════════════
# SDD §4.1 — Enum types
# ═══════════════════════════════════════════════════════════════════

ENUMS = {
    "user_role": [
        "buyer", "seller", "pro_seller", "moderator",
        "mediator", "admin", "super_admin",
    ],
    "kyc_status": ["pending", "pending_review", "verified", "rejected"],
    "ats_tier": ["starter", "trusted", "pro", "elite"],
    "listing_status": [
        "draft", "pending_moderation", "scheduled", "active",
        "ended", "sold", "unsold", "cancelled",
    ],
    "item_condition": ["new", "like_new", "good", "fair", "for_parts"],
    "auction_status": ["draft", "scheduled", "active", "ended", "cancelled"],
    "escrow_state": [
        "initiated", "payment_pending", "payment_failed", "funds_held",
        "shipping_requested", "in_transit", "inspection_period",
        "disputed", "under_review", "released", "refunded",
        "partially_released", "cancelled",
    ],
    "actor_type": ["buyer", "seller", "mediator", "admin", "system"],
    "carrier_type": ["aramex", "fetchr", "jordan_post", "other"],
    "notification_channel": ["push", "sms", "email", "whatsapp", "in_app"],
    "dispute_reason": [
        "item_not_as_described", "item_not_received", "counterfeit",
        "damaged_in_transit", "wrong_item", "other",
    ],
}


def upgrade() -> None:
    # ───────────────────────────────────────────────────────────────
    # Create all PostgreSQL enum types
    # ───────────────────────────────────────────────────────────────
    for name, values in ENUMS.items():
        vals = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({vals})")

    # ───────────────────────────────────────────────────────────────
    # Create app_user role for REVOKE statements (idempotent)
    # ───────────────────────────────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
                CREATE ROLE app_user;
            END IF;
        END $$
    """)

    # ═══════════════════════════════════════════════════════════════
    # TABLES — ordered by FK dependencies
    # ═══════════════════════════════════════════════════════════════

    # ── categories (referenced by listings) ───────────────────────
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("name_ar", sa.Text, nullable=False),
        sa.Column("name_en", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, nullable=False, unique=True),
        sa.Column("sort_order", sa.Integer, server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
    )

    # ── ngo_partners (SDD §4.1 CHARITY domain) ───────────────────
    op.create_table(
        "ngo_partners",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name_ar", sa.Text, nullable=False),
        sa.Column("name_en", sa.Text, nullable=False),
        sa.Column("registration_number", sa.Text, nullable=False, unique=True),
        sa.Column("country_code", sa.Text, server_default="JO", nullable=False),
        sa.Column("bank_account_iban", sa.Text, nullable=True),
        sa.Column("contact_phone", sa.Text, nullable=True),
        sa.Column("contact_email", sa.Text, nullable=True),
        sa.Column("logo_url", sa.Text, nullable=True),
        sa.Column("is_verified", sa.Boolean, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── users (SDD §4.2) ─────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("phone", sa.Text, nullable=False, unique=True),
        sa.Column("full_name_ar", sa.Text, nullable=False),
        sa.Column("full_name_en", sa.Text, nullable=True),
        sa.Column("email", sa.Text, nullable=True),
        sa.Column("role", sa.Enum("buyer", "seller", "pro_seller", "moderator", "mediator", "admin", "super_admin", name="user_role", create_type=False), nullable=False, server_default="buyer"),
        sa.Column("kyc_status", sa.Enum("pending", "pending_review", "verified", "rejected", name="kyc_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("kyc_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kyc_attempt_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("ats_score", sa.Integer, server_default="400", nullable=False),
        sa.Column("ats_tier", sa.Enum("starter", "trusted", "pro", "elite", name="ats_tier", create_type=False), nullable=False, server_default="trusted"),
        sa.Column("strike_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("is_suspended", sa.Boolean, server_default="false", nullable=False),
        sa.Column("is_banned", sa.Boolean, server_default="false", nullable=False),
        sa.Column("country_code", sa.Text, server_default="JO", nullable=False),
        sa.Column("preferred_language", sa.Text, server_default="ar", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("ats_score >= 0 AND ats_score <= 1000", name="ck_users_ats_range"),
    )
    # SDD §4.2 users indexes
    op.create_index("ix_users_ats_score", "users", ["ats_score"])
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_is_suspended", "users", ["is_suspended"], postgresql_where=sa.text("is_suspended = true"))

    # ── kyc_documents ─────────────────────────────────────────────
    op.create_table(
        "kyc_documents",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.Text, nullable=False),
        sa.Column("s3_key", sa.Text, nullable=False),
        sa.Column("rekognition_result", sa.Text, nullable=True),
        sa.Column("status", sa.Text, server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_kyc_documents_user_id", "kyc_documents", ["user_id"])

    # ── authentication_certs (SDD §4.1 LISTING domain) ────────────
    op.create_table(
        "authentication_certs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("expert_name", sa.Text, nullable=False),
        sa.Column("expert_credential", sa.Text, nullable=True),
        sa.Column("item_category", sa.Text, nullable=False),
        sa.Column("item_description", sa.Text, nullable=False),
        sa.Column("authenticity_verdict", sa.Text, nullable=False),
        sa.Column("confidence_level", sa.Float, nullable=True),
        sa.Column("certificate_s3_key", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("certified_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── listings (SDD §4.2) ───────────────────────────────────────
    op.create_table(
        "listings",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("seller_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title_ar", sa.Text, nullable=False),
        sa.Column("title_en", sa.Text, nullable=True),
        sa.Column("description_ar", sa.Text, nullable=False),
        sa.Column("description_en", sa.Text, nullable=True),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("condition", sa.Enum("new", "like_new", "good", "fair", "for_parts", name="item_condition", create_type=False), nullable=False),
        sa.Column("starting_price", sa.Numeric(10, 3), nullable=False),
        sa.Column("reserve_price", sa.Numeric(10, 3), nullable=True),
        sa.Column("buy_it_now_price", sa.Numeric(10, 3), nullable=True),
        sa.Column("listing_currency", sa.Text, server_default="JOD", nullable=False),
        sa.Column("status", sa.Enum("draft", "pending_moderation", "scheduled", "active", "ended", "sold", "unsold", "cancelled", name="listing_status", create_type=False), nullable=False, server_default="draft"),
        sa.Column("ai_generated", sa.Boolean, server_default="false", nullable=False),
        sa.Column("ai_price_low", sa.Numeric(10, 3), nullable=True),
        sa.Column("ai_price_high", sa.Numeric(10, 3), nullable=True),
        sa.Column("phash", sa.Text, nullable=True),
        sa.Column("moderation_score", sa.Float, nullable=True),
        sa.Column("authentication_cert_id", UUID(as_uuid=False), sa.ForeignKey("authentication_certs.id"), nullable=True),
        sa.Column("is_charity", sa.Boolean, server_default="false", nullable=False),
        sa.Column("ngo_id", UUID(as_uuid=False), sa.ForeignKey("ngo_partners.id"), nullable=True),
        sa.Column("image_urls", ARRAY(sa.Text), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("starting_price > 0", name="ck_listings_starting_price_positive"),
    )
    # SDD §4.2 listings indexes
    op.create_index("ix_listings_seller_id", "listings", ["seller_id"])
    op.create_index("ix_listings_status", "listings", ["status"])
    op.create_index("ix_listings_category_id", "listings", ["category_id"])
    op.create_index("ix_listings_is_charity", "listings", ["is_charity"], postgresql_where=sa.text("is_charity = true"))

    # ── auctions (SDD §4.2) ──────────────────────────────────────
    op.create_table(
        "auctions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("listing_id", UUID(as_uuid=False), sa.ForeignKey("listings.id"), nullable=False, unique=True),
        sa.Column("status", sa.Enum("draft", "scheduled", "active", "ended", "cancelled", name="auction_status", create_type=False), nullable=False, server_default="scheduled"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_price", sa.Numeric(10, 3), nullable=False),
        sa.Column("min_increment", sa.Numeric(10, 3), server_default="25", nullable=False),
        sa.Column("bid_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("extension_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("winner_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("final_price", sa.Numeric(10, 3), nullable=True),
        sa.Column("reserve_met", sa.Boolean, nullable=True),
        sa.Column("redis_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    # SDD §4.2 auctions indexes
    op.create_index("ix_auctions_status", "auctions", ["status"])
    op.create_index("ix_auctions_starts_at", "auctions", ["starts_at"])
    op.create_index("ix_auctions_winner_id", "auctions", ["winner_id"], postgresql_where=sa.text("winner_id IS NOT NULL"))

    # ── bids (SDD §4.2 — APPEND-ONLY) ────────────────────────────
    op.create_table(
        "bids",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("auction_id", UUID(as_uuid=False), sa.ForeignKey("auctions.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Numeric(10, 3), nullable=False),
        sa.Column("currency", sa.Text, server_default="JOD", nullable=False),
        sa.Column("is_proxy", sa.Boolean, server_default="false", nullable=False),
        sa.Column("fraud_score", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_bids_amount_positive"),
    )
    # SDD §4.2 bids indexes
    op.create_index("ix_bids_auction_id", "bids", ["auction_id"])
    op.create_index("ix_bids_user_id", "bids", ["user_id"])
    op.create_index("ix_bids_created_at_desc", "bids", [sa.text("created_at DESC")])

    # ── proxy_bids ────────────────────────────────────────────────
    op.create_table(
        "proxy_bids",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("auction_id", UUID(as_uuid=False), sa.ForeignKey("auctions.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("max_amount", sa.Numeric(10, 3), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_proxy_bids_auction_id", "proxy_bids", ["auction_id"])

    # ── escrows (SDD §4.2) ───────────────────────────────────────
    op.create_table(
        "escrows",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("auction_id", UUID(as_uuid=False), sa.ForeignKey("auctions.id"), nullable=False, unique=True),
        sa.Column("winner_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("seller_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("mediator_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("state", sa.Enum("initiated", "payment_pending", "payment_failed", "funds_held", "shipping_requested", "in_transit", "inspection_period", "disputed", "under_review", "released", "refunded", "partially_released", "cancelled", name="escrow_state", create_type=False), nullable=False, server_default="initiated"),
        sa.Column("amount", sa.Numeric(10, 3), nullable=False),
        sa.Column("currency", sa.Text, server_default="JOD", nullable=False),
        sa.Column("seller_amount", sa.Numeric(10, 3), nullable=True),
        sa.Column("payment_intent_id", sa.Text, nullable=True),
        sa.Column("payment_link", sa.Text, nullable=True),
        sa.Column("tracking_number", sa.Text, nullable=True),
        sa.Column("carrier", sa.Enum("aramex", "fetchr", "jordan_post", "other", name="carrier_type", create_type=False), nullable=True),
        sa.Column("dispute_reason", sa.Text, nullable=True),
        sa.Column("evidence_s3_keys", ARRAY(sa.Text), nullable=True),
        sa.Column("evidence_hashes", ARRAY(sa.Text), nullable=True),
        sa.Column("payment_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipping_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inspection_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    # SDD §4.2 escrows indexes
    op.create_index("ix_escrows_state", "escrows", ["state"])
    op.create_index("ix_escrows_winner_id", "escrows", ["winner_id"])
    op.create_index("ix_escrows_seller_id", "escrows", ["seller_id"])
    op.create_index("ix_escrows_payment_deadline", "escrows", ["payment_deadline"])

    # ── escrow_events (SDD §4.2 — APPEND-ONLY PERMANENT) ─────────
    op.create_table(
        "escrow_events",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("escrow_id", UUID(as_uuid=False), sa.ForeignKey("escrows.id"), nullable=False),
        sa.Column("from_state", sa.Text, nullable=False),
        sa.Column("to_state", sa.Text, nullable=False),
        sa.Column("actor_id", UUID(as_uuid=False), nullable=True),
        sa.Column("actor_type", sa.Enum("buyer", "seller", "mediator", "admin", "system", name="actor_type", create_type=False), nullable=False),
        sa.Column("trigger", sa.Text, nullable=False),
        sa.Column("meta", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    # SDD §4.2 escrow_events indexes
    op.create_index("ix_escrow_events_escrow_id", "escrow_events", ["escrow_id"])
    op.create_index("ix_escrow_events_created_at", "escrow_events", ["created_at"])

    # ── shipments (SDD §4.1 ESCROW domain) ────────────────────────
    op.create_table(
        "shipments",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("escrow_id", UUID(as_uuid=False), sa.ForeignKey("escrows.id"), nullable=False, unique=True),
        sa.Column("carrier", sa.Enum("aramex", "fetchr", "jordan_post", "other", name="carrier_type", create_type=False), nullable=False),
        sa.Column("tracking_number", sa.Text, nullable=False),
        sa.Column("label_s3_key", sa.Text, nullable=True),
        sa.Column("sender_address", JSONB, nullable=True),
        sa.Column("receiver_address", JSONB, nullable=True),
        sa.Column("weight_kg", sa.Float, nullable=True),
        sa.Column("shipping_cost", sa.Numeric(10, 3), nullable=True),
        sa.Column("estimated_delivery", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_delivery", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text, server_default="pending", nullable=False),
        sa.Column("carrier_status_raw", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── disputes (SDD §4.1 ESCROW domain) ─────────────────────────
    op.create_table(
        "disputes",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("escrow_id", UUID(as_uuid=False), sa.ForeignKey("escrows.id"), nullable=False),
        sa.Column("filed_by", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Enum("item_not_as_described", "item_not_received", "counterfeit", "damaged_in_transit", "wrong_item", "other", name="dispute_reason", create_type=False), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("evidence_s3_keys", ARRAY(sa.Text), nullable=True),
        sa.Column("evidence_hashes", ARRAY(sa.Text), nullable=True),
        sa.Column("mediator_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolution", sa.Text, nullable=True),
        sa.Column("resolution_amount_buyer", sa.Numeric(10, 3), nullable=True),
        sa.Column("resolution_amount_seller", sa.Numeric(10, 3), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_disputes_escrow_id", "disputes", ["escrow_id"])

    # ── notifications (SDD §4.1 NOTIFICATION domain) ──────────────
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("channel", sa.Enum("push", "sms", "email", "whatsapp", "in_app", name="notification_channel", create_type=False), nullable=False),
        sa.Column("title_ar", sa.Text, nullable=False),
        sa.Column("title_en", sa.Text, nullable=False),
        sa.Column("body_ar", sa.Text, nullable=False),
        sa.Column("body_en", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("is_read", sa.Boolean, server_default="false", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])

    # ── notification_preferences ──────────────────────────────────
    op.create_table(
        "notification_preferences",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("push_enabled", sa.Boolean, server_default="true", nullable=False),
        sa.Column("sms_enabled", sa.Boolean, server_default="true", nullable=False),
        sa.Column("email_enabled", sa.Boolean, server_default="true", nullable=False),
        sa.Column("whatsapp_enabled", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── ratings (SDD §4.1) ────────────────────────────────────────
    op.create_table(
        "ratings",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("escrow_id", UUID(as_uuid=False), sa.ForeignKey("escrows.id"), nullable=False),
        sa.Column("rater_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rated_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_ratings_score_range"),
        sa.UniqueConstraint("escrow_id", "rater_id", name="uq_ratings_escrow_rater"),
    )
    op.create_index("ix_ratings_rated_id", "ratings", ["rated_id"])

    # ── zakat_receipts (SDD §4.1 CHARITY domain) ──────────────────
    op.create_table(
        "zakat_receipts",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("ngo_id", UUID(as_uuid=False), sa.ForeignKey("ngo_partners.id"), nullable=False),
        sa.Column("auction_id", UUID(as_uuid=False), sa.ForeignKey("auctions.id"), nullable=False),
        sa.Column("amount", sa.Numeric(10, 3), nullable=False),
        sa.Column("currency", sa.Text, server_default="JOD", nullable=False),
        sa.Column("receipt_pdf_s3_key", sa.Text, nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_zakat_receipts_user_id", "zakat_receipts", ["user_id"])

    # ── b2b_rooms (SDD §4.1 B2B domain) ──────────────────────────
    op.create_table(
        "b2b_rooms",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title_ar", sa.Text, nullable=False),
        sa.Column("title_en", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("min_bid", sa.Numeric(10, 3), server_default="10000", nullable=False),
        sa.Column("requires_kyc", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── admin_audit_log (SDD §4.1 ADMIN domain) ──────────────────
    op.create_table(
        "admin_audit_log",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("admin_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("target_type", sa.Text, nullable=False),
        sa.Column("target_id", UUID(as_uuid=False), nullable=True),
        sa.Column("meta", JSONB, nullable=True),
        sa.Column("ip_address", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_admin_audit_log_admin_id", "admin_audit_log", ["admin_id"])
    op.create_index("ix_admin_audit_log_created_at", "admin_audit_log", ["created_at"])

    # ── moderation_queue (SDD §4.1 ADMIN domain) ─────────────────
    op.create_table(
        "moderation_queue",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("listing_id", UUID(as_uuid=False), sa.ForeignKey("listings.id"), nullable=False),
        sa.Column("assigned_to", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("ai_score", sa.Float, nullable=True),
        sa.Column("ai_flags", ARRAY(sa.Text), nullable=True),
        sa.Column("decision", sa.Text, nullable=True),
        sa.Column("decision_reason", sa.Text, nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_moderation_queue_listing_id", "moderation_queue", ["listing_id"])

    # ── ai_requests (audit log for AI service calls) ──────────────
    op.create_table(
        "ai_requests",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("request_type", sa.Text, nullable=False),
        sa.Column("user_id", UUID(as_uuid=False), nullable=True),
        sa.Column("listing_id", UUID(as_uuid=False), nullable=True),
        sa.Column("input_payload", JSONB, nullable=True),
        sa.Column("output_payload", JSONB, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("status", sa.Text, server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_ai_requests_request_type", "ai_requests", ["request_type"])
    op.create_index("ix_ai_requests_user_id", "ai_requests", ["user_id"])

    # ═══════════════════════════════════════════════════════════════
    # APPEND-ONLY enforcement — SDD §4.2
    # REVOKE UPDATE, DELETE on financial audit tables
    # ═══════════════════════════════════════════════════════════════
    op.execute("REVOKE UPDATE, DELETE ON bids FROM app_user")
    op.execute("REVOKE UPDATE, DELETE ON escrow_events FROM app_user")

    # Prevent TRUNCATE on escrow_events via trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_truncate()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'TRUNCATE is not allowed on append-only table %', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_no_truncate_bids
        BEFORE TRUNCATE ON bids
        FOR EACH STATEMENT EXECUTE FUNCTION prevent_truncate()
    """)
    op.execute("""
        CREATE TRIGGER trg_no_truncate_escrow_events
        BEFORE TRUNCATE ON escrow_events
        FOR EACH STATEMENT EXECUTE FUNCTION prevent_truncate()
    """)

    # ═══════════════════════════════════════════════════════════════
    # updated_at auto-trigger (SDD §4.2 — "trigger-maintained")
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    for table in [
        "users", "listings", "auctions", "escrows", "shipments",
        "disputes", "notifications", "notification_preferences",
        "kyc_documents", "ngo_partners", "b2b_rooms", "ai_requests",
    ]:
        op.execute(f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at()
        """)


def downgrade() -> None:
    # Drop tables in reverse dependency order
    tables = [
        "ai_requests", "moderation_queue", "admin_audit_log",
        "b2b_rooms", "zakat_receipts", "ratings",
        "notification_preferences", "notifications",
        "disputes", "shipments", "escrow_events", "escrows",
        "proxy_bids", "bids", "auctions", "listings",
        "authentication_certs", "kyc_documents", "users",
        "ngo_partners", "categories",
    ]
    for t in tables:
        op.drop_table(t)

    # Drop functions
    op.execute("DROP FUNCTION IF EXISTS update_updated_at() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS prevent_truncate() CASCADE")

    # Drop enums
    for name in reversed(list(ENUMS.keys())):
        op.execute(f"DROP TYPE IF EXISTS {name}")
