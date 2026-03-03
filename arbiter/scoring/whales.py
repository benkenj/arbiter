"""Whale scoring engine.

Computes P&L per wallet per market, derives composite scores using rank-based
percentile weighting, and upserts the wallets table.
"""
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from arbiter.config import Settings
from arbiter.db.models import Trade, Wallet

logger = logging.getLogger(__name__)

SCORE_WEIGHTS: dict[str, dict[str, float]] = {
    "consistent": {"pnl_trend": 0.50, "win_rate": 0.30, "total_volume": 0.10, "total_trades": 0.10},
    "highroller": {"win_volume": 0.50, "win_rate": 0.30, "pnl_trend": 0.10, "total_trades": 0.10},
    "frequent": {"total_trades": 0.40, "win_rate": 0.40, "total_volume": 0.10, "pnl_trend": 0.10},
}


def compute_pnl_for_market(trades: list) -> tuple[float, Optional[bool]]:
    """FIFO P&L computation for all trades on a single wallet+market pair.

    Returns (net_pnl, is_win).
    is_win is None when the position is still open (no exit, no resolution).
    """
    buys: deque = deque()
    realized_pnl = 0.0

    for trade in sorted(trades, key=lambda t: t.timestamp):
        if trade.side == "BUY":
            buys.append((trade.size, trade.price))
        elif trade.side == "SELL":
            sell_size = trade.size
            while sell_size > 0 and buys:
                buy_size, buy_price = buys[0]
                matched = min(sell_size, buy_size)
                realized_pnl += matched * (trade.price - buy_price)
                if matched == buy_size:
                    buys.popleft()
                else:
                    buys[0] = (buy_size - matched, buy_price)
                sell_size -= matched

    outcomes = {t.outcome for t in trades if t.outcome}
    if outcomes:
        outcome = outcomes.pop()
        resolution_price = 1.0 if outcome == "Yes" else 0.0
        for remaining_size, buy_price in buys:
            realized_pnl += remaining_size * (resolution_price - buy_price)
        is_win: Optional[bool] = realized_pnl > 0
    elif buys:
        return realized_pnl, None
    else:
        is_win = realized_pnl > 0

    return realized_pnl, is_win


def pnl_trend_slope(market_pnls: list[tuple[datetime, float]]) -> float:
    """Linear regression slope of P&L over time in USDC per day.

    Returns 0.0 if fewer than 2 data points.
    """
    if len(market_pnls) < 2:
        return 0.0
    times = [(t - market_pnls[0][0]).total_seconds() / 86400 for t, _ in market_pnls]
    pnls = [p for _, p in market_pnls]
    n = len(times)
    mean_t = sum(times) / n
    mean_p = sum(pnls) / n
    numerator = sum((t - mean_t) * (p - mean_p) for t, p in zip(times, pnls))
    denominator = sum((t - mean_t) ** 2 for t in times)
    return numerator / denominator if denominator != 0 else 0.0


def percentile_ranks(values: list[float]) -> list[float]:
    """Convert raw values to 0..1 percentile ranks.

    Tied values share the same rank. Single value returns [0.5].
    """
    if not values:
        return []
    sorted_unique = sorted(set(values))
    n = len(sorted_unique)
    if n == 1:
        rank_map = {sorted_unique[0]: 0.5}
    else:
        rank_map = {v: i / (n - 1) for i, v in enumerate(sorted_unique)}
    return [rank_map[v] for v in values]


