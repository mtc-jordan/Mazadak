"""Add dispute_messages table for dispute communication threads.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-11

New tables:
  - dispute_messages (buyer/seller/admin message thread per dispute)
"""

import sqlalchemy as sa
from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dispute_messages",
        sa.Column("id", sa.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("dispute_id", sa.UUID, nullable=False),
        sa.Column("sender_id", sa.UUID, nullable=False),
        sa.Column("sender_role", sa.String(10), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("attachment_s3_key", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["dispute_id"], ["disputes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_dispute_messages_dispute_id", "dispute_messages", ["dispute_id"])


def downgrade() -> None:
    op.drop_index("ix_dispute_messages_dispute_id", table_name="dispute_messages")
    op.drop_table("dispute_messages")
