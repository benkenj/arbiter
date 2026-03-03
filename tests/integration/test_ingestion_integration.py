"""
Integration tests for trade ingestion using an in-memory SQLite DB.

Verifies end-to-end: client → ingestion → DB state, including:
- Trades actually written to the trades table
- Watermark updated on the market row
- No duplicates on second run (watermark prevents re-insertion)
- alembic migration schema: outcome column exists on the Trade model
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select, text

from arbiter.db.models import Market, Trade
from arbiter.ingestion.trades import ingest_market, run_ingestion_cycle
from tests.conftest import make_client_trade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_market(session_factory, condition_id: str = "0xcondition1") -> int:
    """Insert a single active market and return its DB id."""
    async with session_factory() as session:
        market = Market(
            external_id=f"ext-{condition_id[:8]}",
            question="Will X happen?",
            active=True,
            fetched_at=datetime.now(tz=timezone.utc),
            condition_id=condition_id,
            last_ingested_at=None,
        )
        session.add(market)
        await session.commit()
        await session.refresh(market)
        return market.id


# ---------------------------------------------------------------------------
# Schema verification
# ---------------------------------------------------------------------------

class TestSchema:
    async def test_trade_orm_has_outcome_column(self, async_engine):
        """Verifies migration 003 outcome column is reflected in the ORM."""
        async with async_engine.connect() as conn:
            result = await conn.execute(text("PRAGMA table_info(trades)"))
            columns = {row[1] for row in result.fetchall()}
        assert "outcome" in columns

    async def test_market_orm_has_last_ingested_at(self, async_engine):
        async with async_engine.connect() as conn:
            result = await conn.execute(text("PRAGMA table_info(markets)"))
            columns = {row[1] for row in result.fetchall()}
        assert "last_ingested_at" in columns


# ---------------------------------------------------------------------------
# ingest_market integration
# ---------------------------------------------------------------------------

class TestIngestMarketIntegration:
    async def test_trades_written_to_db(self, session_factory):
        market_id = await _insert_market(session_factory)

        client_trades = [
            make_client_trade(timestamp=1_700_000_010, proxy_wallet="0xwalletA", outcome="Yes"),
            make_client_trade(timestamp=1_700_000_005, proxy_wallet="0xwalletB", outcome="No"),
        ]
        client = MagicMock()
        client.get_trades_for_market = AsyncMock(return_value=client_trades)

        async with session_factory() as session:
            market = await session.get(Market, market_id)
            count = await ingest_market(session, client, market, page_size=500)

        assert count == 2

        async with session_factory() as session:
            result = await session.execute(select(Trade).where(Trade.market_id == market_id))
            db_trades = result.scalars().all()

        assert len(db_trades) == 2
        wallets = {t.wallet_address for t in db_trades}
        assert wallets == {"0xwalletA", "0xwalletB"}

    async def test_outcome_column_stored(self, session_factory):
        market_id = await _insert_market(session_factory, condition_id="0xcond2")

        client_trades = [
            make_client_trade(timestamp=1_700_000_010, outcome="Yes"),
            make_client_trade(timestamp=1_700_000_009, outcome=None),
        ]
        client = MagicMock()
        client.get_trades_for_market = AsyncMock(return_value=client_trades)

        async with session_factory() as session:
            market = await session.get(Market, market_id)
            await ingest_market(session, client, market, page_size=500)

        async with session_factory() as session:
            result = await session.execute(select(Trade).where(Trade.market_id == market_id))
            db_trades = sorted(result.scalars().all(), key=lambda t: t.timestamp, reverse=True)

        assert db_trades[0].outcome == "Yes"
        assert db_trades[1].outcome is None

    async def test_watermark_updated_after_ingest(self, session_factory):
        market_id = await _insert_market(session_factory)

        client_trades = [
            make_client_trade(timestamp=1_700_000_100),
            make_client_trade(timestamp=1_700_000_050),
        ]
        client = MagicMock()
        client.get_trades_for_market = AsyncMock(return_value=client_trades)

        async with session_factory() as session:
            market = await session.get(Market, market_id)
            await ingest_market(session, client, market, page_size=500)

        async with session_factory() as session:
            market = await session.get(Market, market_id)
            # SQLite stores naive datetimes; compare as timestamps to avoid tz mismatch
            expected_ts = 1_700_000_100
            actual = market.last_ingested_at
            # SQLite returns naive UTC datetimes; utcfromtimestamp matches that representation
            if actual.tzinfo is not None:
                assert int(actual.timestamp()) == expected_ts
            else:
                assert actual == datetime.utcfromtimestamp(expected_ts)

    async def test_no_duplicate_trades_on_second_run(self, session_factory):
        """Second ingest cycle with watermark should insert 0 new trades."""
        market_id = await _insert_market(session_factory, condition_id="0xcond3")

        first_batch = [make_client_trade(timestamp=1_700_000_010)]
        client = MagicMock()

        # First run: insert 1 trade
        client.get_trades_for_market = AsyncMock(return_value=first_batch)
        async with session_factory() as session:
            market = await session.get(Market, market_id)
            await ingest_market(session, client, market, page_size=500)

        # Second run: client returns empty (watermark filters everything)
        client.get_trades_for_market = AsyncMock(return_value=[])
        async with session_factory() as session:
            market = await session.get(Market, market_id)
            count = await ingest_market(session, client, market, page_size=500)

        assert count == 0

        async with session_factory() as session:
            result = await session.execute(select(Trade).where(Trade.market_id == market_id))
            db_trades = result.scalars().all()
        assert len(db_trades) == 1  # still only the original


# ---------------------------------------------------------------------------
# run_ingestion_cycle integration
# ---------------------------------------------------------------------------

class TestRunIngestionCycleIntegration:
    async def test_full_cycle_processes_active_markets(self, session_factory):
        # Insert 2 active markets
        id1 = await _insert_market(session_factory, condition_id="0xcond_a")
        id2 = await _insert_market(session_factory, condition_id="0xcond_b")

        trades_by_condition = {
            "0xcond_a": [make_client_trade(timestamp=1_700_000_010, condition_id="0xcond_a")],
            "0xcond_b": [
                make_client_trade(timestamp=1_700_000_020, condition_id="0xcond_b"),
                make_client_trade(timestamp=1_700_000_015, condition_id="0xcond_b"),
            ],
        }

        async def mock_get_trades(condition_id, since, page_size):
            return trades_by_condition.get(condition_id, [])

        client = MagicMock()
        client.get_trades_for_market = mock_get_trades

        settings = MagicMock()
        settings.ingestion_batch_size = 100
        settings.ingestion_page_size = 500

        processed, total_trades, failures = await run_ingestion_cycle(
            settings, session_factory, client
        )

        assert processed == 2
        assert total_trades == 3
        assert failures == 0

        async with session_factory() as session:
            result = await session.execute(select(Trade))
            all_trades = result.scalars().all()
        assert len(all_trades) == 3

    async def test_inactive_markets_skipped(self, session_factory):
        """Markets with active=False are excluded at the query level."""
        async with session_factory() as session:
            inactive = Market(
                external_id="ext-inactive",
                question="inactive market",
                active=False,
                fetched_at=datetime.now(tz=timezone.utc),
                condition_id="0xinactive",
                last_ingested_at=None,
            )
            session.add(inactive)
            await session.commit()

        client = MagicMock()
        client.get_trades_for_market = AsyncMock(return_value=[])

        settings = MagicMock()
        settings.ingestion_batch_size = 100
        settings.ingestion_page_size = 500

        processed, _, _ = await run_ingestion_cycle(settings, session_factory, client)
        assert processed == 0
        client.get_trades_for_market.assert_not_called()

    async def test_market_without_condition_id_skipped(self, session_factory):
        """Markets with condition_id IS NULL are excluded at the query level."""
        async with session_factory() as session:
            market = Market(
                external_id="ext-nocond",
                question="no condition id market",
                active=True,
                fetched_at=datetime.now(tz=timezone.utc),
                condition_id=None,  # should be excluded
            )
            session.add(market)
            await session.commit()

        client = MagicMock()
        client.get_trades_for_market = AsyncMock(return_value=[])

        settings = MagicMock()
        settings.ingestion_batch_size = 100
        settings.ingestion_page_size = 500

        processed, _, _ = await run_ingestion_cycle(settings, session_factory, client)
        assert processed == 0
        client.get_trades_for_market.assert_not_called()
