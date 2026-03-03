"""Unit tests for arbiter whales CLI subcommand (04-03)."""
import argparse
import sys
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arbiter.main import build_parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_wallet(
    address="0xabcdefgh12345678",
    win_rate=0.75,
    total_pnl=100.0,
    total_volume=1000.0,
    win_volume=800.0,
    pnl_trend=5.0,
    total_trades=20,
    score=0.8,
    is_tracked=True,
    last_scored_at=None,
):
    w = MagicMock()
    w.address = address
    w.win_rate = win_rate
    w.total_pnl = total_pnl
    w.total_volume = total_volume
    w.win_volume = win_volume
    w.pnl_trend = pnl_trend
    w.total_trades = total_trades
    w.score = score
    w.is_tracked = is_tracked
    w.last_scored_at = last_scored_at
    return w


def make_trade(wallet_address, market_id, size=10.0, side="BUY", price=0.5, timestamp=None):
    from datetime import datetime, timezone
    t = MagicMock()
    t.wallet_address = wallet_address
    t.market_id = market_id
    t.size = size
    t.side = side
    t.price = price
    t.timestamp = timestamp or datetime(2024, 1, 1, tzinfo=timezone.utc)
    t.outcome = None
    return t


def make_market(market_id, question="Will X happen?"):
    m = MagicMock()
    m.id = market_id
    m.question = question
    m.resolved = False
    return m


# ---------------------------------------------------------------------------
# TestArgparserWhalesSubcommand
# ---------------------------------------------------------------------------

