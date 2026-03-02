"""initial_schema

Revision ID: 704f539fec49
Revises:
Create Date: 2026-02-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "704f539fec49"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "markets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("closed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("yes_price", sa.Float(), nullable=True),
        sa.Column("liquidity", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_markets_active", "markets", ["active"])

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("market_question", sa.Text(), nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("signal_direction", sa.String(10), nullable=False),
        sa.Column("signal_price", sa.Float(), nullable=False),
        sa.Column("hours_to_expiry", sa.Float(), nullable=True),
        sa.Column("liquidity_at_signal", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "resolved_correct",
                "resolved_incorrect",
                "expired",
                "void",
                name="signal_status",
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("resolution_outcome", sa.String(20), nullable=True),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_signals_market_strategy_active",
        "signals",
        ["market_id", "strategy"],
        unique=True,
        postgresql_where="status = 'active'",
    )

    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("yes_bid", sa.Float(), nullable=True),
        sa.Column("yes_ask", sa.Float(), nullable=True),
        sa.Column("liquidity", sa.Float(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_price_snapshots_market_fetched",
        "price_snapshots",
        ["market_id", "fetched_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_price_snapshots_market_fetched", table_name="price_snapshots")
    op.drop_table("price_snapshots")

    op.drop_index("ix_signals_market_strategy_active", table_name="signals")
    op.drop_table("signals")

    op.drop_index("ix_markets_active", table_name="markets")
    op.drop_table("markets")

    op.execute("DROP TYPE signal_status")
