"""Integration tests for whale scoring — uses aiosqlite in-memory DB.

upsert_wallet_scores uses pg_insert (PostgreSQL-only), so it is mocked here.
We test _compute_wallet_stats, _apply_scores, _apply_is_tracked, and score_all_wallets
independently from the upsert path.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from arbiter.config import Settings
from arbiter.db.models import Market, Trade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_settings(**kwargs) -> Settings:
    defaults = dict(
        database_url="postgresql+asyncpg://fake:fake@localhost/fake",
        discord_webhook_url="https://discord.com/api/webhooks/fake/fake",
    )
    defaults.update(kwargs)
    return Settings(**defaults)


async def seed_market(session, market_id: int, external_id: str = "ext-1") -> Market:
    m = Market(
        id=market_id,
        external_id=external_id,
        question="Will X happen?",
        resolved=False,
        closed=False,
        active=True,
        fetched_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    session.add(m)
    await session.flush()
    return m


async def seed_trade(
    session,
    wallet_address: str,
    market_id: int,
    side: str = "BUY",
    size: float = 10.0,
    price: float = 0.40,
    outcome: str | None = None,
    timestamp: datetime | None = None,
) -> Trade:
    if timestamp is None:
        timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    t = Trade(
        wallet_address=wallet_address,
        market_id=market_id,
        side=side,
        size=size,
        price=price,
        timestamp=timestamp,
        outcome=outcome,
    )
    session.add(t)
    await session.flush()
    return t


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestScoringIntegration:
    async def test_compute_wallet_stats_from_db_trades(self, session_factory):
        from arbiter.scoring.whales import _apply_is_tracked, _apply_scores, _compute_wallet_stats

        settings = make_settings(
            whale_min_trades=1,
            whale_min_win_rate=0.5,
            whale_min_volume=1.0,
        )

        async with session_factory() as session:
            await seed_market(session, market_id=1, external_id="ext-1")
            await seed_market(session, market_id=2, external_id="ext-2")

            # wallet A: wins market 1, loses market 2
            await seed_trade(session, "walletA", market_id=1, side="BUY", size=10, price=0.40, outcome="Yes")
            await seed_trade(session, "walletA", market_id=2, side="BUY", size=10, price=0.40, outcome="No")

            # wallet B: wins both
            await seed_trade(session, "walletB", market_id=1, side="BUY", size=5, price=0.50, outcome="Yes")
            await seed_trade(session, "walletB", market_id=2, side="BUY", size=5, price=0.30, outcome="Yes")

            await session.commit()

            result = await session.execute(select(Trade))
            trades = result.scalars().all()

        rows = _compute_wallet_stats(trades, settings)
        by_addr = {r["address"]: r for r in rows}

        assert abs(by_addr["walletA"]["win_rate"] - 0.5) < 1e-9
        assert abs(by_addr["walletB"]["win_rate"] - 1.0) < 1e-9

        _apply_scores(rows, mode="consistent")
        for row in rows:
            assert "score" in row
            assert row["score"] is not None

        _apply_is_tracked(rows, settings)
        # walletB wins more — should be tracked
        assert by_addr["walletB"]["is_tracked"] is True

    async def test_score_all_wallets_no_duplicates(self, session_factory):
        """score_all_wallets called twice should not duplicate rows (upsert mocked)."""
        from arbiter.scoring.whales import score_all_wallets

        settings = make_settings(
            whale_min_trades=1,
            whale_min_win_rate=0.5,
            whale_min_volume=1.0,
        )

        async with session_factory() as session:
            await seed_market(session, market_id=1, external_id="ext-1")
            await seed_trade(session, "walletA", market_id=1, side="BUY", size=10, price=0.40, outcome="Yes")
            await session.commit()

        call_count = {"n": 0}

        async def mock_upsert(session, rows):
            call_count["n"] += 1

        with patch("arbiter.scoring.whales.upsert_wallet_scores", side_effect=mock_upsert):
            async with session_factory() as session:
                count1 = await score_all_wallets(session, settings)

            async with session_factory() as session:
                count2 = await score_all_wallets(session, settings)

        assert count1 == 1
        assert count2 == 1
        assert call_count["n"] == 2

    async def test_score_all_wallets_empty_db_returns_zero(self, session_factory):
        from arbiter.scoring.whales import score_all_wallets

        settings = make_settings()

        with patch("arbiter.scoring.whales.upsert_wallet_scores", new_callable=AsyncMock):
            async with session_factory() as session:
                count = await score_all_wallets(session, settings)

        assert count == 0

    async def test_score_all_wallets_respects_days_window(self, session_factory):
        """Trades outside whale_score_days window must be excluded from scoring."""
        from arbiter.scoring.whales import score_all_wallets

        settings = make_settings(
            whale_min_trades=1,
            whale_min_win_rate=0.0,
            whale_min_volume=0.0,
            whale_score_days=30,
        )

        now = datetime.now(tz=timezone.utc)
        recent_ts = now - timedelta(days=1)
        old_ts = now - timedelta(days=40)

        async with session_factory() as session:
            await seed_market(session, market_id=1, external_id="ext-old")
            await seed_market(session, market_id=2, external_id="ext-recent")
            # walletOLD: trade from 40 days ago — outside 30-day window
            await seed_trade(session, "walletOLD", market_id=1, outcome="Yes", timestamp=old_ts)
            # walletNEW: trade from yesterday — inside window
            await seed_trade(session, "walletNEW", market_id=2, outcome="Yes", timestamp=recent_ts)
            await session.commit()

        with patch("arbiter.scoring.whales.upsert_wallet_scores", new_callable=AsyncMock):
            async with session_factory() as session:
                count = await score_all_wallets(session, settings)

        assert count == 1, f"Expected 1 wallet in 30-day window, got {count}"
