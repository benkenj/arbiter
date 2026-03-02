"""whale_schema

Revision ID: 1c5960c71bfe
Revises: 704f539fec49
Create Date: 2026-03-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "1c5960c71bfe"
down_revision: Union[str, None] = "704f539fec49"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop price_snapshots index + table
    op.drop_index("ix_price_snapshots_market_fetched", table_name="price_snapshots")
    op.drop_table("price_snapshots")

    # 2. Drop signals index + table
    op.drop_index("ix_signals_market_strategy_active", table_name="signals")
    op.drop_table("signals")

    # 3. Drop signal_status enum (Alembic does not auto-drop PostgreSQL enums)
    op.execute("DROP TYPE IF EXISTS signal_status")

    # 4. Add nullable columns to markets
    op.add_column("markets", sa.Column("condition_id", sa.String(), nullable=True))
    op.add_column("markets", sa.Column("last_ingested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("markets", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))

    # 5. Create trades table
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wallet_address", sa.String(), nullable=False),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("size", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trades_wallet", "trades", ["wallet_address"])
    op.create_index("ix_trades_market", "trades", ["market_id"])

    # 6. Create wallets table
    op.create_table(
        "wallets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("total_volume", sa.Float(), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("last_scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_tracked", sa.Boolean(), nullable=False, server_default="false"),
        sa.UniqueConstraint("address"),
    )
    op.create_index("ix_wallets_is_tracked", "wallets", ["is_tracked"])

    # 7. Create positions table
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wallet_address", sa.String(), nullable=False),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("current_size", sa.Float(), nullable=False),
        sa.Column("avg_price", sa.Float(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_positions_wallet", "positions", ["wallet_address"])


def downgrade() -> None:
    # 1. Drop positions
    op.drop_index("ix_positions_wallet", table_name="positions")
    op.drop_table("positions")

    # 2. Drop wallets
    op.drop_index("ix_wallets_is_tracked", table_name="wallets")
    op.drop_table("wallets")

    # 3. Drop trades
    op.drop_index("ix_trades_market", table_name="trades")
    op.drop_index("ix_trades_wallet", table_name="trades")
    op.drop_table("trades")

    # 4. Remove new columns from markets
    op.drop_column("markets", "created_at")
    op.drop_column("markets", "last_ingested_at")
    op.drop_column("markets", "condition_id")

    # 5. Re-create signal_status enum
    op.execute(
        "CREATE TYPE signal_status AS ENUM "
        "('active', 'resolved_correct', 'resolved_incorrect', 'expired', 'void')"
    )

    # 6. Re-create signals table + index
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
                create_type=False,
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

    # 7. Re-create price_snapshots table + index
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
