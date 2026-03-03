"""Unit tests for whale scoring logic — no DB required."""
from datetime import datetime, timedelta, timezone

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

    def test_empty_list_returns_empty(self):
        from arbiter.scoring.whales import percentile_ranks

        assert percentile_ranks([]) == []


class TestComputePnlEdgeCases:
    def test_multiple_fifo_lots_matched_in_order(self):
        from arbiter.scoring.whales import compute_pnl_for_market

        trades = [
            make_trade(side="BUY", size=5, price=0.30, timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc)),
            make_trade(side="BUY", size=5, price=0.60, timestamp=datetime(2025, 1, 2, tzinfo=timezone.utc)),
            make_trade(side="SELL", size=10, price=0.80, timestamp=datetime(2025, 1, 3, tzinfo=timezone.utc)),
        ]
        # Lot 1: 5 @ 0.30 sold @ 0.80 → 5 * 0.50 = 2.50
        # Lot 2: 5 @ 0.60 sold @ 0.80 → 5 * 0.20 = 1.00
        # Total = 3.50, buys empty → is_win = True
        pnl, is_win = compute_pnl_for_market(trades)
        assert abs(pnl - 3.50) < 1e-9
        assert is_win is True

    def test_sell_exceeds_available_buys(self):
        from arbiter.scoring.whales import compute_pnl_for_market

        trades = [
            make_trade(side="BUY", size=3, price=0.50, timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc)),
            make_trade(side="SELL", size=5, price=0.80, timestamp=datetime(2025, 1, 2, tzinfo=timezone.utc)),
        ]
        # Only 3 shares available; excess sell size is dropped when deque empties
        # pnl = 3 * (0.80 - 0.50) = 0.90
        pnl, is_win = compute_pnl_for_market(trades)
        assert abs(pnl - 0.90) < 1e-9
        assert is_win is True


class TestPnlTrendSlope:
    def test_positive_slope(self):
        from arbiter.scoring.whales import pnl_trend_slope

        t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t1 = t0 + timedelta(days=1)
        # P&L rises from 0 to 10 over 1 day → slope = 10.0 USDC/day
        assert abs(pnl_trend_slope([(t0, 0.0), (t1, 10.0)]) - 10.0) < 1e-9

    def test_negative_slope(self):
        from arbiter.scoring.whales import pnl_trend_slope

        t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t1 = t0 + timedelta(days=1)
        assert abs(pnl_trend_slope([(t0, 10.0), (t1, 0.0)]) - (-10.0)) < 1e-9

    def test_flat_pnl_returns_zero(self):
        from arbiter.scoring.whales import pnl_trend_slope

        t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t1 = t0 + timedelta(days=1)
        assert pnl_trend_slope([(t0, 5.0), (t1, 5.0)]) == 0.0

    def test_all_same_timestamp_returns_zero(self):
        # denominator is 0 when all times are identical — guard must return 0.0
        from arbiter.scoring.whales import pnl_trend_slope

        t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert pnl_trend_slope([(t0, 0.0), (t0, 10.0)]) == 0.0

    def test_single_point_returns_zero(self):
        from arbiter.scoring.whales import pnl_trend_slope

        t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert pnl_trend_slope([(t0, 5.0)]) == 0.0

    def test_empty_returns_zero(self):
        from arbiter.scoring.whales import pnl_trend_slope

        assert pnl_trend_slope([]) == 0.0


class TestApplyScores:
    def _make_rows(self):
        # Wallet A: high pnl_trend, low win_volume
        # Wallet B: low pnl_trend, high win_volume
        return [
            {
                "address": "0xA",
                "pnl_trend": 50.0,
                "win_rate": 0.6,
                "total_volume": 500.0,
                "total_trades": 10,
                "win_volume": 10.0,
            },
            {
                "address": "0xB",
                "pnl_trend": 1.0,
                "win_rate": 0.6,
                "total_volume": 500.0,
                "total_trades": 10,
                "win_volume": 100.0,
            },
        ]

    def test_consistent_mode_favors_pnl_trend(self):
        from arbiter.scoring.whales import _apply_scores

        rows = self._make_rows()
        _apply_scores(rows, mode="consistent")
        by_addr = {r["address"]: r for r in rows}
        # consistent: pnl_trend weight=0.50 → wallet A ranks higher
        assert by_addr["0xA"]["score"] > by_addr["0xB"]["score"]

    def test_highroller_mode_favors_win_volume(self):
        from arbiter.scoring.whales import _apply_scores

        rows = self._make_rows()
        _apply_scores(rows, mode="highroller")
        by_addr = {r["address"]: r for r in rows}
        # highroller: win_volume weight=0.50 → wallet B ranks higher
        assert by_addr["0xB"]["score"] > by_addr["0xA"]["score"]

    def test_score_key_replaces_accumulator(self):
        from arbiter.scoring.whales import _apply_scores

        rows = self._make_rows()
        _apply_scores(rows, mode="frequent")
        for row in rows:
            assert "score" in row
            assert isinstance(row["score"], float)
            assert "_score_acc" not in row
