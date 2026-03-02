"""add outcome column to trades

Revision ID: a3f8b2c91d45
Revises: 1c5960c71bfe
Create Date: 2026-03-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "a3f8b2c91d45"
down_revision = "1c5960c71bfe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trades",
        sa.Column("outcome", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trades", "outcome")
