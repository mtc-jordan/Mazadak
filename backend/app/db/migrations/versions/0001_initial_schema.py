"""Complete MZADAK schema — all tables, enums, indexes, triggers, REVOKE.

Revision ID: 0001_initial
Revises: None
Create Date: 2026-04-07

Money columns use INTEGER (cents/fils) — 1 JOD = 1000 fils.
Append-only tables (bids, escrow_events) have REVOKE UPDATE/DELETE.
updated_at trigger auto-maintained on mutable tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# =====================================================================
# ENUM DEFINITIONS
# =====================================================================

ENUMS: dict[str, list[str]] = {
    "user_role": ["buyer", "seller", "admin", "superadmin"],

    "user_status": ["pending_kyc", "active", "suspended", "banned"],

    "kyc_status": [
        "not_started", "pending", "pending_review", "verified", "rejected",
    ],

    "listing_status": [
        "draft", "pending_review", "active", "ended", "cancelled", "relisted",
    ],

    "listing_condition": [
        "brand_new", "like_new", "very_good", "good", "acceptable",
    ],

    "auction_status": ["scheduled", "active", "ended", "cancelled"],

    "escrow_status": [
        "payment_pending", "funds_held", "shipping_requested",
        "label_generated", "shipped", "in_transit", "delivered",
        "inspection_period", "released", "disputed", "under_review",
        "resolved_released", "resolved_refunded", "resolved_split", "cancelled",
    ],

    "dispute_reason": [
        "not_as_described", "not_received", "damaged",
        "counterfeit", "wrong_item", "other",
    ],

    "dispute_status": [
        "open", "under_review", "resolved_buyer", "resolved_seller",
        "resolved_split", "closed",
    ],

    "notification_channel": ["push", "whatsapp", "sms", "email"],

    "notification_event": [
        "outbid", "won", "lost", "auction_starting", "auction_ending",
        "payment_request", "payment_received", "payment_failed",
        "shipping_requested", "shipped", "delivered",
        "inspection_started", "escrow_released", "escrow_refunded",
        "dispute_opened", "dispute_resolved", "kyc_approved",
        "kyc_rejected", "new_bid", "proxy_outbid",
    ],

    "payment_status": [
        "pending", "captured", "failed", "refunded", "partially_refunded",
    ],

    "bid_status": ["accepted", "rejected", "retracted"],
}


def upgrade() -> None:
    # -----------------------------------------------------------------
    # 1. Create all PostgreSQL enum types
    # -----------------------------------------------------------------
    for name, values in ENUMS.items():
        vals = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({vals})")

    # -----------------------------------------------------------------
    # 2. Create mzadak_app_role (idempotent)
    # -----------------------------------------------------------------
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mzadak_app_role') THEN
                CREATE ROLE mzadak_app_role;
            END IF;
        END $$
    """)

    # =================================================================
    # TABLES  (ordered by FK dependencies)
    # =================================================================

    # -- categories ---------------------------------------------------
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name_en", sa.String(100), nullable=False),
        sa.Column("name_ar", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("icon_url", sa.String(500), nullable=True),
        sa.Column("sort_order", sa.Integer, server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
    )

    # -- ngo_partners -------------------------------------------------
    op.create_table(
        "ngo_partners",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name_en", sa.String(200), nullable=False),
        sa.Column("name_ar", sa.String(200), nullable=False),
        sa.Column("logo_s3_key", sa.String(500), nullable=True),
        sa.Column("is_zakat_eligible", sa.Boolean, server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("checkout_merchant_id", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # -- users --------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("phone", sa.String(20), nullable=False, unique=True),
        sa.Column("phone_verified", sa.Boolean, server_default="false", nullable=False),
        sa.Column("email", sa.String(255), nullable=True, unique=True),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("full_name_ar", sa.String(255), nullable=True),
        sa.Column("role", sa.Enum("buyer", "seller", "admin", "superadmin", name="user_role", create_type=False), nullable=False, server_default="buyer"),
        sa.Column("status", sa.Enum("pending_kyc", "active", "suspended", "banned", name="user_status", create_type=False), nullable=False, server_default="pending_kyc"),
        sa.Column("kyc_status", sa.Enum("not_started", "pending", "pending_review", "verified", "rejected", name="kyc_status", create_type=False), nullable=False, server_default="not_started"),
        sa.Column("kyc_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kyc_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kyc_rejection_reason", sa.Text, nullable=True),
        # -- ATS (Auction Trust Score) composite ----------------------
        sa.Column("ats_score", sa.Integer, server_default="400", nullable=False),
        sa.Column("ats_identity_score", sa.Integer, server_default="0", nullable=False),
        sa.Column("ats_completion_score", sa.Integer, server_default="400", nullable=False),
        sa.Column("ats_speed_score", sa.Integer, server_default="400", nullable=False),
        sa.Column("ats_rating_score", sa.Integer, server_default="400", nullable=False),
        sa.Column("ats_quality_score", sa.Integer, server_default="400", nullable=False),
        sa.Column("ats_dispute_score", sa.Integer, server_default="400", nullable=False),
        sa.Column("strike_count", sa.Integer, server_default="0", nullable=False),
        # -- Pro seller -----------------------------------------------
        sa.Column("is_pro_seller", sa.Boolean, server_default="false", nullable=False),
        sa.Column("pro_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commission_rate", sa.Numeric(5, 4), server_default="0.0500", nullable=False),
        # -- WhatsApp bot link ----------------------------------------
        sa.Column("fcm_tokens", JSONB, server_default="'[]'", nullable=False),
        sa.Column("whatsapp_linked", sa.Boolean, server_default="false", nullable=False),
        sa.Column("whatsapp_linked_at", sa.DateTime(timezone=True), nullable=True),
        # -- Preferences & tracking -----------------------------------
        sa.Column("preferred_language", sa.String(5), server_default="ar", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("ats_score >= 0 AND ats_score <= 1000", name="ck_users_ats_range"),
    )
    op.create_index("ix_users_phone", "users", ["phone"], unique=True)
    op.create_index("ix_users_status", "users", ["status"])
    op.create_index("ix_users_ats_score_desc", "users", [sa.text("ats_score DESC")])

    # -- user_kyc_documents -------------------------------------------
    op.create_table(
        "user_kyc_documents",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("s3_key", sa.String(500), nullable=False),
        sa.Column("rekognition_confidence", sa.Numeric(5, 2), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_user_kyc_documents_user_id", "user_kyc_documents", ["user_id"])

    # -- refresh_tokens -----------------------------------------------
    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_info", JSONB, nullable=True),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)

    # -- listings -----------------------------------------------------
    op.create_table(
        "listings",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("seller_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("title_en", sa.String(200), nullable=False),
        sa.Column("title_ar", sa.String(200), nullable=False),
        sa.Column("description_en", sa.Text, nullable=True),
        sa.Column("description_ar", sa.Text, nullable=True),
        sa.Column("condition", sa.Enum("brand_new", "like_new", "very_good", "good", "acceptable", name="listing_condition", create_type=False), nullable=False),
        sa.Column("status", sa.Enum("draft", "pending_review", "active", "ended", "cancelled", "relisted", name="listing_status", create_type=False), nullable=False, server_default="draft"),
        sa.Column("is_certified", sa.Boolean, server_default="false", nullable=False),
        sa.Column("is_charity", sa.Boolean, server_default="false", nullable=False),
        sa.Column("ngo_id", sa.Integer, sa.ForeignKey("ngo_partners.id"), nullable=True),
        # -- Prices in INTEGER cents ----------------------------------
        sa.Column("starting_price", sa.Integer, nullable=False),
        sa.Column("reserve_price", sa.Integer, nullable=True),
        sa.Column("buy_it_now_price", sa.Integer, nullable=True),
        sa.Column("current_price", sa.Integer, nullable=True),
        sa.Column("bid_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("watcher_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("min_increment", sa.Integer, server_default="2500", nullable=False),
        # -- Schedule --------------------------------------------------
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extension_count", sa.Integer, server_default="0", nullable=False),
        # -- Location --------------------------------------------------
        sa.Column("location_city", sa.String(100), nullable=True),
        sa.Column("location_country", sa.String(5), server_default="JO", nullable=False),
        # -- AI / moderation ------------------------------------------
        sa.Column("ai_generated", sa.Boolean, server_default="false", nullable=False),
        sa.Column("ai_category_confidence", sa.Numeric(5, 2), nullable=True),
        sa.Column("moderation_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("moderation_status", sa.String(50), server_default="pending", nullable=False),
        sa.Column("moderation_flags", JSONB, server_default="'[]'", nullable=False),
        sa.Column("phash", sa.String(64), nullable=True),
        sa.Column("view_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("starting_price > 0", name="ck_listings_starting_price_positive"),
    )
    op.create_index("ix_listings_status_ends_at", "listings", ["status", "ends_at"])
    op.create_index("ix_listings_seller_id", "listings", ["seller_id"])
    op.create_index("ix_listings_category_status", "listings", ["category_id", "status"])
    op.create_index("ix_listings_phash", "listings", ["phash"], postgresql_where=sa.text("phash IS NOT NULL"))

    # -- listing_images -----------------------------------------------
    op.create_table(
        "listing_images",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("listing_id", UUID(as_uuid=False), sa.ForeignKey("listings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("s3_key", sa.String(500), nullable=False),
        sa.Column("s3_key_thumb_100", sa.String(500), nullable=True),
        sa.Column("s3_key_thumb_400", sa.String(500), nullable=True),
        sa.Column("s3_key_thumb_800", sa.String(500), nullable=True),
        sa.Column("display_order", sa.Integer, nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_listing_images_listing_id", "listing_images", ["listing_id"])

    # -- auctions -----------------------------------------------------
    op.create_table(
        "auctions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("listing_id", UUID(as_uuid=False), sa.ForeignKey("listings.id"), nullable=False, unique=True),
        sa.Column("seller_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("winner_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.Enum("scheduled", "active", "ended", "cancelled", name="auction_status", create_type=False), nullable=False, server_default="scheduled"),
        sa.Column("final_price", sa.Integer, nullable=True),
        sa.Column("redis_initialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redis_expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_auctions_status", "auctions", ["status"])
    op.create_index("ix_auctions_listing_id", "auctions", ["listing_id"], unique=True)
    op.create_index("ix_auctions_seller_id", "auctions", ["seller_id"])

    # -- bids  (APPEND-ONLY) ------------------------------------------
    op.create_table(
        "bids",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("listing_id", UUID(as_uuid=False), sa.ForeignKey("listings.id"), nullable=False),
        sa.Column("auction_id", UUID(as_uuid=False), sa.ForeignKey("auctions.id"), nullable=False),
        sa.Column("bidder_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Integer, nullable=False),
        sa.Column("status", sa.Enum("accepted", "rejected", "retracted", name="bid_status", create_type=False), nullable=False, server_default="accepted"),
        sa.Column("rejection_reason", sa.String(100), nullable=True),
        sa.Column("is_proxy", sa.Boolean, server_default="false", nullable=False),
        sa.Column("proxy_max", sa.Integer, nullable=True),
        sa.Column("ip_address", INET, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_bids_amount_positive"),
    )
    op.create_index("ix_bids_listing_created", "bids", ["listing_id", sa.text("created_at DESC")])
    op.create_index("ix_bids_bidder_id", "bids", ["bidder_id"])
    op.create_index("ix_bids_auction_id", "bids", ["auction_id"])

    # -- escrows  (12-state FSM) --------------------------------------
    op.create_table(
        "escrows",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("auction_id", UUID(as_uuid=False), sa.ForeignKey("auctions.id"), nullable=False, unique=True),
        sa.Column("listing_id", UUID(as_uuid=False), sa.ForeignKey("listings.id"), nullable=False),
        sa.Column("buyer_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("seller_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        # -- Money (INTEGER cents) ------------------------------------
        sa.Column("amount", sa.Integer, nullable=False),
        sa.Column("platform_fee", sa.Integer, nullable=False),
        sa.Column("seller_payout", sa.Integer, nullable=False),
        # -- State machine --------------------------------------------
        sa.Column("state", sa.Enum(
            "payment_pending", "funds_held", "shipping_requested",
            "label_generated", "shipped", "in_transit", "delivered",
            "inspection_period", "released", "disputed", "under_review",
            "resolved_released", "resolved_refunded", "resolved_split", "cancelled",
            name="escrow_status", create_type=False,
        ), nullable=False, server_default="payment_pending"),
        # -- Payment --------------------------------------------------
        sa.Column("checkout_payment_id", sa.String(200), nullable=True),
        sa.Column("checkout_payment_intent_id", sa.String(200), nullable=True),
        # -- Shipping -------------------------------------------------
        sa.Column("tracking_number", sa.String(200), nullable=True),
        sa.Column("carrier", sa.String(100), nullable=True),
        sa.Column("tracking_url", sa.String(500), nullable=True),
        # -- Deadlines ------------------------------------------------
        sa.Column("payment_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipping_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inspection_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_deadline", sa.DateTime(timezone=True), nullable=True),
        # -- Transition tracking --------------------------------------
        sa.Column("last_transition_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transition_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_escrows_state", "escrows", ["state"])
    op.create_index("ix_escrows_buyer_id", "escrows", ["buyer_id"])
    op.create_index("ix_escrows_seller_id", "escrows", ["seller_id"])
    op.create_index("ix_escrows_payment_deadline", "escrows", ["payment_deadline"])

    # -- escrow_events  (APPEND-ONLY audit trail) ---------------------
    op.create_table(
        "escrow_events",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("escrow_id", UUID(as_uuid=False), sa.ForeignKey("escrows.id"), nullable=False),
        sa.Column("from_state", sa.Enum(
            "payment_pending", "funds_held", "shipping_requested",
            "label_generated", "shipped", "in_transit", "delivered",
            "inspection_period", "released", "disputed", "under_review",
            "resolved_released", "resolved_refunded", "resolved_split", "cancelled",
            name="escrow_status", create_type=False,
        ), nullable=False),
        sa.Column("to_state", sa.Enum(
            "payment_pending", "funds_held", "shipping_requested",
            "label_generated", "shipped", "in_transit", "delivered",
            "inspection_period", "released", "disputed", "under_review",
            "resolved_released", "resolved_refunded", "resolved_split", "cancelled",
            name="escrow_status", create_type=False,
        ), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("trigger", sa.String(100), nullable=False),
        sa.Column("metadata", JSONB, server_default="'{}'", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_escrow_events_escrow_created", "escrow_events", ["escrow_id", "created_at"])

    # -- disputes -----------------------------------------------------
    op.create_table(
        "disputes",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("escrow_id", UUID(as_uuid=False), sa.ForeignKey("escrows.id"), nullable=False),
        sa.Column("buyer_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("seller_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Enum("not_as_described", "not_received", "damaged", "counterfeit", "wrong_item", "other", name="dispute_reason", create_type=False), nullable=False),
        sa.Column("reason_detail", sa.Text, nullable=True),
        sa.Column("desired_resolution", sa.String(50), nullable=True),
        sa.Column("status", sa.Enum("open", "under_review", "resolved_buyer", "resolved_seller", "resolved_split", "closed", name="dispute_status", create_type=False), nullable=False, server_default="open"),
        sa.Column("admin_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("admin_ruling", sa.Text, nullable=True),
        sa.Column("admin_ruled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_resolution_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("buyer_evidence_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("seller_evidence_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_disputes_escrow_id", "disputes", ["escrow_id"])
    op.create_index("ix_disputes_status", "disputes", ["status"])

    # -- dispute_evidence ---------------------------------------------
    op.create_table(
        "dispute_evidence",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("dispute_id", UUID(as_uuid=False), sa.ForeignKey("disputes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploader_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("uploader_role", sa.String(10), nullable=False),
        sa.Column("s3_key", sa.String(500), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_dispute_evidence_dispute_id", "dispute_evidence", ["dispute_id"])

    # -- notifications ------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_type", sa.Enum(
            "outbid", "won", "lost", "auction_starting", "auction_ending",
            "payment_request", "payment_received", "payment_failed",
            "shipping_requested", "shipped", "delivered",
            "inspection_started", "escrow_released", "escrow_refunded",
            "dispute_opened", "dispute_resolved", "kyc_approved",
            "kyc_rejected", "new_bid", "proxy_outbid",
            name="notification_event", create_type=False,
        ), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=False), nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("title_en", sa.String(200), nullable=True),
        sa.Column("title_ar", sa.String(200), nullable=True),
        sa.Column("body_en", sa.Text, nullable=True),
        sa.Column("body_ar", sa.Text, nullable=True),
        sa.Column("data", JSONB, server_default="'{}'", nullable=False),
        sa.Column("is_read", sa.Boolean, server_default="false", nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("channels_sent", JSONB, server_default="'[]'", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_notifications_user_read_created", "notifications", ["user_id", "is_read", sa.text("created_at DESC")])
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", sa.text("created_at DESC")])

    # -- ratings ------------------------------------------------------
    op.create_table(
        "ratings",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("escrow_id", UUID(as_uuid=False), sa.ForeignKey("escrows.id"), nullable=False, unique=True),
        sa.Column("rater_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("ratee_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("is_anonymous", sa.Boolean, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_ratings_score_range"),
    )
    op.create_index("ix_ratings_ratee_id", "ratings", ["ratee_id"])

    # -- zakat_receipts -----------------------------------------------
    op.create_table(
        "zakat_receipts",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("escrow_id", UUID(as_uuid=False), sa.ForeignKey("escrows.id"), nullable=False),
        sa.Column("ngo_id", sa.Integer, sa.ForeignKey("ngo_partners.id"), nullable=False),
        sa.Column("buyer_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Integer, nullable=False),
        sa.Column("receipt_number", sa.String(100), nullable=False, unique=True),
        sa.Column("pdf_s3_key", sa.String(500), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_zakat_receipts_buyer_id", "zakat_receipts", ["buyer_id"])

    # -- b2b_rooms ----------------------------------------------------
    op.create_table(
        "b2b_rooms",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_name", sa.String(300), nullable=False),
        sa.Column("client_name_ar", sa.String(300), nullable=True),
        sa.Column("tender_reference", sa.String(200), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("documents", JSONB, server_default="'[]'", nullable=False),
        sa.Column("status", sa.String(50), server_default="open", nullable=False),
        sa.Column("submission_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("results_announced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # -- b2b_bids -----------------------------------------------------
    op.create_table(
        "b2b_bids",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("room_id", UUID(as_uuid=False), sa.ForeignKey("b2b_rooms.id"), nullable=False),
        sa.Column("bidder_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Integer, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("validity_days", sa.Integer, nullable=False),
        sa.Column("attachments", JSONB, server_default="'[]'", nullable=False),
        sa.Column("is_winner", sa.Boolean, server_default="false", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_b2b_bids_amount_positive"),
    )
    op.create_index("ix_b2b_bids_room_id", "b2b_bids", ["room_id"])
    op.create_index("ix_b2b_bids_bidder_id", "b2b_bids", ["bidder_id"])

    # -- admin_audit_log ----------------------------------------------
    op.create_table(
        "admin_audit_log",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("admin_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(200), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=True),
        sa.Column("entity_id", UUID(as_uuid=False), nullable=True),
        sa.Column("before_state", JSONB, nullable=True),
        sa.Column("after_state", JSONB, nullable=True),
        sa.Column("ip_address", INET, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_admin_audit_admin_created", "admin_audit_log", ["admin_id", sa.text("created_at DESC")])
    op.create_index("ix_admin_audit_entity", "admin_audit_log", ["entity_type", "entity_id"])

    # -- proxy_bids ---------------------------------------------------
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

    # -- ai_requests --------------------------------------------------
    op.create_table(
        "ai_requests",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("request_type", sa.String(50), nullable=False),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("listing_id", UUID(as_uuid=False), sa.ForeignKey("listings.id"), nullable=True),
        sa.Column("input_payload", JSONB, nullable=True),
        sa.Column("output_payload", JSONB, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_ai_requests_user_id", "ai_requests", ["user_id"])

    # -- wa_accounts --------------------------------------------------
    op.create_table(
        "wa_accounts",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("wa_phone", sa.String(20), nullable=False, unique=True),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_wa_accounts_wa_phone", "wa_accounts", ["wa_phone"], unique=True)
    op.create_index("ix_wa_accounts_user_id", "wa_accounts", ["user_id"])
    op.create_index("ix_wa_accounts_phone_active", "wa_accounts", ["wa_phone", "is_active"])

    # -- bot_conversations --------------------------------------------
    op.create_table(
        "bot_conversations",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("wa_phone", sa.String(20), nullable=False),
        sa.Column("state", sa.String(50), server_default="idle", nullable=False),
        sa.Column("intent", sa.String(20), server_default="unknown", nullable=False),
        sa.Column("context_auction_ids", sa.Text, nullable=True),
        sa.Column("context_amount", sa.Float, nullable=True),
        sa.Column("context_keyword", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_bot_conversations_wa_phone", "bot_conversations", ["wa_phone"])

    # -- notification_preferences -------------------------------------
    op.create_table(
        "notification_preferences",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("push_enabled", sa.Boolean, server_default="true", nullable=False),
        sa.Column("sms_enabled", sa.Boolean, server_default="true", nullable=False),
        sa.Column("email_enabled", sa.Boolean, server_default="true", nullable=False),
        sa.Column("whatsapp_enabled", sa.Boolean, server_default="true", nullable=False),
    )
    op.create_index("ix_notification_preferences_user_id", "notification_preferences", ["user_id"], unique=True)

    # =================================================================
    # APPEND-ONLY enforcement
    # =================================================================
    op.execute("REVOKE UPDATE, DELETE ON bids FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON escrow_events FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON bids FROM mzadak_app_role")
    op.execute("REVOKE UPDATE, DELETE ON escrow_events FROM mzadak_app_role")

    # Prevent TRUNCATE via trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_truncate()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'TRUNCATE is not allowed on append-only table %', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER trg_no_truncate_bids BEFORE TRUNCATE ON bids FOR EACH STATEMENT EXECUTE FUNCTION prevent_truncate()")
    op.execute("CREATE TRIGGER trg_no_truncate_escrow_events BEFORE TRUNCATE ON escrow_events FOR EACH STATEMENT EXECUTE FUNCTION prevent_truncate()")

    # =================================================================
    # updated_at auto-trigger
    # =================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ["users", "listings", "escrows", "disputes",
                  "proxy_bids", "ai_requests", "wa_accounts", "bot_conversations"]:
        op.execute(f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION update_updated_at()")

    # =================================================================
    # GRANT minimal permissions to mzadak_app_role
    # =================================================================
    _all_tables = [
        "categories", "ngo_partners", "users", "user_kyc_documents",
        "refresh_tokens", "listings", "listing_images", "auctions",
        "bids", "escrows", "escrow_events", "disputes", "dispute_evidence",
        "notifications", "ratings", "zakat_receipts",
        "b2b_rooms", "b2b_bids", "admin_audit_log",
        "proxy_bids", "ai_requests", "wa_accounts", "bot_conversations",
        "notification_preferences",
    ]
    for t in _all_tables:
        op.execute(f"GRANT SELECT, INSERT ON {t} TO mzadak_app_role")
    # Mutable tables also get UPDATE
    for t in ["users", "listings", "auctions", "escrows", "disputes",
              "notifications", "ratings", "b2b_rooms", "b2b_bids",
              "proxy_bids", "ai_requests", "wa_accounts", "bot_conversations"]:
        op.execute(f"GRANT UPDATE ON {t} TO mzadak_app_role")
    # Sequence permissions for SERIAL PKs
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mzadak_app_role")

    # =================================================================
    # Seed categories
    # =================================================================
    op.execute("""
        INSERT INTO categories (name_en, name_ar, slug, sort_order) VALUES
        ('Electronics',      'إلكترونيات',       'electronics',      1),
        ('Vehicles',         'مركبات',           'vehicles',          2),
        ('Jewelry & Watches','مجوهرات وساعات',   'jewelry-watches',   3),
        ('Art & Collectibles','فن ومقتنيات',     'art-collectibles',  4),
        ('Fashion',          'أزياء',            'fashion',           5),
        ('Antiques',         'تحف وأنتيكات',     'antiques',          6),
        ('Real Estate',      'عقارات',           'real-estate',       7),
        ('Charity',          'خيري',             'charity',           8)
    """)


def downgrade() -> None:
    # Drop tables in reverse dependency order
    tables = [
        "notification_preferences", "bot_conversations", "wa_accounts",
        "ai_requests", "proxy_bids",
        "admin_audit_log", "b2b_bids", "b2b_rooms",
        "zakat_receipts", "ratings",
        "notifications",
        "dispute_evidence", "disputes",
        "escrow_events", "escrows",
        "bids", "auctions",
        "listing_images", "listings",
        "refresh_tokens", "user_kyc_documents", "users",
        "ngo_partners", "categories",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")

    # Drop functions
    op.execute("DROP FUNCTION IF EXISTS update_updated_at() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS prevent_truncate() CASCADE")

    # Drop role
    op.execute("DROP ROLE IF EXISTS mzadak_app_role")

    # Drop enums in reverse
    for name in reversed(list(ENUMS.keys())):
        op.execute(f"DROP TYPE IF EXISTS {name}")
