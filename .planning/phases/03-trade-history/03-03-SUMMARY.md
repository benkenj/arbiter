---
phase: 03-trade-history
plan: "03"
subsystem: ingestion
tags: [polymarket, clob, asyncio, sqlalchemy, trade-ingestion, watermark]

# Dependency graph
requires:
  - phase: 03-01
    provides: PolymarketClient.get_trades_for_market() with watermark pagination
  - phase: 03-02
    provides: outcome column on trades table

provides:
  - arbiter/ingestion/__init__.py — package marker
  - arbiter/ingestion/trades.py — ingest_market(), run_ingestion_cycle(), ingestion_loop()
  - main.py wired with ingestion_loop in asyncio.gather alongside discovery_loop

affects:
  - 04-whale-scoring
  - 05-position-monitor

# Tech tracking
tech-stack:
  added: []
  patterns:
    - session-per-market — fresh AsyncSession opened per market to avoid holding DB connections idle during async HTTP calls
    - append-only insert — sa_insert(Trade).values() without ON CONFLICT; watermark prevents re-fetching old trades
    - failure-isolated loop — per-market try/except, failures counted and logged, other markets continue unaffected
    - asyncio.gather concurrency — ingestion_loop and discovery_loop run as concurrent coroutines sharing one PolymarketClient

key-files:
  created:
    - arbiter/ingestion/__init__.py
    - arbiter/ingestion/trades.py
  modified:
    - arbiter/main.py

key-decisions:
  - "Append-only sa_insert(Trade) — no ON CONFLICT; watermark logic in get_trades_for_market() guarantees no duplicate timestamps are returned"
  - "Session-per-market pattern — avoids holding a DB connection idle during N HTTP round-trips; freshly re-fetches Market row inside each session for clean ORM tracking"
  - "markets[:ingestion_batch_size] slice applied before the loop — rate-limit guard, caps Data API requests per cycle regardless of active market count"
  - "Markets with condition_id IS NULL excluded at query level via Market.condition_id.is_not(None) — no NULL guard needed inside ingest_market()"

patterns-established:
  - "Failure isolation pattern: each market wrapped in its own try/except; failures increment counter, error logged with external_id + condition_id prefix, loop continues"
  - "Heartbeat log: every ingestion cycle emits markets processed, trades inserted, failure count, and elapsed time"
  - "Watermark update: market.last_ingested_at set to max(trade.timestamp) of returned batch, committed atomically with trade inserts"

requirements-completed: [HIST-01, HIST-02, HIST-03]

# Metrics
duration: 2min
completed: 2026-03-02
---

# Phase 3 Plan 03: Trade Ingestion Summary

**Incremental per-market trade ingestion loop using CLOB watermark pagination, session-per-market DB isolation, and per-market failure containment wired into asyncio.gather alongside discovery**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-02T06:37:05Z
- **Completed:** 2026-03-02T06:38:22Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created arbiter/ingestion/trades.py with ingest_market(), run_ingestion_cycle(), and ingestion_loop()
- Per-market failure isolation: each market in its own try/except; one market crashing does not stop others
- Watermark update (last_ingested_at) committed atomically with trade inserts to prevent gaps or duplicates on restart
- Wired ingestion_loop into main.py asyncio.gather alongside discovery_loop — both loops run concurrently sharing one PolymarketClient

## Task Commits

Each task was committed atomically:

1. **Task 1: Create arbiter/ingestion/__init__.py and arbiter/ingestion/trades.py** - `3e2a753` (feat)
2. **Task 2: Wire ingestion_loop into main.py** - `f4d7b0c` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `arbiter/ingestion/__init__.py` - Empty package marker
- `arbiter/ingestion/trades.py` - Core ingestion: ingest_market(), run_ingestion_cycle(), ingestion_loop(), _trade_to_db_row(), _bulk_insert_trades()
- `arbiter/main.py` - Added ingestion_loop import and asyncio.gather entry; updated startup log message

## Decisions Made
- Append-only insert (no ON CONFLICT) — correct because get_trades_for_market() watermark filtering ensures only trades newer than last_ingested_at are returned; re-inserting the same trade would violate correctness
- Session-per-market re-fetch — market row is re-fetched via session.get() inside each fresh session rather than reusing the market object from the initial query; avoids SQLAlchemy DetachedInstanceError when modifying last_ingested_at
- ingestion_batch_size cap applied before the loop with a slice — simple and avoids per-iteration counter logic

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- Trade ingestion is fully operational; the trades table will populate incrementally on each ingestion cycle
- Phase 4 (Whale Scoring) can query the trades table using wallet_address, market_id, side, size, and outcome to compute win rates and volumes
- outcome column is nullable — Phase 4 scoring must treat NULL as unresolved (no completed trade outcome yet)

## Self-Check: PASSED

- arbiter/ingestion/__init__.py: FOUND
- arbiter/ingestion/trades.py: FOUND
- 03-03-SUMMARY.md: FOUND
- commit 3e2a753: FOUND
- commit f4d7b0c: FOUND

---
*Phase: 03-trade-history*
*Completed: 2026-03-02*
