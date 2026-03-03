"""Unit tests for whale scoring logic — no DB required."""
from datetime import datetime, timezone

import pytest

from arbiter.config import Settings


def make_settings(**kwargs) -> Settings:
    defaults = dict(
        database_url="postgresql+asyncpg://fake:fake@localhost/fake",
        discord_webhook_url="https://discord.com/api/webhooks/fake/fake",
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def make_trade(
    wallet_address: str = "0xaaa",
    market_id: int = 1,
    side: str = "BUY",
    size: float = 10.0,
    price: float = 0.40,
    timestamp: datetime | None = None,
    outcome: str | None = None,
):
    """Create a simple namespace object mimicking a Trade ORM row."""
    from types import SimpleNamespace

    if timestamp is None:
        timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return SimpleNamespace(
        wallet_address=wallet_address,
        market_id=market_id,
        side=side,
        size=size,
        price=price,
        timestamp=timestamp,
        outcome=outcome,
    )


class TestComputePnl:
    def test_buy_then_sell_realized_win(self):
        from arbiter.scoring.whales import compute_pnl_for_market

        trades = [
            make_trade(side="BUY", size=10, price=0.40, timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc)),
            make_trade(side="SELL", size=10, price=0.70, timestamp=datetime(2025, 1, 2, tzinfo=timezone.utc)),
        ]
        pnl, is_win = compute_pnl_for_market(trades)
        assert abs(pnl - 3.0) < 1e-9
        assert is_win is True

    def test_buy_resolved_yes(self):
        from arbiter.scoring.whales import compute_pnl_for_market

        trades = [
            make_trade(side="BUY", size=10, price=0.40, outcome="Yes"),
        ]
        pnl, is_win = compute_pnl_for_market(trades)
        assert abs(pnl - 6.0) < 1e-9
        assert is_win is True

    def test_buy_resolved_no(self):
        from arbiter.scoring.whales import compute_pnl_for_market

        trades = [
            make_trade(side="BUY", size=10, price=0.40, outcome="No"),
        ]
        pnl, is_win = compute_pnl_for_market(trades)
        assert abs(pnl - (-4.0)) < 1e-9
        assert is_win is False

    def test_open_position_no_exit_no_outcome(self):
        from arbiter.scoring.whales import compute_pnl_for_market

        trades = [
            make_trade(side="BUY", size=10, price=0.40),
        ]
        pnl, is_win = compute_pnl_for_market(trades)
        assert pnl == 0.0
        assert is_win is None

    def test_partial_sell_then_resolve_yes(self):
        from arbiter.scoring.whales import compute_pnl_for_market

        trades = [
            make_trade(side="BUY", size=10, price=0.40, timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc)),
            make_trade(side="SELL", size=5, price=0.70, timestamp=datetime(2025, 1, 2, tzinfo=timezone.utc), outcome=None),
            make_trade(side="BUY", size=0, price=0.70, timestamp=datetime(2025, 1, 3, tzinfo=timezone.utc), outcome="Yes"),
        ]
        # BUY 10 @ 0.40, SELL 5 @ 0.70 => realized 5*(0.70-0.40) = 1.5
        # remaining 5 @ 0.40 resolve Yes => 5*(1.0-0.40) = 3.0
        # total = 4.5
        pnl, is_win = compute_pnl_for_market(trades)
        assert abs(pnl - 4.5) < 1e-9
        assert is_win is True