def _compute_wallet_stats(trades: list, settings: Settings) -> list[dict]:
    """Group trades by wallet+market and compute per-wallet statistics.

    Returns a list of dicts with keys matching Wallet columns plus 'address'.
    """
    by_wallet_market: dict[tuple, list] = defaultdict(list)
    for trade in trades:
        by_wallet_market[(trade.wallet_address, trade.market_id)].append(trade)

    wallet_data: dict[str, dict] = {}

    for (wallet_address, market_id), market_trades in by_wallet_market.items():
        pnl, is_win = compute_pnl_for_market(market_trades)
        size_sum = sum(t.size for t in market_trades)
        first_ts = min(t.timestamp for t in market_trades)

        if wallet_address not in wallet_data:
            wallet_data[wallet_address] = {
                "address": wallet_address,
                "total_volume": 0.0,
                "total_trades": 0,
                "wins": 0,
                "win_volume": 0.0,
                "total_pnl": 0.0,
                "market_pnls": [],
            }

        wd = wallet_data[wallet_address]
        wd["total_volume"] += size_sum
        wd["total_pnl"] += pnl
        wd["market_pnls"].append((first_ts, pnl))

        if is_win is not None:
            wd["total_trades"] += 1
            if is_win:
                wd["wins"] += 1
                wd["win_volume"] += size_sum

    rows = []
    for address, wd in wallet_data.items():
        total_trades = wd["total_trades"]
        wins = wd["wins"]
        win_rate: Optional[float] = wins / total_trades if total_trades > 0 else None

        trend = pnl_trend_slope(wd["market_pnls"])

        rows.append({
            "address": address,
            "total_volume": wd["total_volume"],
            "total_trades": total_trades,
            "win_rate": win_rate,
            "win_volume": wd["win_volume"],
            "total_pnl": wd["total_pnl"],
            "pnl_trend": trend,
        })

    return rows


def _apply_scores(wallet_rows: list[dict], mode: str) -> None:
    """Compute composite score for each wallet using percentile ranking.

    Mutates wallet_rows in place — sets 'score' key on each dict.
    """
    weights = SCORE_WEIGHTS[mode]

    for dimension, weight in weights.items():
        raw_values = [
            row.get(dimension) if row.get(dimension) is not None else 0.0
            for row in wallet_rows
        ]
        ranks = percentile_ranks(raw_values)
        for row, rank in zip(wallet_rows, ranks):
            row.setdefault("_score_acc", 0.0)
            row["_score_acc"] += weight * rank

    for row in wallet_rows:
        row["score"] = row.pop("_score_acc", 0.0)


def _apply_is_tracked(wallet_rows: list[dict], settings: Settings) -> None:
    """Set is_tracked flag based on configured thresholds.

    Mutates wallet_rows in place.
    """
    for row in wallet_rows:
        total_trades = row.get("total_trades", 0)
        win_rate = row.get("win_rate")
        total_volume = row.get("total_volume", 0.0)

        row["is_tracked"] = (
            total_trades >= settings.whale_min_trades
            and win_rate is not None
            and win_rate >= settings.whale_min_win_rate
            and total_volume >= settings.whale_min_volume
        )


async def upsert_wallet_scores(session, rows: list[dict]) -> None:
    """Upsert wallet scoring rows using PostgreSQL ON CONFLICT DO UPDATE.

    This function is PostgreSQL-only. In test environments using aiosqlite,
    mock this function and test scoring logic independently.
    """
    if not rows:
        return

    now = datetime.now(tz=timezone.utc)
    for row in rows:
        row["last_scored_at"] = now

    stmt = pg_insert(Wallet).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["address"],
        set_={
            "win_rate": stmt.excluded.win_rate,
            "total_volume": stmt.excluded.total_volume,
            "total_trades": stmt.excluded.total_trades,
            "win_volume": stmt.excluded.win_volume,
            "total_pnl": stmt.excluded.total_pnl,
            "pnl_trend": stmt.excluded.pnl_trend,
            "score": stmt.excluded.score,
            "is_tracked": stmt.excluded.is_tracked,
            "last_scored_at": stmt.excluded.last_scored_at,
        },
    )
    await session.execute(stmt)
    await session.commit()


async def score_all_wallets(session, settings: Settings) -> int:
    """Compute scores for all wallets with trade history and upsert wallets table.

    Returns count of wallets scored.
    """
    since: Optional[datetime] = None
    if settings.whale_score_days > 0:
        since = datetime.now(tz=timezone.utc) - timedelta(days=settings.whale_score_days)

    query = select(Trade)
    if since is not None:
        query = query.where(Trade.timestamp >= since)

    result = await session.execute(query)
    trades = result.scalars().all()

    wallet_rows = _compute_wallet_stats(trades, settings)
    if not wallet_rows:
        return 0

    _apply_scores(wallet_rows, mode=settings.whale_score_mode)
    _apply_is_tracked(wallet_rows, settings)

    await upsert_wallet_scores(session, wallet_rows)
    logger.info("[scoring] scored %d wallets (mode=%s)", len(wallet_rows), settings.whale_score_mode)
    return len(wallet_rows)
