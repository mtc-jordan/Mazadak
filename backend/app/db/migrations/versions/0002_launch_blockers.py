"""Add launch blocker features: profile fields, featured listings, dispute response, announcements.

Revision ID: 0002
Revises: 0001_initial
Create Date: 2026-04-11

New columns:
  - users: address_city, address_country
  - listings: is_featured, featured_at, featured_until
  - disputes: seller_response, seller_responded_at, seller_response_deadline, seller_proposed_resolution

New tables:
  - announcements
"""

import sqlalchemy as sa
from alembic import op


revision = "0002"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Users: address fields (FR-AUTH-009) ─────────────────────
    op.add_column("users", sa.Column("address_city", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("address_country", sa.String(5), nullable=True))

    # ── Listings: featured fields (FR-LIST-010) ─────────────────
    op.add_column("listings", sa.Column("is_featured", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("listings", sa.Column("featured_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("listings", sa.Column("featured_until", sa.DateTime(timezone=True), nullable=True))

    # ── Disputes: seller response fields (FR-DISP-004) ──────────
    op.add_column("disputes", sa.Column("seller_response", sa.Text(), nullable=True))
    op.add_column("disputes", sa.Column("seller_responded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("disputes", sa.Column("seller_response_deadline", sa.DateTime(timezone=True), nullable=True))
    op.add_column("disputes", sa.Column("seller_proposed_resolution", sa.String(50), nullable=True))

    # ── Announcements table (FR-ADMIN-011) ──────────────────────
    op.create_table(
        "announcements",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title_ar", sa.String(200), nullable=False),
        sa.Column("title_en", sa.String(200), nullable=False),
        sa.Column("body_ar", sa.Text(), nullable=True),
        sa.Column("body_en", sa.Text(), nullable=True),
        sa.Column("type", sa.String(20), server_default="info", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_audience", sa.String(20), server_default="all", nullable=False),
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("announcements")

    op.drop_column("disputes", "seller_proposed_resolution")
    op.drop_column("disputes", "seller_response_deadline")
    op.drop_column("disputes", "seller_responded_at")
    op.drop_column("disputes", "seller_response")

    op.drop_column("listings", "featured_until")
    op.drop_column("listings", "featured_at")
    op.drop_column("listings", "is_featured")

    op.drop_column("users", "address_country")
    op.drop_column("users", "address_city")