class TestComputeWalletStats:
    def test_two_wallets_two_markets(self):
        from arbiter.scoring.whales import _compute_wallet_stats

        settings = make_settings()
        t = datetime(2025, 1, 1, tzinfo=timezone.utc)

        trades = [
            # wallet A, market 1 — win (buy at 0.4, resolve Yes => pnl=6.0)
            make_trade("walletA", market_id=1, side="BUY", size=10, price=0.40, timestamp=t, outcome="Yes"),
            # wallet A, market 2 — lose (buy at 0.4, resolve No => pnl=-4.0)
            make_trade("walletA", market_id=2, side="BUY", size=10, price=0.40, timestamp=t, outcome="No"),
            # wallet B, market 1 — win
            make_trade("walletB", market_id=1, side="BUY", size=5, price=0.50, timestamp=t, outcome="Yes"),
            # wallet B, market 2 — win (sell before resolution)
            make_trade("walletB", market_id=2, side="BUY", size=5, price=0.30, timestamp=t),
            make_trade("walletB", market_id=2, side="SELL", size=5, price=0.80, timestamp=datetime(2025, 1, 2, tzinfo=timezone.utc)),
        ]

        rows = _compute_wallet_stats(trades, settings)
        by_addr = {r["address"]: r for r in rows}

        # wallet A: 1 win, 1 loss => win_rate = 0.5
        assert abs(by_addr["walletA"]["win_rate"] - 0.5) < 1e-9
        # wallet B: 2 wins => win_rate = 1.0
        assert abs(by_addr["walletB"]["win_rate"] - 1.0) < 1e-9

    def test_total_volume_includes_all_trades(self):
        from arbiter.scoring.whales import _compute_wallet_stats

        settings = make_settings()
        t = datetime(2025, 1, 1, tzinfo=timezone.utc)

        trades = [
            make_trade("walletA", market_id=1, side="BUY", size=10, price=0.40, timestamp=t, outcome="Yes"),
            make_trade("walletA", market_id=2, side="BUY", size=5, price=0.60, timestamp=t),
        ]
        rows = _compute_wallet_stats(trades, settings)
        row = rows[0]
        assert abs(row["total_volume"] - 15.0) < 1e-9

    def test_win_volume_only_winning_positions(self):
        from arbiter.scoring.whales import _compute_wallet_stats

        settings = make_settings()
        t = datetime(2025, 1, 1, tzinfo=timezone.utc)

        trades = [
            make_trade("walletA", market_id=1, side="BUY", size=10, price=0.40, timestamp=t, outcome="Yes"),
            make_trade("walletA", market_id=2, side="BUY", size=5, price=0.40, timestamp=t, outcome="No"),
        ]
        rows = _compute_wallet_stats(trades, settings)
        row = rows[0]
        # win_volume = size on winning market (market 1) only = 10
        assert abs(row["win_volume"] - 10.0) < 1e-9

    def test_total_trades_excludes_open(self):
        from arbiter.scoring.whales import _compute_wallet_stats

        settings = make_settings()
        t = datetime(2025, 1, 1, tzinfo=timezone.utc)

        trades = [
            make_trade("walletA", market_id=1, side="BUY", size=10, price=0.40, timestamp=t, outcome="Yes"),
            # market 2 is open — no resolution or sell
            make_trade("walletA", market_id=2, side="BUY", size=5, price=0.40, timestamp=t),
        ]
        rows = _compute_wallet_stats(trades, settings)
        row = rows[0]
        # only 1 resolved position
        assert row["total_trades"] == 1

    def test_pnl_trend_single_market_returns_zero(self):
        from arbiter.scoring.whales import _compute_wallet_stats

        settings = make_settings()
        t = datetime(2025, 1, 1, tzinfo=timezone.utc)

        trades = [
            make_trade("walletA", market_id=1, side="BUY", size=10, price=0.40, timestamp=t, outcome="Yes"),
        ]
        rows = _compute_wallet_stats(trades, settings)
        row = rows[0]
        # fewer than 2 data points => trend = 0.0
        assert row["pnl_trend"] == 0.0


class TestIsTracked:
    def test_below_min_trades_not_tracked(self):
        from arbiter.scoring.whales import _apply_is_tracked

        settings = make_settings(whale_min_trades=10, whale_min_win_rate=0.6, whale_min_volume=1000.0)
        rows = [
            {"address": "0xaaa", "total_trades": 5, "win_rate": 1.0, "total_volume": 5000.0}
        ]
        _apply_is_tracked(rows, settings)
        assert rows[0]["is_tracked"] is False

    def test_meeting_all_thresholds_is_tracked(self):
        from arbiter.scoring.whales import _apply_is_tracked

        settings = make_settings(whale_min_trades=10, whale_min_win_rate=0.6, whale_min_volume=1000.0)
        rows = [
            {"address": "0xaaa", "total_trades": 15, "win_rate": 0.75, "total_volume": 2000.0}
        ]
        _apply_is_tracked(rows, settings)
        assert rows[0]["is_tracked"] is True

    def test_low_volume_not_tracked(self):
        from arbiter.scoring.whales import _apply_is_tracked

        settings = make_settings(whale_min_trades=10, whale_min_win_rate=0.6, whale_min_volume=1000.0)
        rows = [
            {"address": "0xaaa", "total_trades": 15, "win_rate": 0.75, "total_volume": 500.0}
        ]
        _apply_is_tracked(rows, settings)
        assert rows[0]["is_tracked"] is False

    def test_none_win_rate_not_tracked(self):
        from arbiter.scoring.whales import _apply_is_tracked

        settings = make_settings(whale_min_trades=10, whale_min_win_rate=0.6, whale_min_volume=1000.0)
        rows = [
            {"address": "0xaaa", "total_trades": 15, "win_rate": None, "total_volume": 5000.0}
        ]
        _apply_is_tracked(rows, settings)
        assert rows[0]["is_tracked"] is False


class TestPercentileRanks:
    def test_single_value_returns_half(self):
        from arbiter.scoring.whales import percentile_ranks

        result = percentile_ranks([42.0])
        assert result == [0.5]

    def test_three_values_ordered(self):
        from arbiter.scoring.whales import percentile_ranks

        result = percentile_ranks([1.0, 2.0, 3.0])
        assert result == [0.0, 0.5, 1.0]

    def test_tied_values_share_rank(self):
        from arbiter.scoring.whales import percentile_ranks

        result = percentile_ranks([1.0, 1.0, 3.0])
        # 1.0 maps to rank 0 / (2-1) = 0.0, 3.0 maps to 1.0
        assert result[0] == result[1]
        assert result[2] == 1.0