class TestArgparserWhalesSubcommand:
    def test_whales_no_args(self):
        parser = build_parser()
        args = parser.parse_args(["whales"])
        assert args.command == "whales"
        assert args.address is None
        assert args.show_all is False

    def test_whales_all_flag(self):
        parser = build_parser()
        args = parser.parse_args(["whales", "--all"])
        assert args.show_all is True

    def test_whales_address_positional(self):
        parser = build_parser()
        args = parser.parse_args(["whales", "0xabcdef"])
        assert args.address == "0xabcdef"

    def test_whales_mode_flag(self):
        parser = build_parser()
        args = parser.parse_args(["whales", "--mode", "highroller"])
        assert args.mode == "highroller"

    def test_whales_days_flag(self):
        parser = build_parser()
        args = parser.parse_args(["whales", "--days", "30"])
        assert args.days == 30

    def test_check_flag_backward_compat(self):
        parser = build_parser()
        args = parser.parse_args(["--check"])
        assert getattr(args, "command", None) is None

    def test_bare_arbiter_backward_compat(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert getattr(args, "command", None) is None


# ---------------------------------------------------------------------------
# TestDisplayWhales
# ---------------------------------------------------------------------------

class TestDisplayWhales:
    async def test_shows_tracked_wallets_sorted_by_score(self, capsys):
        from arbiter.main import display_whales

        wallet_a = make_wallet(address="0xAAAAAAAABBBBBB", score=0.8)
        wallet_b = make_wallet(address="0xCCCCCCCCDDDDDD", score=0.6)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [wallet_a, wallet_b]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()
        mock_factory = MagicMock(return_value=session)

        args = argparse.Namespace(command="whales", address=None, show_all=False, mode=None, days=None)
        settings = MagicMock()
        settings.database_url = "postgresql+asyncpg://test"
        settings.whale_score_mode = "consistent"

        with patch("arbiter.main.make_engine", return_value=mock_engine), \
             patch("arbiter.main.make_session_factory", return_value=mock_factory):
            await display_whales(args, settings)

        captured = capsys.readouterr()
        output = captured.out

        # Header check
        assert "Rank" in output
        assert "Address" in output
        assert "Win Rate" in output
        assert "Score" in output

        # Both addresses appear (abbreviated)
        assert "0xAAAAA" in output
        assert "0xCCCCC" in output

        # Score 0.8 row before score 0.6 row
        pos_a = output.index("0xAAAAA")
        pos_b = output.index("0xCCCCC")
        assert pos_a < pos_b, "Higher score wallet should appear first"

    async def test_address_abbreviated(self, capsys):
        from arbiter.main import display_whales

        addr = "0x1234567890abcdef1234"
        wallet = make_wallet(address=addr, score=0.9)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [wallet]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()
        mock_factory = MagicMock(return_value=session)

        args = argparse.Namespace(command="whales", address=None, show_all=False, mode=None, days=None)
        settings = MagicMock()
        settings.database_url = "postgresql+asyncpg://test"
        settings.whale_score_mode = "consistent"

        with patch("arbiter.main.make_engine", return_value=mock_engine), \
             patch("arbiter.main.make_session_factory", return_value=mock_factory):
            await display_whales(args, settings)

        captured = capsys.readouterr()
        # Abbreviated: first 8 + "..." + last 6
        expected_abbr = addr[:8] + "..." + addr[-6:]
        assert expected_abbr in captured.out

    async def test_no_whales_message_when_empty(self, capsys):
        from arbiter.main import display_whales

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()
        mock_factory = MagicMock(return_value=session)

        args = argparse.Namespace(command="whales", address=None, show_all=False, mode=None, days=None)
        settings = MagicMock()
        settings.database_url = "postgresql+asyncpg://test"
        settings.whale_score_mode = "consistent"

        with patch("arbiter.main.make_engine", return_value=mock_engine), \
             patch("arbiter.main.make_session_factory", return_value=mock_factory):
            await display_whales(args, settings)

        captured = capsys.readouterr()
        assert "No whales found" in captured.out


# ---------------------------------------------------------------------------
# TestDisplayWhalesAll
# ---------------------------------------------------------------------------

class TestDisplayWhalesAll:
    async def test_default_shows_only_tracked(self, capsys):
        from arbiter.main import display_whales

        tracked_addr = "0xTRACKEDAABBCCDD"  # first 8: "0xTRACKE", last 6: "BBCCDD"
        not_tracked_addr = "0xNOTTRACKEDEEFF"  # first 8: "0xNOTTRA", last 6: "DEEFF" -- wait, 17 chars
        tracked = make_wallet(address=tracked_addr, score=0.8, is_tracked=True)
        not_tracked = make_wallet(address=not_tracked_addr, score=0.3, is_tracked=False)

        call_count = [0]

        async def mock_execute(stmt):
            call_count[0] += 1
            result = MagicMock()
            result.scalars.return_value.all.return_value = [tracked]
            return result

        session = AsyncMock()
        session.execute = mock_execute
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()
        mock_factory = MagicMock(return_value=session)

        args = argparse.Namespace(command="whales", address=None, show_all=False, mode=None, days=None)
        settings = MagicMock()
        settings.database_url = "postgresql+asyncpg://test"
        settings.whale_score_mode = "consistent"

        with patch("arbiter.main.make_engine", return_value=mock_engine), \
             patch("arbiter.main.make_session_factory", return_value=mock_factory):
            await display_whales(args, settings)

        captured = capsys.readouterr()
        # tracked_addr[:8] = "0xTRACKE", last 6 = "BBCCDD"
        assert "0xTRACKE" in captured.out
        assert "BBCCDD" in captured.out
        # not_tracked address should not appear at all
        assert not_tracked_addr not in captured.out
        assert "0xNOTTRA" not in captured.out

    async def test_show_all_includes_untracked(self, capsys):
        from arbiter.main import display_whales

        # Use unique prefixes that will be visible in abbreviated form
        tracked = make_wallet(address="0xAAAAAAAABBBBBB", score=0.8, is_tracked=True)
        not_tracked = make_wallet(address="0xCCCCCCCCDDDDDD", score=0.3, is_tracked=False)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [tracked, not_tracked]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()
        mock_factory = MagicMock(return_value=session)

        args = argparse.Namespace(command="whales", address=None, show_all=True, mode=None, days=None)
        settings = MagicMock()
        settings.database_url = "postgresql+asyncpg://test"
        settings.whale_score_mode = "consistent"

        with patch("arbiter.main.make_engine", return_value=mock_engine), \
             patch("arbiter.main.make_session_factory", return_value=mock_factory):
            await display_whales(args, settings)

        captured = capsys.readouterr()
        # Both abbreviations should appear (first 8 chars of each)
        assert "0xAAAAAA" in captured.out
        assert "0xCCCCCC" in captured.out


# ---------------------------------------------------------------------------
# TestDisplayWalletDetail
# ---------------------------------------------------------------------------

class TestDisplayWalletDetail:
    async def test_shows_wallet_stats_and_markets(self, capsys):
        from arbiter.main import display_whales

        addr = "0xABCDEF1234567890"
        wallet = make_wallet(address=addr, win_rate=0.7, total_pnl=250.0)

        markets_data = [
            make_market(1, "Will Biden win?"),
            make_market(2, "Will BTC hit 100k?"),
            make_market(3, "Will it rain?"),
        ]

        trades_data = [
            make_trade(addr, 1, size=50.0),
            make_trade(addr, 2, size=100.0),
            make_trade(addr, 3, size=75.0),
        ]

        execute_results = []

        # First call: get wallet
        wallet_result = MagicMock()
        wallet_result.scalars.return_value.first.return_value = wallet
        execute_results.append(wallet_result)

        # Second call: get trades with markets joined
        trades_result = MagicMock()
        # Return (trade, market) tuples
        trades_result.all.return_value = [(t, m) for t, m in zip(trades_data, markets_data)]
        execute_results.append(trades_result)

        call_idx = [0]

        async def mock_execute(stmt):
            idx = call_idx[0]
            call_idx[0] += 1
            return execute_results[idx]

        session = AsyncMock()
        session.execute = mock_execute
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()
        mock_factory = MagicMock(return_value=session)

        args = argparse.Namespace(command="whales", address=addr, show_all=False, mode=None, days=None)
        settings = MagicMock()
        settings.database_url = "postgresql+asyncpg://test"
        settings.whale_score_mode = "consistent"

        with patch("arbiter.main.make_engine", return_value=mock_engine), \
             patch("arbiter.main.make_session_factory", return_value=mock_factory):
            await display_whales(args, settings)

        captured = capsys.readouterr()
        output = captured.out

        # Wallet stats present
        assert addr in output
        assert "70.0%" in output or "0.7" in output
        assert "250" in output  # total_pnl

        # Market questions appear
        assert "Will Biden win?" in output or "Will Biden win"[:20] in output
        assert "Will BTC hit 100k?" in output or "Will BTC hit 100k"[:20] in output

    async def test_unknown_wallet_prints_error(self, capsys):
        from arbiter.main import display_whales

        wallet_result = MagicMock()
        wallet_result.scalars.return_value.first.return_value = None

        session = AsyncMock()
        session.execute = AsyncMock(return_value=wallet_result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()
        mock_factory = MagicMock(return_value=session)

        args = argparse.Namespace(command="whales", address="0xDEADBEEF", show_all=False, mode=None, days=None)
        settings = MagicMock()
        settings.database_url = "postgresql+asyncpg://test"
        settings.whale_score_mode = "consistent"

        with patch("arbiter.main.make_engine", return_value=mock_engine), \
             patch("arbiter.main.make_session_factory", return_value=mock_factory):
            await display_whales(args, settings)

        captured = capsys.readouterr()
        assert "not found" in captured.out.lower() or "0xDEADBEEF" in captured.out
