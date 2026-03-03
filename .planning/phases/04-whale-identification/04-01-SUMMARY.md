---
phase: 04-whale-identification
plan: "01"
subsystem: database
tags: [alembic, sqlalchemy, postgres, migrations, wallets]

requires:
  - phase: 03-trade-history
    provides: trades table with outcome column (migration 003, revision a3f8b2c91d45)

provides:
  - Alembic migration 004 adding win_volume, total_pnl, pnl_trend to wallets table
  - Wallet ORM model updated with three new Optional[float] fields

affects:
  - 04-02 (whale scoring engine — reads and writes these columns)

tech-stack:
  added: []
  patterns:
    - "Manual Alembic migration authoring (no autogenerate) — consistent project convention"
    - "All new scoring columns nullable Float — NULL until scoring engine runs"

key-files:
  created:
    - alembic/versions/004_whale_scoring_columns.py
  modified:
    - arbiter/db/models.py

key-decisions:
  - "win_volume, total_pnl, pnl_trend all nullable Float — existing wallet rows have no scored values; NULL is correct until scoring engine runs"
  - "Migration revision 004_whale_scoring_columns manually authored — project convention avoids autogenerate postgresql_where issues"

patterns-established:
  - "New scoring dimension columns added as nullable Float with NULL semantics for unscored rows"

requirements-completed: [WHALE-01, WHALE-04]

duration: 1min
completed: 2026-03-03
---

# Phase 4 Plan 01: Whale Schema Migration Summary

**Alembic migration 004 adding win_volume, total_pnl, pnl_trend as nullable Float columns to wallets, with Wallet ORM model updated to match**

## Performance

- **Duration:** ~1 min
- **Started:** 2026-03-03T02:50:58Z
- **Completed:** 2026-03-03T02:51:38Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created migration 004_whale_scoring_columns chaining correctly from down_revision a3f8b2c91d45
- Added win_volume, total_pnl, pnl_trend as nullable Float columns in both upgrade/downgrade paths
- Updated Wallet ORM model with three new Optional[float] mapped_column fields after is_tracked
- All 36 existing tests pass with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration 004** - `b5b0e5a` (feat)
2. **Task 2: Update Wallet ORM model** - `0508b18` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `alembic/versions/004_whale_scoring_columns.py` - Migration adding win_volume, total_pnl, pnl_trend to wallets
- `arbiter/db/models.py` - Wallet class updated with three new Optional[float] column fields

## Decisions Made
- All three columns are nullable Float — rows ingested before scoring runs will have NULL values, which the scoring engine treats as unscored

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Migration 004 is in place; `alembic upgrade head` (when DB running) applies cleanly after 003
- Wallet ORM model is ready for the scoring engine (Plan 02) to write win_volume, total_pnl, pnl_trend
- No blockers for Plan 02 execution

---
*Phase: 04-whale-identification*
*Completed: 2026-03-03*
