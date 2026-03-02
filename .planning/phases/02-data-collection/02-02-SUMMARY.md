---
phase: 02-data-collection
plan: 02
subsystem: infra
tags: [polymarket, asyncio, sqlalchemy, postgres, discovery, market-filter]

# Dependency graph
requires:
  - phase: 02-data-collection
    plan: 01
    provides: ORM models (Market, Trade, Wallet, Position) and markets table with created_at column
provides:
  - Market filter config fields (market_binary_only, market_min_volume, market_min_liquidity, discovery_interval_seconds)
  - discovery_loop(): async loop that immediately runs one cycle then sleeps, with DB failure exit
  - run_discovery_cycle(): fetches all active Polymarket markets, filters, upserts via ON CONFLICT
  - Heartbeat log line after each cycle with upserted/new/filtered counts
affects:
  - 02-03 (trade ingestion — main.py pattern to add trade ingestion loop alongside discovery_loop)
  - 02-04 (whale scoring — same pattern)
  - 02-05 (position monitoring — same pattern)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - discovery module pattern: loop + cycle separation (loop handles timing/errors, cycle handles business logic)
    - ON CONFLICT DO UPDATE excludes created_at from SET clause — preserves original insert timestamp
    - Consecutive DB failure counter with sys.exit(1) threshold — lets process manager restart the service

key-files:
  created:
    - arbiter/discovery/__init__.py
    - arbiter/discovery/loop.py
  modified:
    - arbiter/config.py
    - .env.example
    - arbiter/main.py

key-decisions:
  - "poetry venv uses Python 3.14 (not 3.12) — arbiter-iy17SPxa-py3.14; all verification commands use VENV path"
  - "Sleep placed after cycle body (not before) — first cycle runs immediately on entry per plan spec"
  - "created_at excluded from ON CONFLICT SET clause — only INSERT sets it, UPDATE preserves original value"
  - "Separate engine instance in main() for service loop vs run_checks() — health check engine is short-lived, service engine is persistent"
  - "discovery_interval_seconds default=300 (5 min); used in asyncio.sleep at end of each cycle"

patterns-established:
  - "Module layout: arbiter/{concern}/__init__.py (empty) + loop.py with loop() + cycle() pattern"
  - "Config fields: Field(description=...) not docstrings — pydantic surfaces Field descriptions in validation errors"

requirements-completed:
  - INFRA-04
  - INFRA-06
  - INFRA-07
  - FILTER-01
  - FILTER-02
  - FILTER-03

# Metrics
duration: 3min
completed: 2026-03-02
---

# Phase 2 Plan 02: Discovery Loop Summary

**Asyncio discovery loop that fetches all active Polymarket markets every 5 minutes, applies binary/volume/liquidity filters, upserts to PostgreSQL via ON CONFLICT, and logs a heartbeat with upserted/new/filtered counts**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-02T00:14:02Z
- **Completed:** 2026-03-02T00:16:49Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- Market filter config fields (market_binary_only, market_min_volume, market_min_liquidity, discovery_interval_seconds) with correct defaults; old signal-detection threshold fields removed
- `arbiter/discovery/loop.py`: _is_binary(), _apply_filters(), upsert_markets() (ON CONFLICT, preserves created_at), run_discovery_cycle(), discovery_loop() with consecutive DB failure exit
- `arbiter/main.py` wired: asyncio.gather(discovery_loop(...)), separate engine/session_factory for service loop, engine.dispose() in finally

## Task Commits

Each task was committed atomically:

1. **Task 1: Add market filter + discovery interval fields to config** - `2dce797` (feat)
2. **Task 2: Implement discovery loop with filter, upsert, and heartbeat** - `13bab09` (feat)
3. **Task 3: Wire discovery loop into main.py** - `1e338d6` (feat)

## Files Created/Modified
- `arbiter/config.py` - Removed longshot_*/time_decay_* fields; added market_binary_only, market_min_volume, market_min_liquidity, discovery_interval_seconds; updated print_config_summary()
- `.env.example` - Removed old LONGSHOT_*/TIME_DECAY_* entries; added Market Discovery Filters section
- `arbiter/discovery/__init__.py` - Empty package file
- `arbiter/discovery/loop.py` - Full discovery module: filters, upsert, cycle, loop with error recovery
- `arbiter/main.py` - Wired discovery_loop via asyncio.gather; updated argparse description to "whale copy-trading alert service"

## Decisions Made
- Poetry venv is Python 3.14 (`arbiter-iy17SPxa-py3.14`) — all verification used the VENV path directly
- `created_at` excluded from ON CONFLICT SET — preserves original insert timestamp across upsert cycles
- Sleep after cycle body (not before) — ensures first cycle runs immediately on startup
- Separate persistent engine in main() vs short-lived engine in run_checks() — intentional, clean lifecycle management

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

`python` binary resolves to system Python 3.11 (pydantic v1, pre-`field_validator`). All Python verification used the poetry venv path directly (`/Users/benmiller/Library/Caches/pypoetry/virtualenvs/arbiter-iy17SPxa-py3.14/bin/python`). Not a blocker — project runs correctly via `poetry run` or the venv.

## User Setup Required

None — no external service configuration required beyond what was already documented. To run the full service end-to-end:
```bash
docker compose up -d postgres
export DATABASE_URL=postgresql+asyncpg://arbiter:arbiter@localhost:5432/arbiter
alembic upgrade head
python -m arbiter           # runs discovery loop; Ctrl-C to stop
python -m arbiter --check   # health check only
```

## Next Phase Readiness
- Discovery loop is complete and wired — service will fetch/filter/upsert markets on every cycle
- `asyncio.gather()` in main.py is ready to accept additional coroutines (trade ingestion, whale scoring, position monitoring) as each phase ships
- markets table is populated after first cycle, providing the market IDs needed by trade ingestion (Phase 3)

---
*Phase: 02-data-collection*
*Completed: 2026-03-02*
