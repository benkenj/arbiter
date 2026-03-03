---
phase: 04-whale-identification
plan: "03"
subsystem: cli, ingestion, scoring
tags: [argparse, sqlalchemy, asyncpg, whale-scoring, tdd]

# Dependency graph
requires:
  - phase: 04-02
    provides: score_all_wallets(), _apply_scores(), SCORE_WEIGHTS — scoring engine this plan wires in
provides:
  - arbiter whales CLI subcommand with --all, --mode, --days flags
  - score_all_wallets called automatically after every run_ingestion_cycle
  - _show_whale_table: ranked table of tracked wallets sorted by score desc
  - _show_wallet_detail: full wallet stats + last 10 traded markets
affects: [05-position-monitoring, 06-alerts]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD: test class written first (RED) then implementation (GREEN)"
    - "Scoring isolated from ingestion failure — try/except wraps score_all_wallets"
    - "display_whales uses getattr(args, 'command', None) for backward-compat subparser dispatch"
    - "CLI address abbreviation: addr[:8] + '...' + addr[-6:]"

key-files:
  created:
    - tests/unit/test_cli_whales.py
  modified:
    - arbiter/ingestion/trades.py
    - arbiter/main.py
    - tests/unit/test_ingestion.py

key-decisions:
  - "score_all_wallets called in fresh session after market loop in run_ingestion_cycle; scoring errors logged but do not fail ingestion"
  - "getattr(args, 'command', None) used in main_sync() — bare arbiter and arbiter --check work without change"
  - "--mode and --days recompute display rank in memory via _apply_scores; DB is never written during CLI display"
  - "Address abbreviated as first 8 + '...' + last 6 chars for table readability"

patterns-established:
  - "TDD: write test class (RED) → implement (GREEN) → commit each phase"
  - "CLI subparser added via add_subparsers(dest='command'); backward compat via getattr"
  - "Scoring isolation: wrapped in try/except so ingestion continues on scoring failure"

requirements-completed: [WHALE-05, CLI-01, CLI-02, CLI-03]

# Metrics
duration: 3min
completed: 2026-03-03
---

# Phase 4 Plan 3: Wire Scoring into Ingestion + Whale CLI Summary

**score_all_wallets wired into every ingestion cycle; arbiter whales CLI subcommand displays ranked whale table with --all/--mode/--days flags**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-03T02:57:54Z
- **Completed:** 2026-03-03T03:01:03Z
- **Tasks:** 2
- **Files modified:** 3 (trades.py, main.py, test_ingestion.py) + 1 created (test_cli_whales.py)

## Accomplishments

- Wired `score_all_wallets` into `run_ingestion_cycle` — scoring now runs automatically after every cycle, in an isolated fresh session so scoring errors can't abort ingestion
- Added `arbiter whales` CLI subcommand with `address`, `--all`, `--mode`, `--days` flags via argparse subparsers
- Implemented `display_whales`, `_show_whale_table`, and `_show_wallet_detail` for ranked whale display and per-wallet detail view
- Full test suite: 71 tests passing (14 new CLI tests, 1 new ingestion test)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire scoring into ingestion loop + test** - `7d28d25` (feat)
2. **Task 2: CLI subcommand arbiter whales + test** - `6f6a06a` (feat)

**Plan metadata:** (docs commit below)

_Note: TDD tasks had implicit RED/GREEN cycle — test written first, then implementation_

## Files Created/Modified

- `arbiter/ingestion/trades.py` - Imports score_all_wallets; calls it after market loop in run_ingestion_cycle with try/except isolation
- `arbiter/main.py` - build_parser() adds whales subparser; display_whales/\_show_whale_table/\_show_wallet_detail functions; main_sync() dispatches on command == "whales"
- `tests/unit/test_ingestion.py` - Added TestIngestionCallsScoring class verifying score_all_wallets is called once per cycle
- `tests/unit/test_cli_whales.py` - Created: TestArgparserWhalesSubcommand, TestDisplayWhales, TestDisplayWhalesAll, TestDisplayWalletDetail (14 tests)

## Decisions Made

- `score_all_wallets` wrapped in try/except in `run_ingestion_cycle` — scoring failure must not abort ingestion cycle; both concerns are independent
- `getattr(args, 'command', None)` used in `main_sync()` — argparse subparsers are optional by default in Python 3.9+; bare `arbiter` must still run the service loop
- `--mode` and `--days` recompute display rank in memory via `_apply_scores`; they never write back to the wallets table
- Address abbreviated as `addr[:8] + "..." + addr[-6:]` — keeps table readable at standard terminal widths

## Deviations from Plan

**1. [Rule 1 - Bug] Test assertion string mismatch for abbreviated addresses**

- **Found during:** Task 2 (TestDisplayWhalesAll)
- **Issue:** Test checked for `"0xTRACKED"` (9 chars) but `_abbrev_address` uses first 8 chars, giving `"0xTRACKE"` for address `"0xTRACKEDAABBCCDD"`
- **Fix:** Updated test assertions to use the correct first-8-chars prefix and check both prefix and suffix independently
- **Files modified:** tests/unit/test_cli_whales.py
- **Verification:** All 14 CLI tests pass after fix
- **Committed in:** `6f6a06a` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - test assertion bug)
**Impact on plan:** Caught during initial test run; no functional code change. Tests now correctly validate the abbreviation behavior.

## Issues Encountered

None beyond the test assertion fix documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 4 (Whale Identification) complete: discovery, ingestion, scoring, and CLI all wired
- Phase 5 (Position Monitoring) can now query tracked wallets from DB using `is_tracked=True` filter
- `arbiter whales` is the user-facing verification tool for the entire Phase 4 feature set

---
*Phase: 04-whale-identification*
*Completed: 2026-03-03*
