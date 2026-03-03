# Phase 4: Whale Identification - Research

**Researched:** 2026-03-02
**Domain:** SQLAlchemy async upsert, percentile ranking, argparse subparsers, P&L accounting, CLI table formatting
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Composite Score Formula:**
- Rank-based scoring: each dimension is converted to a percentile rank (0–1) across all wallets, then combined using mode-specific weights
- Four scoring dimensions: win rate, win volume (USDC on winning positions), trade volume (total), P&L trend (cumulative P&L slope over time)
- Three mode presets via `--mode` CLI flag:
  - `consistent`: P&L trend 50%, win rate 30%, trade volume 10%, trade count 10%
  - `highroller`: win volume 50%, win rate 30%, P&L trend 10%, trade count 10%
  - `frequent`: trade count 40%, win rate 40%, trade volume 10%, P&L trend 10%
- Time range filter: `--days N` rolling window (only trades from last N days count)
- DB storage policy: `WHALE_SCORE_MODE` and `WHALE_SCORE_DAYS` env vars define canonical scoring. `--mode`/`--days` CLI flags override for ad-hoc inspection only — they do not affect stored scores or `is_tracked`

**Win / P&L Definition:**
- P&L is price-based: `profit = size × (exit_price - entry_price)` for realized exits; `profit = size × (1.0 - entry_price)` for resolution wins; `profit = size × (0 - entry_price)` for resolution losses
- One result per wallet per market: aggregate all trades to compute net P&L. Win = net P&L > 0
- Realized exits count: if a wallet bought YES at 0.4 and sold at 0.7 before resolution, that's a realized win — does not require market resolution
- Truly open positions (no exit trade, no resolution outcome) are excluded from win rate but count toward volume metrics
- `win_volume` = total USDC size on winning market positions

**CLI Design:**
- `arbiter whales` → top 20 tracked whales (`is_tracked=true`), sorted by score desc. Columns: rank, address (abbreviated), win rate, total P&L, trade count, score
- `arbiter whales --all` → same table including below-threshold wallets
- `arbiter whales <address>` → full stats: all metrics + last 10 markets (question, side, P&L on that market, resolved?)
- `--mode consistent|highroller|frequent` → applies mode weights to ranking for display only, does not update DB
- `--days N` → rolling window — only trades from last N days contribute to displayed metrics
- Subcommand pattern: `argparse` subparsers, `arbiter whales` is a new subcommand

**Scoring Schedule:**
- Scoring runs after each ingestion cycle completes — called from within `ingestion_loop`, not a third `asyncio.gather` task
- Scores all wallets every cycle — upserts `wallets` table
- Upsert always writes: win_rate, total_volume, total_trades, score, last_scored_at; never duplicates records

### Claude's Discretion
- Exact FIFO vs LIFO accounting for matching buy/sell trades when computing realized P&L (FIFO is conventional)
- How to handle wallets with only open positions (no realized/resolved trades) — likely exclude from win rate, show in `--all` with N/A
- Normalization approach for percentile ranks (min-max or rank/n)
- Table formatting library (tabulate or manual f-string formatting)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| WHALE-01 | Scoring computes win_rate and total_volume for each wallet with trade history | P&L computation patterns, SQLAlchemy group-by query patterns |
| WHALE-02 | Wallets with fewer than `WHALE_MIN_TRADES` resolved trades excluded from classification | Filtering before threshold application in scoring logic |
| WHALE-03 | Wallets meeting `WHALE_MIN_WIN_RATE` and `WHALE_MIN_VOLUME` thresholds flagged `is_tracked = true` | Upsert pattern with conditional `is_tracked` |
| WHALE-04 | Scoring upserts wallets table — re-running does not duplicate records | SQLAlchemy `insert(...).on_conflict_do_update()` pattern |
| WHALE-05 | Scoring runs on configurable periodic interval | Called at end of each ingestion cycle; `WHALE_SCORE_INTERVAL_SECONDS` in config |
| CLI-01 | `arbiter whales` displays tracked whales sorted by score desc | argparse subparser + SQLAlchemy query + table formatter |
| CLI-02 | `arbiter whales --all` includes non-tracked wallets | Optional filter on `is_tracked` query |
| CLI-03 | `arbiter whales <address>` shows full stats + recent market history | Per-wallet query + join to trades + markets |
</phase_requirements>

