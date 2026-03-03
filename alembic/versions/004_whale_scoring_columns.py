"""add win_volume, total_pnl, pnl_trend to wallets

Revision ID: 004_whale_scoring_columns
Revises: a3f8b2c91d45
Create Date: 2026-03-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "004_whale_scoring_columns"
down_revision = "a3f8b2c91d45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("wallets", sa.Column("win_volume", sa.Float(), nullable=True))
    op.add_column("wallets", sa.Column("total_pnl", sa.Float(), nullable=True))
    op.add_column("wallets", sa.Column("pnl_trend", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("wallets", "pnl_trend")
    op.drop_column("wallets", "total_pnl")
    op.drop_column("wallets", "win_volume")
