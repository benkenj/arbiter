"""Unit tests for PolymarketClient.get_trades_for_market watermark pagination (03-01)."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from arbiter.clients.polymarket import PolymarketClient, Trade


def _make_trade(timestamp: int, wallet: str = "0xabc") -> Trade:
    return Trade(
        proxy_wallet=wallet,
        side="BUY",
        size=1.0,
        price=0.5,
        timestamp=timestamp,
        condition_id="0xcond",
    )


class TestGetTradesForMarketPagination:
    async def test_returns_empty_when_no_trades(self):
        client = PolymarketClient.__new__(PolymarketClient)
        client._fetch_clob_page = AsyncMock(return_value=[])

        result = await client.get_trades_for_market("0xcond")
        assert result == []
        client._fetch_clob_page.assert_called_once_with("0xcond", 0, 500)

    async def test_single_partial_page_no_watermark(self):
        trades = [_make_trade(1700000002), _make_trade(1700000001)]
        client = PolymarketClient.__new__(PolymarketClient)
        client._fetch_clob_page = AsyncMock(return_value=trades)

        result = await client.get_trades_for_market("0xcond", page_size=500)
        assert len(result) == 2
        # Partial page (2 < 500) signals end — no second fetch needed
        assert client._fetch_clob_page.call_count == 1

    async def test_stops_when_page_fills_exactly(self):
        # Page with exactly page_size=2 trades → fetches next, which is empty
        page1 = [_make_trade(1700000002), _make_trade(1700000001)]
        client = PolymarketClient.__new__(PolymarketClient)
        client._fetch_clob_page = AsyncMock(side_effect=[page1, []])

        result = await client.get_trades_for_market("0xcond", page_size=2)
        assert len(result) == 2
        assert client._fetch_clob_page.call_count == 2

    async def test_multiple_full_pages(self):
        page1 = [_make_trade(1700000005), _make_trade(1700000004)]
        page2 = [_make_trade(1700000003), _make_trade(1700000002)]
        page3 = [_make_trade(1700000001)]  # partial — final page
        client = PolymarketClient.__new__(PolymarketClient)
        client._fetch_clob_page = AsyncMock(side_effect=[page1, page2, page3])

        result = await client.get_trades_for_market("0xcond", page_size=2)
        assert len(result) == 5

    async def test_watermark_filters_all_old_trades(self):
        # All trades older than watermark → return empty
        since = datetime.fromtimestamp(1700000010, tz=timezone.utc)
        old_trades = [_make_trade(1700000005), _make_trade(1700000001)]
        client = PolymarketClient.__new__(PolymarketClient)
        client._fetch_clob_page = AsyncMock(return_value=old_trades)

        result = await client.get_trades_for_market("0xcond", since=since, page_size=500)
        assert result == []
        # Stopped after 1 page because all trades were older
        client._fetch_clob_page.assert_called_once()

    async def test_watermark_filters_partial_page(self):
        # First two trades newer, last one older → returns first two, stops paging
        since = datetime.fromtimestamp(1700000003, tz=timezone.utc)
        trades = [
            _make_trade(1700000010),  # newer
            _make_trade(1700000005),  # newer
            _make_trade(1700000002),  # older — stops here
        ]
        client = PolymarketClient.__new__(PolymarketClient)
        client._fetch_clob_page = AsyncMock(return_value=trades)

        result = await client.get_trades_for_market("0xcond", since=since, page_size=500)
        assert len(result) == 2
        assert all(t.timestamp > 1700000003 for t in result)
        # No second page fetched because watermark was crossed mid-page
        client._fetch_clob_page.assert_called_once()

    async def test_watermark_all_newer_fetches_next_page(self):
        # All trades on first page are newer than watermark → must fetch next page
        since = datetime.fromtimestamp(1700000000, tz=timezone.utc)
        page1 = [_make_trade(1700000010), _make_trade(1700000005)]
        page2 = [_make_trade(1700000003)]  # newer, but partial page → stop
        client = PolymarketClient.__new__(PolymarketClient)
        client._fetch_clob_page = AsyncMock(side_effect=[page1, page2])

        result = await client.get_trades_for_market("0xcond", since=since, page_size=2)
        assert len(result) == 3
        assert client._fetch_clob_page.call_count == 2

    async def test_page_offset_increments_correctly(self):
        page1 = [_make_trade(1700000003), _make_trade(1700000002)]
        client = PolymarketClient.__new__(PolymarketClient)
        client._fetch_clob_page = AsyncMock(side_effect=[page1, []])

        await client.get_trades_for_market("0xcond", page_size=2)

        calls = client._fetch_clob_page.call_args_list
        assert calls[0].args == ("0xcond", 0, 2)
        assert calls[1].args == ("0xcond", 2, 2)

    async def test_custom_page_size_passed_through(self):
        client = PolymarketClient.__new__(PolymarketClient)
        client._fetch_clob_page = AsyncMock(return_value=[])

        await client.get_trades_for_market("0xcond", page_size=100)
        client._fetch_clob_page.assert_called_once_with("0xcond", 0, 100)