---

## Summary

Phase 4 implements whale identification: a scoring job that reads all trades from the DB, computes P&L per wallet per market, derives composite scores using rank-based percentile weighting, upserts the `wallets` table, and exposes rankings via CLI subcommands.

The domain is almost entirely internal Python/SQLAlchemy work — no new external APIs. The main technical challenges are: (1) a schema migration to add missing columns (`win_volume`, `total_pnl`, `pnl_trend`) that the scoring dimensions require, (2) implementing FIFO trade matching for realized P&L correctly, (3) the async SQLAlchemy upsert pattern using `on_conflict_do_update`, and (4) wiring an `argparse` subparser into the existing `main_sync` dispatch.

The stack is already established (SQLAlchemy 2.x asyncio, pydantic-settings, pytest with aiosqlite). No new dependencies are required unless tabulate is added for table formatting — and a simple manual formatter is viable too.

**Primary recommendation:** Use `insert(...).on_conflict_do_update()` for upserts, `rank / n` for percentile normalization (no external dependencies), FIFO buy/sell matching, and manual f-string table formatting to avoid a new dependency.

---

## Standard Stack

### Core (all already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | >=2.0 | Async ORM + upsert via `insert().on_conflict_do_update()` | Already used; 2.x has first-class asyncio support |
| asyncpg | ^0.31.0 | PostgreSQL async driver | Already used; required by SQLAlchemy asyncio |
| pydantic-settings | ^2.0 | Config fields for new env vars | Already used; add `WHALE_SCORE_MODE`, `WHALE_SCORE_DAYS`, thresholds |
| pytest + pytest-asyncio | ^8.0 / ^0.23 | Test framework | Already configured, `asyncio_mode = "auto"` |
| aiosqlite | ^0.22.1 | In-memory SQLite for tests | Already used in integration tests |

### Optional New Dependency
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tabulate | ^0.9 | CLI table formatting | Only if manual f-string alignment is judged too fragile |

**Recommendation:** Do not add tabulate. Manual f-string formatting is adequate for 4–6 columns and avoids a new dependency. Use `str(val).ljust(width)` pattern.

**Installation (only if tabulate chosen):**
```bash
poetry add tabulate
```

---

## Architecture Patterns

### Recommended Project Structure
```
arbiter/
├── scoring/
│   ├── __init__.py          # empty
│   └── whales.py            # score_all_wallets(), score_wallet_display()
├── ingestion/
│   └── trades.py            # add: call score_all_wallets() at end of run_ingestion_cycle()
├── main.py                  # add: whales subparser, dispatch to display_whales()
└── config.py                # add: WHALE_SCORE_MODE, WHALE_SCORE_DAYS, threshold fields

alembic/versions/
└── 004_whale_scoring_columns.py  # adds win_volume, total_pnl, pnl_trend to wallets
```

### Pattern 1: SQLAlchemy Async Upsert (PostgreSQL ON CONFLICT)

**What:** Insert a row; if the unique key already exists, update specified columns. This is the correct pattern for idempotent scoring writes.

**When to use:** Every scoring cycle — write wallet stats without caring whether the row is new.

```python
# Source: SQLAlchemy 2.x docs — postgresql dialect insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from arbiter.db.models import Wallet
from datetime import datetime, timezone

async def upsert_wallet_scores(session, rows: list[dict]) -> None:
    if not rows:
        return
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
```

**Critical note:** Use `sqlalchemy.dialects.postgresql.insert`, not the generic `sqlalchemy.insert`. The `on_conflict_do_update` method is PostgreSQL-specific. In SQLite test environments, this import will fail — tests must either mock the upsert or use a separate test-safe upsert path.

