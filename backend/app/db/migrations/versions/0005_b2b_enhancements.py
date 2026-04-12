"""B2B enhancements: invitations table + room/bid columns.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- b2b_invitations (access control for tender rooms) ----------------
    op.create_table(
        "b2b_invitations",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("room_id", UUID(as_uuid=False), sa.ForeignKey("b2b_rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("invited_by", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("min_ats_score", sa.Integer, nullable=True),
        sa.Column("min_kyc_level", sa.String(20), nullable=True),
        sa.Column("invited_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("room_id", "user_id", name="uq_b2b_invitations_room_user"),
    )
    op.create_index("ix_b2b_invitations_room_id", "b2b_invitations", ["room_id"])
    op.create_index("ix_b2b_invitations_user_id", "b2b_invitations", ["user_id"])

    # -- ALTER b2b_rooms: add new columns --------------------------------
    op.add_column("b2b_rooms", sa.Column("client_logo_url", sa.String(500), nullable=True))
    op.add_column("b2b_rooms", sa.Column("sealed", sa.Boolean, server_default="true", nullable=False))
    op.add_column("b2b_rooms", sa.Column("min_lot_amount", sa.Integer, server_default="1000000", nullable=False))
    op.add_column("b2b_rooms", sa.Column("estimated_value", sa.Integer, nullable=True))
    op.add_column("b2b_rooms", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True))

    # -- ALTER b2b_bids: add submission_ref ------------------------------
    op.add_column("b2b_bids", sa.Column("submission_ref", sa.String(50), server_default=sa.text("gen_random_uuid()::text"), nullable=True, unique=True))


def downgrade() -> None:
    op.drop_column("b2b_bids", "submission_ref")
    op.drop_column("b2b_rooms", "updated_at")
    op.drop_column("b2b_rooms", "estimated_value")
    op.drop_column("b2b_rooms", "min_lot_amount")
    op.drop_column("b2b_rooms", "sealed")
    op.drop_column("b2b_rooms", "client_logo_url")
    op.drop_index("ix_b2b_invitations_user_id", table_name="b2b_invitations")
    op.drop_index("ix_b2b_invitations_room_id", table_name="b2b_invitations")
    op.drop_table("b2b_invitations")
