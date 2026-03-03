---
phase: 04-whale-identification
plan: "02"
subsystem: scoring
tags: [python, sqlalchemy, postgresql, pnl, percentile-ranking, whale-scoring, fifo]

requires:
  - phase: 04-01
    provides: "Wallet ORM model with win_volume, total_pnl, pnl_trend columns; migration 004"

provides:
  - "score_all_wallets() — async entry point for scoring all wallets from trade history"
  - "_compute_wallet_stats() — FIFO P&L computation grouped by wallet+market"
  - "_apply_scores() — three-mode composite percentile scoring (consistent/highroller/frequent)"
  - "_apply_is_tracked() — threshold-based whale classification"
  - "upsert_wallet_scores() — PostgreSQL ON CONFLICT DO UPDATE upsert"
  - "Six whale_* config fields in Settings"
  - "Unit and integration test suites for scoring engine"

affects:
  - "04-03 (CLI whales subcommand depends on score_all_wallets and Wallet model)"
  - "arbiter/ingestion/trades.py (will call score_all_wallets after each cycle)"

tech-stack:
  added: []
  patterns:
    - "FIFO P&L matching using collections.deque for buy/sell trade pairing"
    - "Percentile rank normalization (rank/n) — no external dependencies"
    - "pg_insert ON CONFLICT DO UPDATE for idempotent wallet upserts"
    - "Mock upsert_wallet_scores in aiosqlite integration tests — test logic layer independently"
    - "score_all_wallets() called from ingestion loop (not a separate asyncio.gather task)"

key-files:
  created:
    - "arbiter/scoring/__init__.py"
    - "arbiter/scoring/whales.py"
    - "tests/unit/test_scoring.py"
    - "tests/integration/test_scoring_integration.py"
  modified:
    - "arbiter/config.py"

key-decisions:
  - "FIFO buy/sell matching for realized P&L — conventional and testable without SQL CTEs"
  - "Mock upsert_wallet_scores in integration tests — pg_insert is PostgreSQL-only, aiosqlite cannot execute it"
  - "percentile_ranks uses rank/n normalization — avoids outlier sensitivity, no numpy needed"
  - "score_all_wallets() called from ingestion loop after each cycle per CONTEXT.md lock (WHALE_SCORE_INTERVAL_SECONDS config field retained but informational only)"

patterns-established:
  - "Pattern: FIFO P&L — compute_pnl_for_market() with deque, outcome field for resolution"
  - "Pattern: Scoring pipeline — _compute_wallet_stats → _apply_scores → _apply_is_tracked → upsert"
  - "Pattern: Integration test isolation — mock pg_insert path, test logic layer with aiosqlite"

requirements-completed: [WHALE-01, WHALE-02, WHALE-03, WHALE-04, WHALE-05]

duration: 3min
completed: 2026-03-03
---

# Phase 4 Plan 02: Whale Scoring Engine Summary

**FIFO P&L computation, three-mode percentile scoring (consistent/highroller/frequent), and PostgreSQL upsert for whale identification — all tested with 20 unit + 3 integration tests**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-03T02:53:14Z
- **Completed:** 2026-03-03T02:55:34Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 5

## Accomplishments
- Whale scoring engine implemented with FIFO P&L matching across buy/sell trades and market resolution outcomes
- Three scoring modes (consistent, highroller, frequent) using rank-based percentile weighting with no external dependencies
- Six new whale_* config fields added to Settings with pydantic-settings Field() defaults
- Full test coverage: 20 unit tests (TestComputePnl, TestComputeWalletStats, TestIsTracked, TestPercentileRanks) + 3 integration tests with mocked upsert path

## Task Commits

Each task was committed atomically:

1. **Task 1: Config fields + scoring engine (TDD RED → GREEN)** - `c13bc69` (feat)

## Files Created/Modified
- `arbiter/scoring/__init__.py` - Empty package init
- `arbiter/scoring/whales.py` - Full scoring engine: compute_pnl_for_market, pnl_trend_slope, percentile_ranks, _compute_wallet_stats, _apply_scores, _apply_is_tracked, upsert_wallet_scores, score_all_wallets
- `arbiter/config.py` - Six new whale_* config fields (whale_min_trades, whale_min_win_rate, whale_min_volume, whale_score_mode, whale_score_days, whale_score_interval_seconds)
- `tests/unit/test_scoring.py` - 17 unit tests across 4 test classes
- `tests/integration/test_scoring_integration.py` - 3 integration tests using aiosqlite with mocked upsert

## Decisions Made
- FIFO P&L matching via collections.deque — conventional, side-agnostic, testable without SQL CTEs
- pg_insert mocked in integration tests — pg_insert is PostgreSQL-only dialect, aiosqlite integration tests test the logic layer independently
- percentile_ranks uses rank/n normalization on sorted unique values — handles tied values, single-value guard returns 0.5
- whale_score_interval_seconds retained as config field (per WHALE-05) but is informational — scoring runs inside ingestion_loop per CONTEXT.md lock

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Scoring engine complete and tested; ready for Plan 04-03 (CLI whales subcommand)
- ingestion/trades.py will need a call to score_all_wallets() at end of run_ingestion_cycle() in a future plan
- upsert_wallet_scores() requires live PostgreSQL — will function correctly when DB is provisioned

## Self-Check: PASSED

Files verified:
- FOUND: arbiter/scoring/__init__.py
- FOUND: arbiter/scoring/whales.py
- FOUND: tests/unit/test_scoring.py
- FOUND: tests/integration/test_scoring_integration.py

Commit verified:
- FOUND: c13bc69 feat(04-02): implement whale scoring engine with FIFO P&L and percentile ranking

---
*Phase: 04-whale-identification*
*Completed: 2026-03-03*
