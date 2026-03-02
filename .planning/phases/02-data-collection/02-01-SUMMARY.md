---
phase: 02-data-collection
plan: 01
subsystem: database
tags: [postgres, sqlalchemy, alembic, migration, orm]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: Initial schema (markets, signals, price_snapshots) at migration 001
provides:
  - Migration 002 (1c5960c71bfe) that drops signal-detection tables and creates whale-tracking tables
  - ORM models for Trade, Wallet, Position; Signal and PriceSnapshot removed
  - markets table extended with condition_id, last_ingested_at, created_at for Phase 3 compatibility
affects:
  - 02-02 (trade ingestion — imports Trade, uses last_ingested_at, condition_id)
  - 02-03 (whale scoring — imports Wallet)
  - 02-04 (position monitoring — imports Position)
  - 02-05 (discovery loop — upserts to markets with created_at)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Manual Alembic migration authoring (autogenerate skipped — unreliable for postgresql_where partial indexes and enum types)
    - downgrade() fully reverses all changes including PostgreSQL enum recreation

key-files:
  created:
    - alembic/versions/1c5960c71bfe_whale_schema.py
  modified:
    - arbiter/db/models.py

key-decisions:
  - "Migration revision ID 1c5960c71bfe, down_revision 704f539fec49 — explicitly chained to initial_schema"
  - "DROP TYPE IF EXISTS signal_status after table drop — Alembic does not auto-drop PostgreSQL enums"
  - "condition_id, last_ingested_at, created_at all nullable — backward-compatible with any existing markets rows"
  - "DB-level verification (alembic upgrade head, psql \\dt) deferred until Docker/postgres provisioned — noted in pre-existing STATE.md blocker"

patterns-established:
  - "Alembic migration structure: drop tables in reverse dependency order, add columns, create new tables in dependency order"
  - "ORM models: only import what is used — Enum and text removed when no longer needed"

requirements-completed:
  - INFRA-04

# Metrics
duration: 3min
completed: 2026-03-01
---

# Phase 2 Plan 01: Whale Schema Migration Summary

**Alembic migration 002 drops signal-detection tables (signals, price_snapshots, signal_status enum) and creates whale-tracking tables (trades, wallets, positions), extending markets with three Phase 3 columns**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-02T00:08:37Z
- **Completed:** 2026-03-02T00:10:48Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Migration 002 (1c5960c71bfe) chains from 704f539fec49, drops signals/price_snapshots, drops signal_status PostgreSQL enum, adds trades/wallets/positions tables with full downgrade reversal
- ORM models rewritten: Signal and PriceSnapshot removed, Trade/Wallet/Position added, Market extended with condition_id/last_ingested_at/created_at
- All four ORM models import cleanly; Base.metadata.tables is exactly ['markets', 'trades', 'wallets', 'positions']

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration 002** - `00fa761` (feat)
2. **Task 2: Update ORM models** - `d6dcb70` (feat)

## Files Created/Modified
- `alembic/versions/1c5960c71bfe_whale_schema.py` - Migration 002: drop old signal tables, add whale-tracking tables, extend markets
- `arbiter/db/models.py` - ORM models: Signal/PriceSnapshot removed, Trade/Wallet/Position added, Market extended

## Decisions Made
- Revision ID `1c5960c71bfe` generated with uuid4().hex[:12]; down_revision explicitly set to `704f539fec49`
- `DROP TYPE IF EXISTS signal_status` used (not `DROP TYPE`) — safe if enum was already cleaned up, mirrors the plan requirement
- condition_id, last_ingested_at, created_at added as nullable columns — no backfill needed, existing rows unaffected
- DB-level verification (alembic upgrade head, psql \dt) cannot run in this environment (Docker not installed); plan noted this pre-existing blocker in STATE.md

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written, with one environmental note:

The plan's verify step calls `docker compose up -d postgres` then `alembic upgrade head`. Docker is not installed in this environment (this is a pre-existing blocker logged in STATE.md under "[01-02]: PostgreSQL not installed locally"). The migration file has been syntax- and compile-verified; DB-level verification must be run manually once Docker/postgres is provisioned. All non-DB verification checks pass:
- `from arbiter.db.models import Base, Market, Trade, Wallet, Position` — OK
- `from arbiter.db.models import Signal` — raises ImportError (correct)
- `Base.metadata.tables` — ['markets', 'trades', 'wallets', 'positions'] (correct)

## Issues Encountered

Docker/postgres not available in execution environment. Pre-existing blocker from Phase 1. All Python-level verification passes.

## User Setup Required

To complete DB-level verification once Docker is available:
```bash
docker compose up -d postgres
export DATABASE_URL=postgresql+asyncpg://arbiter:arbiter@localhost:5432/arbiter
alembic upgrade head   # should end: Running upgrade 704f539fec49 -> 1c5960c71bfe, whale_schema
alembic downgrade -1   # should reverse cleanly
alembic upgrade head   # idempotent re-apply
psql $DATABASE_URL -c "\dt"       # markets, trades, wallets, positions
psql $DATABASE_URL -c "\d markets" # condition_id, last_ingested_at, created_at present
```

## Next Phase Readiness
- Trade, Wallet, Position ORM models are importable for 02-02 (trade ingestion), 02-03 (whale scoring), 02-04 (position monitoring)
- markets.condition_id and markets.last_ingested_at are ready for Phase 3 incremental ingestion
- DB schema migration is ready; requires Docker postgres to be provisioned before runtime use

---
*Phase: 02-data-collection*
*Completed: 2026-03-01*
