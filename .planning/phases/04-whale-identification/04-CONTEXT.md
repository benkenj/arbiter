# Phase 4: Whale Identification - Context

**Gathered:** 2026-03-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Score all wallets in the trades table by a composite of win rate, volume, and P&L trend. Maintain a `wallets` table with configurable thresholds determining which wallets are classified as tracked whales. Expose whale rankings via a CLI subcommand. Position monitoring and Discord alerts are Phase 6.

</domain>

<decisions>
## Implementation Decisions

### Composite Score Formula
- Rank-based scoring: each dimension is converted to a percentile rank (0–1) across all wallets, then dimensions are combined using mode-specific weights
- Four scoring dimensions: win rate, win volume (volume on winning market positions), trade volume (total), P&L trend (cumulative P&L slope over time)
- Three mode presets, selectable via `--mode` CLI flag:
  - `consistent`: P&L trend 50%, win rate 30%, trade volume 10%, trade count 10%
  - `highroller`: win volume 50%, win rate 30%, P&L trend 10%, trade count 10%
  - `frequent`: trade count 40%, win rate 40%, trade volume 10%, P&L trend 10%
- Time range filter: `--days N` rolling window (only trades from last N days count toward all metrics)
- DB storage policy: env vars define canonical scoring (`WHALE_SCORE_MODE`, `WHALE_SCORE_DAYS`); `is_tracked` reflects this policy. CLI `--mode`/`--days` flags override for ad-hoc inspection only — they do not affect stored scores or `is_tracked`.

### Win / P&L Definition
- P&L is price-based, not binary: `profit = size × (exit_price - entry_price)` for realized exits; `profit = size × (1.0 - entry_price)` for resolution wins, `profit = size × (0 - entry_price)` for resolution losses
- One result per wallet per market: aggregate all trades on a market for a wallet to compute net P&L. Win = net P&L > 0.
- Realized exits count: if a wallet bought YES at 0.4 and sold at 0.7 before resolution, that's a realized win — does not require market resolution
- Truly open positions (no exit trade, no resolution outcome) are excluded from win rate calculation but count toward trade volume metrics
- `win volume` = total USDC size on winning market positions (net P&L > 0)

### CLI Design
- `arbiter whales` → top 20 tracked whales (`is_tracked=true`), sorted by score desc. Table columns: rank, address (abbreviated), win rate, total P&L, trade count, score
- `arbiter whales --all` → same table but includes below-threshold wallets, for threshold tuning
- `arbiter whales <address>` → full stats for one wallet: all metrics + last 10 markets (market question, side, P&L on that market, resolved?)
- `--mode consistent|highroller|frequent` → applies mode weights to ranking (display only, does not update DB)
- `--days N` → rolling window: only trades from last N days contribute to displayed metrics
- Subcommand pattern: `argparse` subparsers, `arbiter whales` is a new subcommand (not a flag on the existing parser)

### Scoring Schedule
- Scoring runs after each ingestion cycle completes — called from within the ingestion loop, not on a separate timer
- Scores all wallets every cycle (not just wallets with new trades) — upserts `wallets` table
- Upsert behavior: scoring always writes win_rate, total_volume, total_trades, score, last_scored_at; never duplicates records

### Claude's Discretion
- Exact FIFO vs LIFO accounting for matching buy/sell trades when computing realized P&L (either is fine; FIFO is conventional)
- How to handle wallets with only open positions (no realized/resolved trades) — likely exclude from win rate, show in --all with N/A
- Normalization approach for percentile ranks (e.g. min-max or rank/n)
- Table formatting library (tabulate or manual f-string formatting)

</decisions>

<specifics>
## Specific Ideas

- User wants to be able to find: high-frequency traders with decent win rates, high-conviction low-frequency traders (few trades, large size), and steady climbers (P&L trend positive over time). The mode presets encode exactly these three use cases.
- "I want to be able to configure this via the CLI" — modes and days are primary levers, not just env vars

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Wallet` ORM model (`arbiter/db/models.py`): already has all needed columns — `win_rate`, `total_volume`, `total_trades`, `score`, `last_scored_at`, `is_tracked`. No schema migration needed for scoring.
- `Trade` ORM model: `wallet_address`, `market_id`, `side`, `size`, `price`, `timestamp`, `outcome` — all data for P&L computation is present
- `config.py` pydantic-settings `Field` pattern: add `WHALE_SCORE_MODE`, `WHALE_SCORE_DAYS`, existing threshold fields (`WHALE_MIN_TRADES`, `WHALE_MIN_WIN_RATE`, `WHALE_MIN_VOLUME`) follow the same pattern

### Established Patterns
- Periodic loops: `discovery_loop` and `ingestion_loop` in `main.py` via `asyncio.gather` — scoring runs inside `ingestion_loop` after each cycle, not as a third gather task
- Upsert pattern: Phase 3 ingestion upserts trades — scoring follows same approach for wallets
- Config: all thresholds and intervals are pydantic-settings fields with defaults and descriptions

### Integration Points
- `arbiter/scoring/whales.py` — new file, new package (`arbiter/scoring/__init__.py`)
- `arbiter/ingestion/trades.py` — scoring is called at the end of each ingestion cycle
- `arbiter/main.py` — `whales` subcommand added to argparse; `main_sync` routes to scoring display instead of the service loop
- `arbiter/config.py` — add `WHALE_SCORE_MODE` (default: `consistent`), `WHALE_SCORE_DAYS` (default: `0` = all-time), and the existing threshold fields

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 04-whale-identification*
*Context gathered: 2026-03-02*