**Test workaround:** For integration tests using aiosqlite, use a `SELECT + INSERT/UPDATE` pattern or mock `upsert_wallet_scores` and test the scoring logic separately from the DB write.

### Pattern 2: Async SQLAlchemy Query for Scoring Input

**What:** Fetch all trades within an optional date range, group by wallet+market for P&L computation.

```python
from sqlalchemy import select
from arbiter.db.models import Trade

async def fetch_trades_for_scoring(
    session, since: datetime | None = None
) -> list[Trade]:
    q = select(Trade)
    if since:
        q = q.where(Trade.timestamp >= since)
    result = await session.execute(q)
    return result.scalars().all()
```

**Note:** Load all trades into memory and compute P&L in Python — do NOT attempt complex SQL GROUP BY with P&L arithmetic. Python-side grouping is clearer and more testable.

### Pattern 3: Percentile Rank Normalization

**What:** Convert raw metric values to 0–1 ranks across all wallets. `rank/n` approach avoids sensitivity to outliers.

```python
def percentile_ranks(values: list[float]) -> list[float]:
    """Convert a list of raw values to 0..1 percentile ranks. Tied values share the same rank."""
    if not values:
        return []
    n = len(values)
    sorted_vals = sorted(set(values))
    rank_map = {v: i / (len(sorted_vals) - 1) if len(sorted_vals) > 1 else 0.5
                for i, v in enumerate(sorted_vals)}
    return [rank_map[v] for v in values]
```

**When to use:** Applied independently to each scoring dimension before weighting and summing.

### Pattern 4: FIFO P&L Matching

**What:** For each wallet+market, pair BUY trades against SELL trades in chronological order (FIFO) to compute realized P&L.

```python
from collections import deque

def compute_pnl_for_market(trades: list[Trade]) -> tuple[float, bool | None]:
    """
    Returns (net_pnl, is_win).
    is_win is None if position is still open (no exit, no resolution).
    """
    buys = deque()  # (size, price) in timestamp order
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

    # Check for resolution via outcome field on any trade in this market
    outcomes = {t.outcome for t in trades if t.outcome}
    if outcomes:
        # Use the resolution outcome to value remaining open buys
        outcome = outcomes.pop()  # e.g. "Yes" or "No"
        side_won = (outcome == "Yes")  # assumes BUY is always YES-side
        for remaining_size, buy_price in buys:
            resolution_price = 1.0 if side_won else 0.0
            realized_pnl += remaining_size * (resolution_price - buy_price)
        is_win = realized_pnl > 0
    elif buys:
        # Truly open — no exit, no resolution
        return realized_pnl, None
    else:
        is_win = realized_pnl > 0

    return realized_pnl, is_win
```

**Note:** The `outcome` field on trades is per-trade from the CLOB API. Trades on a resolved market will have `outcome = "Yes"` or `outcome = "No"`. Trades on open markets have `outcome = None` (nullable per Phase 3 migration).

### Pattern 5: argparse Subparsers

**What:** Add `arbiter whales` as a subcommand alongside the existing top-level flags.

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arbiter", ...)
    # Existing top-level flags
    parser.add_argument("--check", ...)
    parser.add_argument("--verbose", ...)

    # New subparsers
    subparsers = parser.add_subparsers(dest="command")

    whales_parser = subparsers.add_parser("whales", help="Display whale rankings")
    whales_parser.add_argument("address", nargs="?", help="Show stats for a single wallet")
    whales_parser.add_argument("--all", action="store_true", help="Include below-threshold wallets")
    whales_parser.add_argument(
        "--mode",
        choices=["consistent", "highroller", "frequent"],
        default=None,
        help="Scoring mode override for display (does not update DB)",
    )
    whales_parser.add_argument("--days", type=int, default=None, help="Rolling window in days")

    return parser
```

**Dispatch in `main_sync`:**
```python
def main_sync() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = load_settings()
    configure_logging(...)

    if args.command == "whales":
        asyncio.run(display_whales(args, settings))
    else:
        asyncio.run(main(args, settings))
