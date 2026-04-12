"""Add currency column to listings table.

Revision ID: 0004
Revises: 0003
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "listings",
        sa.Column("currency", sa.String(3), server_default="JOD", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("listings", "currency")
