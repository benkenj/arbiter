"""Unit tests for trade ingestion module (03-03) using mocked DB sessions."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arbiter.clients.polymarket import Trade as ClientTrade
from arbiter.ingestion.trades import (
    _trade_to_db_row,
    ingest_market,
    run_ingestion_cycle,
)
from tests.conftest import make_client_trade


# ---------------------------------------------------------------------------
# _trade_to_db_row
# ---------------------------------------------------------------------------

class TestTradeToDbRow:
    def test_basic_field_mapping(self):
        trade = make_client_trade(
            proxy_wallet="0xwallet",
            side="BUY",
            size=10.0,
            price=0.65,
            timestamp=1_700_000_000,
            condition_id="0xcond",
            outcome="Yes",
        )
        row = _trade_to_db_row(trade, market_id=42)

        assert row["wallet_address"] == "0xwallet"
        assert row["market_id"] == 42
        assert row["side"] == "BUY"
        assert row["size"] == 10.0
        assert row["price"] == 0.65
        assert row["outcome"] == "Yes"

    def test_timestamp_converted_to_utc_datetime(self):
        trade = make_client_trade(timestamp=1_700_000_000)
        row = _trade_to_db_row(trade, market_id=1)
        expected = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
        assert row["timestamp"] == expected
        assert row["timestamp"].tzinfo is not None

    def test_outcome_none_preserved(self):
        trade = make_client_trade(outcome=None)
        row = _trade_to_db_row(trade, market_id=1)
        assert row["outcome"] is None

    def test_sell_side(self):
        trade = make_client_trade(side="SELL", outcome="No")
        row = _trade_to_db_row(trade, market_id=5)
        assert row["side"] == "SELL"
        assert row["outcome"] == "No"


# ---------------------------------------------------------------------------
# ingest_market
# ---------------------------------------------------------------------------

class TestIngestMarket:
    def _make_market(self, market_id=1, condition_id="0xcond", last_ingested_at=None):
        m = MagicMock()
        m.id = market_id
        m.condition_id = condition_id
        m.last_ingested_at = last_ingested_at
        return m

    async def test_returns_zero_when_no_trades(self):
        market = self._make_market()
        client = MagicMock()
        client.get_trades_for_market = AsyncMock(return_value=[])

        session = AsyncMock()
        count = await ingest_market(session, client, market, page_size=500)

        assert count == 0
        session.execute.assert_not_called()
        session.commit.assert_not_called()

    async def test_inserts_trades_and_updates_watermark(self):
        trades = [
            make_client_trade(timestamp=1_700_000_010),
            make_client_trade(timestamp=1_700_000_005),
        ]
        market = self._make_market(market_id=7, last_ingested_at=None)
        client = MagicMock()
        client.get_trades_for_market = AsyncMock(return_value=trades)

        session = AsyncMock()
        count = await ingest_market(session, client, market, page_size=500)

        assert count == 2
        session.execute.assert_called_once()
        session.commit.assert_called_once()
        # Watermark set to max timestamp
        expected_watermark = datetime.fromtimestamp(1_700_000_010, tz=timezone.utc)
        assert market.last_ingested_at == expected_watermark

    async def test_watermark_passed_to_client(self):
        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        market = self._make_market(last_ingested_at=since)
        client = MagicMock()
        client.get_trades_for_market = AsyncMock(return_value=[])

        session = AsyncMock()
        await ingest_market(session, client, market, page_size=200)

        client.get_trades_for_market.assert_called_once_with(
            condition_id="0xcond",
            since=since,
            page_size=200,
        )

    async def test_watermark_set_to_newest_trade(self):
        # Trades returned newest-first; watermark should be max timestamp
        trades = [
            make_client_trade(timestamp=1_700_000_100),  # newest
            make_client_trade(timestamp=1_700_000_050),
            make_client_trade(timestamp=1_700_000_001),  # oldest
        ]
        market = self._make_market()
        client = MagicMock()
        client.get_trades_for_market = AsyncMock(return_value=trades)

        session = AsyncMock()
        await ingest_market(session, client, market, page_size=500)

        expected = datetime.fromtimestamp(1_700_000_100, tz=timezone.utc)
        assert market.last_ingested_at == expected


# ---------------------------------------------------------------------------
# run_ingestion_cycle
# ---------------------------------------------------------------------------

class TestRunIngestionCycle:
    def _make_settings(self, batch_size=100, page_size=500):
        s = MagicMock()
        s.ingestion_batch_size = batch_size
        s.ingestion_page_size = page_size
        return s

    def _make_market(self, market_id: int, condition_id: str = "0xcond"):
        m = MagicMock()
        m.id = market_id
        m.external_id = f"ext-{market_id}"
        m.condition_id = condition_id
        m.last_ingested_at = None
        return m

    async def test_returns_zero_counts_with_no_markets(self):
        settings = self._make_settings()
        client = MagicMock()

        # Session returns no markets
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        factory = MagicMock(return_value=session)

        processed, trades, failures = await run_ingestion_cycle(settings, factory, client)
        assert processed == 0
        assert trades == 0
        assert failures == 0

    async def test_per_market_failure_does_not_abort_cycle(self):
        """One market failing should not prevent others from being processed."""
        settings = self._make_settings(batch_size=10)

        markets = [self._make_market(i) for i in range(3)]

        # First session call: return market list
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = markets

        list_session = AsyncMock()
        list_session.execute = AsyncMock(return_value=list_result)

        # Per-market sessions: market 0 raises, markets 1+2 succeed
        def make_per_market_session(market_id):
            sess = AsyncMock()
            mkt = self._make_market(market_id)
            sess.get = AsyncMock(return_value=mkt)
            if market_id == 0:
                sess.execute = AsyncMock(side_effect=RuntimeError("boom"))
            else:
                sess.execute = AsyncMock(return_value=MagicMock())
            return sess

        call_count = [0]
        per_market_sessions = [make_per_market_session(i) for i in range(3)]

        def session_cm_factory():
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                sess = list_session
            else:
                sess = per_market_sessions[idx - 1]
            sess.__aenter__ = AsyncMock(return_value=sess)
            sess.__aexit__ = AsyncMock(return_value=False)
            return sess

        client = MagicMock()
        trades_by_market = {0: RuntimeError("network down"), 1: [], 2: []}

        call_idx = [0]
        async def mock_get_trades(condition_id, since, page_size):
            val = list(trades_by_market.values())[call_idx[0]]
            call_idx[0] += 1
            if isinstance(val, Exception):
                raise val
            return val

        client.get_trades_for_market = mock_get_trades

        factory = MagicMock(side_effect=session_cm_factory)

        processed, total_trades, failures = await run_ingestion_cycle(settings, factory, client)

        # 1 failure, 2 processed successfully
        assert failures == 1
        assert processed == 2

    async def test_respects_batch_size(self):
        """Only processes up to ingestion_batch_size markets per cycle."""
        settings = self._make_settings(batch_size=2)

        # 5 markets in DB, only 2 should be processed
        markets = [self._make_market(i) for i in range(5)]

        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = markets

        list_session = AsyncMock()
        list_session.execute = AsyncMock(return_value=list_result)

        processed_ids = []

        def session_cm_factory():
            from unittest.mock import MagicMock as MM
            sess = AsyncMock()
            # Return a fresh mock market when .get() is called
            async def fake_get(model, mid):
                processed_ids.append(mid)
                return self._make_market(mid)
            sess.get = fake_get
            sess.execute = AsyncMock(return_value=MagicMock())
            return sess

        call_count = [0]

        def factory():
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                s = list_session
            else:
                s = session_cm_factory()
            s.__aenter__ = AsyncMock(return_value=s)
            s.__aexit__ = AsyncMock(return_value=False)
            return s

        client = MagicMock()
        client.get_trades_for_market = AsyncMock(return_value=[])

        processed, _, _ = await run_ingestion_cycle(settings, factory, client)
        assert processed == 2  # batch_size=2, not all 5