```

**Critical:** argparse `subparsers` are optional by default in Python 3.9+. If `args.command` is `None` (no subcommand), fall through to existing service loop behavior. This preserves backward compatibility with `arbiter --check` and bare `arbiter`.

### Pattern 6: P&L Trend (Linear Slope)

**What:** Compute the slope of cumulative P&L over time for a wallet — positive slope = rising performance.

```python
def pnl_trend(market_pnls: list[tuple[datetime, float]]) -> float:
    """
    Compute linear regression slope of cumulative P&L over time.
    market_pnls: list of (timestamp, pnl) sorted by timestamp.
    Returns slope (USDC per day). Returns 0.0 if fewer than 2 data points.
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
```

**Note:** Uses individual market P&L values at their timestamp (not cumulative running sum) — simple and avoids needing ordered time series. Slope sign is what matters for the consistent mode.

### Anti-Patterns to Avoid

- **Using `sqlalchemy.insert` instead of `sqlalchemy.dialects.postgresql.insert` for upserts:** Generic insert has no `on_conflict_do_update`. Will raise `AttributeError` at runtime.
- **Computing P&L entirely in SQL:** Complex CTEs for FIFO matching are fragile and untestable. Do it in Python.
- **Adding scoring as a third `asyncio.gather` task:** CONTEXT.md locked scoring to run inside `ingestion_loop` at the end of each cycle.
- **Storing CLI-only computed scores back to DB:** `--mode` and `--days` override values must never touch `wallets` table.
- **Assuming `side == "BUY"` means YES-side universally:** The CLOB data may have maker/taker sides. Use the `outcome` field on the trade as the authoritative resolution signal.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PostgreSQL upsert | Custom SELECT + INSERT/UPDATE logic | `pg_insert().on_conflict_do_update()` | Race-condition-free, single round trip |
| Config validation | Custom env var parser | pydantic-settings `Field()` (already in use) | Already established pattern, validated at startup |
| Test DB sessions | Real PostgreSQL in unit tests | aiosqlite in-memory + existing conftest fixtures | Already established pattern |

**Key insight:** This phase is pure Python logic on top of an established stack. The only novel technical element is `pg_insert().on_conflict_do_update()` — everything else (async queries, config, test fixtures) follows Phase 3 patterns exactly.

---

## Schema Migration Required

The current `Wallet` model (from migration `1c5960c71bfe`) is missing columns required by the locked scoring dimensions and CLI output:

| Column | Type | Purpose | Missing? |
|--------|------|---------|---------|
| `win_rate` | Float | Win rate ratio | Already exists |
| `total_volume` | Float | Total USDC traded | Already exists |
| `total_trades` | Integer | Total resolved market count | Already exists |
| `score` | Float | Composite score | Already exists |
| `last_scored_at` | DateTime | Scoring timestamp | Already exists |
| `is_tracked` | Boolean | Whale classification flag | Already exists |
| **`win_volume`** | **Float** | **USDC on winning positions (highroller mode)** | **MISSING** |
| **`total_pnl`** | **Float** | **Cumulative realized P&L (CLI output + consistent mode)** | **MISSING** |
| **`pnl_trend`** | **Float** | **P&L slope over time (consistent mode weight)** | **MISSING** |

**A new Alembic migration (004) is required** to add these three columns before scoring can write to them.

Migration pattern (follows project convention — manual authoring, no autogenerate):
```python
# alembic/versions/004_whale_scoring_columns.py
revision = "004_whale_scoring_columns"
down_revision = "a3f8b2c91d45"

def upgrade():
    op.add_column("wallets", sa.Column("win_volume", sa.Float(), nullable=True))
    op.add_column("wallets", sa.Column("total_pnl", sa.Float(), nullable=True))
    op.add_column("wallets", sa.Column("pnl_trend", sa.Float(), nullable=True))

def downgrade():
    op.drop_column("wallets", "pnl_trend")
    op.drop_column("wallets", "total_pnl")
    op.drop_column("wallets", "win_volume")
```

The `Wallet` ORM model (`arbiter/db/models.py`) must also be updated to add these three `mapped_column` fields as `Optional[float]`.

---

## Common Pitfalls

### Pitfall 1: pg_insert Unavailable in SQLite Tests

**What goes wrong:** `from sqlalchemy.dialects.postgresql import insert as pg_insert` is PostgreSQL-specific. Integration tests use aiosqlite, which will fail when the upsert statement is constructed.

**Why it happens:** SQLite does not implement `ON CONFLICT DO UPDATE` with the same syntax. The `pg_insert` object itself is PostgreSQL-only.

**How to avoid:** Keep the upsert logic in a separate function (`upsert_wallet_scores`). In unit tests, mock this function entirely and test scoring logic independently. Integration tests can use a plain INSERT + SELECT-verify pattern instead of testing the upsert path directly.

**Warning signs:** `AttributeError: 'Insert' object has no attribute 'on_conflict_do_update'` when using generic insert; `OperationalError` from aiosqlite when pg_insert is used.

### Pitfall 2: Wallets With No Resolvable Trades Skipped from win_rate but Counted in Volume

**What goes wrong:** A wallet that only has open positions (no exits, no resolved markets) would have no win rate data. Excluding them entirely from scoring causes them to vanish from `--all` view.

**Why it happens:** The scoring code filters to `resolved trades only` for win rate.

**How to avoid:** Score all wallets that appear in the trades table. Set `win_rate = None` and exclude from `is_tracked` qualification if no resolved/exited positions exist. Show `N/A` for win rate in CLI. Include in `--all` for threshold tuning.

### Pitfall 3: CLI Subparser Breaks Existing `arbiter --check`

**What goes wrong:** After adding `add_subparsers`, the existing `--check` flag may not be recognized if dispatch logic routes all commands through the subparser path.

**Why it happens:** argparse subparser `dest` is `None` when no subcommand is given, but careless `args.command` checks can raise `AttributeError`.

**How to avoid:** Check `getattr(args, 'command', None)` not `args.command`. Route to existing behavior when `command is None`.

### Pitfall 4: Mode-Override Scores Written to DB

**What goes wrong:** If `--mode` or `--days` are passed and the display function calls the same scoring path as the background job, it may accidentally write display-only scores back to `wallets`.

**Why it happens:** Reusing the same function for both background scoring and CLI display without a `dry_run` flag.

**How to avoid:** The CLI display path must never call `upsert_wallet_scores`. It reads from DB (stored canonical scores) and recomputes ranks in-memory for display only if `--mode` or `--days` differ from the stored values.

### Pitfall 5: Percentile Rank With a Single Wallet

**What goes wrong:** `rank / (n-1)` division by zero when only one wallet exists.

**Why it happens:** Edge case in rank normalization.

**How to avoid:** Guard with `if len(sorted_vals) > 1 else 0.5` — single wallet gets a neutral 0.5 rank.

### Pitfall 6: WHALE-05 vs CONTEXT Conflict

**What goes wrong:** REQUIREMENTS.md says scoring runs on `WHALE_SCORE_INTERVAL_SECONDS` (a dedicated timer). CONTEXT.md locks scoring to run inside `ingestion_loop` after each cycle, not on a separate timer.

**Resolution:** CONTEXT.md takes precedence (it reflects the user's explicit decision). The config field `WHALE_SCORE_INTERVAL_SECONDS` should still exist (per WHALE-05) but is effectively unused in v1 — the scoring interval equals the ingestion interval. Document this in config field description.

---

## Code Examples

### Full Scoring Pipeline Skeleton

```python
# arbiter/scoring/whales.py
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from arbiter.config import Settings
from arbiter.db.models import Trade, Wallet

logger = logging.getLogger(__name__)

SCORE_WEIGHTS = {
    "consistent":  {"pnl_trend": 0.50, "win_rate": 0.30, "total_volume": 0.10, "total_trades": 0.10},
    "highroller":  {"win_volume": 0.50, "win_rate": 0.30, "pnl_trend": 0.10,   "total_trades": 0.10},
    "frequent":    {"total_trades": 0.40, "win_rate": 0.40, "total_volume": 0.10, "pnl_trend": 0.10},
}


async def score_all_wallets(session, settings: Settings) -> int:
    """
    Compute scores for all wallets with trade history. Upserts wallets table.
    Returns count of wallets scored.
    """
    since = None
    if settings.whale_score_days > 0:
        since = datetime.now(tz=timezone.utc) - timedelta(days=settings.whale_score_days)

    result = await session.execute(select(Trade).where(
        Trade.timestamp >= since if since else True
    ))
    trades = result.scalars().all()

    wallet_rows = _compute_wallet_stats(trades, settings)
    if not wallet_rows:
        return 0

    _apply_scores(wallet_rows, mode=settings.whale_score_mode)
    _apply_is_tracked(wallet_rows, settings)

    await upsert_wallet_scores(session, wallet_rows)
    logger.info("[scoring] scored %d wallets (mode=%s)", len(wallet_rows), settings.whale_score_mode)
    return len(wallet_rows)
```

### CLI Display Query Pattern

```python
# Display stored scores — no DB write
async def display_whales(args, settings: Settings) -> None:
    from arbiter.db.session import make_engine, make_session_factory
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    try:
        async with session_factory() as session:
            if args.address:
                await _show_wallet_detail(session, args.address)
            else:
                await _show_whale_table(session, show_all=args.all)
    finally:
        await engine.dispose()
```

### Config Fields to Add

```python
# In arbiter/config.py Settings class:
whale_min_trades: int = Field(
    default=10,
    description="Minimum resolved trades for whale classification. Default: 10.",
)
whale_min_win_rate: float = Field(
    default=0.6,
    description="Minimum win rate (0.0–1.0) for whale classification. Default: 0.6.",
)
whale_min_volume: float = Field(
    default=1000.0,
    description="Minimum total USDC volume for whale classification. Default: 1000.",
)
whale_score_mode: str = Field(
    default="consistent",
    description="Scoring mode: consistent | highroller | frequent. Default: consistent.",
)
whale_score_days: int = Field(
    default=0,
    description="Rolling window in days for scoring (0 = all-time). Default: 0.",
)
whale_score_interval_seconds: int = Field(
    default=300,
    description="Scoring interval in seconds (informational; scoring runs after each ingestion cycle). Default: 300.",
)
```

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|-----------------|-------|
| SQLAlchemy Core `insert().prefix_with("OR REPLACE")` | `pg_insert().on_conflict_do_update()` | PostgreSQL-specific; handles partial updates correctly |
| Pandas for groupby/rank | Pure Python `defaultdict` + sort | No pandas in this project; stdlib is sufficient |
| Separate scoring daemon/APScheduler | Inline call in ingestion loop | Established project pattern (no APScheduler) |

---

## Open Questions

1. **BUY side = YES-side assumption**
   - What we know: CLOB API `side` field is "BUY" or "SELL". The `outcome` column is "Yes" or "No" when resolved.
   - What's unclear: Does `side == "BUY"` always mean the wallet bet YES, or can maker/taker flip this?
   - Recommendation: Use `outcome` field to determine resolution win/loss — it's authoritative. For realized P&L (sell before resolution), the direction of price movement (exit > entry = profit) is side-agnostic. The FIFO pattern handles this correctly without assuming YES-side.

2. **win_volume column granularity**
   - What we know: `win_volume = sum of size on winning market positions`
   - What's unclear: Is this total USDC committed on winning markets, or total realized profit only?
   - Recommendation: Total USDC `size` on winning markets (not profit). This is the raw volume signal for highroller mode.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.23 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `asyncio_mode = "auto"` |
| Quick run command | `poetry run pytest tests/unit/test_scoring.py -x -q` |
| Full suite command | `poetry run pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| WHALE-01 | `_compute_wallet_stats` returns correct win_rate, total_volume for known trades | unit | `poetry run pytest tests/unit/test_scoring.py::TestComputeWalletStats -x` | Wave 0 |
| WHALE-01 | P&L computed correctly for realized exits and resolutions | unit | `poetry run pytest tests/unit/test_scoring.py::TestComputePnl -x` | Wave 0 |
| WHALE-02 | Wallets below `WHALE_MIN_TRADES` threshold not marked `is_tracked` | unit | `poetry run pytest tests/unit/test_scoring.py::TestIsTracked -x` | Wave 0 |
| WHALE-03 | Wallets meeting both thresholds have `is_tracked=True` | unit | `poetry run pytest tests/unit/test_scoring.py::TestIsTracked -x` | Wave 0 |
| WHALE-04 | `score_all_wallets` upserts — second run does not duplicate | integration | `poetry run pytest tests/integration/test_scoring_integration.py -x` | Wave 0 |
| WHALE-05 | `ingestion_loop` calls scoring after each cycle | unit | `poetry run pytest tests/unit/test_ingestion.py::TestIngestionCallsScoring -x` | Wave 0 |
| CLI-01 | `display_whales` queries tracked wallets, sorts by score desc, prints table | unit | `poetry run pytest tests/unit/test_cli_whales.py::TestDisplayWhales -x` | Wave 0 |
| CLI-02 | `--all` flag includes non-tracked wallets in output | unit | `poetry run pytest tests/unit/test_cli_whales.py::TestDisplayWhalesAll -x` | Wave 0 |
| CLI-03 | `<address>` shows per-wallet detail with last 10 markets | unit | `poetry run pytest tests/unit/test_cli_whales.py::TestDisplayWalletDetail -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/test_scoring.py -x -q`
- **Per wave merge:** `poetry run pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_scoring.py` — covers WHALE-01, WHALE-02, WHALE-03, WHALE-05
- [ ] `tests/integration/test_scoring_integration.py` — covers WHALE-04 (upsert idempotency)
- [ ] `tests/unit/test_cli_whales.py` — covers CLI-01, CLI-02, CLI-03

*(Existing `tests/conftest.py` fixtures — `async_engine`, `session_factory`, `settings` — are reusable for Phase 4 tests. No conftest changes needed.)*

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `arbiter/db/models.py`, `arbiter/ingestion/trades.py`, `arbiter/main.py`, `arbiter/config.py` — all patterns verified in-repo
- Direct schema inspection: `alembic/versions/*.py` — confirmed missing columns (`win_volume`, `total_pnl`, `pnl_trend`)
- `pyproject.toml` — confirmed stack versions and dev dependencies
- `tests/` directory — confirmed test infrastructure, conftest fixtures, asyncio_mode="auto"

### Secondary (MEDIUM confidence)
- SQLAlchemy 2.x `on_conflict_do_update` pattern — standard PostgreSQL upsert idiom, consistent with SQLAlchemy 2.x async docs (https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert)
- argparse subparsers behavior (Python 3.12 stdlib) — verified against Python docs (https://docs.python.org/3/library/argparse.html#sub-commands)

### Tertiary (LOW confidence)
- None — all claims are either code-verified or stdlib-documented.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in project, versions confirmed in pyproject.toml
- Architecture: HIGH — all patterns follow established Phase 3 conventions, verified in source
- Schema gap: HIGH — confirmed by direct inspection of Wallet ORM model vs CONTEXT.md scoring dimensions
- Pitfalls: HIGH — most derived from direct code inspection (pg_insert SQLite gap, subparser behavior)
- P&L accounting: MEDIUM — FIFO pattern is conventional and matches CONTEXT.md decision, but outcome field interpretation has one open question (BUY-side assumption)

**Research date:** 2026-03-02
**Valid until:** 2026-04-02 (stable stack, 30-day window)
