---
phase: 01-foundation
plan: 02
subsystem: database
tags: [sqlalchemy, alembic, asyncpg, postgresql, orm, migrations]

# Dependency graph
requires: []
provides:
  - SQLAlchemy 2.0 ORM models for Market, Signal, PriceSnapshot
  - Async session factory (make_engine, make_session_factory)
  - Alembic initial migration with partial unique index for signal deduplication
  - PostgreSQL ENUM signal_status with 5 states
affects: [02-polymarket-client, 03-signal-detection, 04-resolution-tracking]

# Tech tracking
tech-stack:
  added: [sqlalchemy[asyncio]>=2.0, asyncpg, alembic, greenlet]
  patterns:
    - "SQLAlchemy 2.0 Mapped/mapped_column style throughout (no Column())"
    - "No module-level engine or session — make_engine/make_session_factory take explicit params"
    - "expire_on_commit=False on session factory (prevents MissingGreenlet errors in async)"
    - "DATABASE_URL injected from environment in alembic/env.py (no hardcoded URL)"

key-files:
  created:
    - arbiter/db/__init__.py
    - arbiter/db/models.py
    - arbiter/db/session.py
    - alembic.ini
    - alembic/env.py
    - alembic/versions/704f539fec49_initial_schema.py
  modified:
    - pyproject.toml
    - poetry.lock

key-decisions:
  - "greenlet added as explicit dep — required by SQLAlchemy asyncio on Python 3.14 (no pre-built greenlet wheel bundled)"
  - "Migration written manually (not autogenerate) to guarantee correct partial index SQL with postgresql_where clause"
  - "signal_status ENUM created before signals table in upgrade(), dropped after signals table in downgrade()"

patterns-established:
  - "Alembic env.py reads DATABASE_URL from os.environ — callers must export this before running migrations"
  - "Partial index postgresql_where uses string literal in migration (not text() object)"

requirements-completed: [INFRA-03]

# Metrics
duration: ~15min
completed: 2026-02-22
---

# Phase 1 Plan 02: Database Schema Summary

**SQLAlchemy 2.0 ORM models and Alembic async migration with partial unique index for one-active-signal-per-market-per-strategy deduplication**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-02-23T05:25:00Z
- **Completed:** 2026-02-23T05:40:00Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Three ORM models (Market, Signal, PriceSnapshot) using SQLAlchemy 2.0 Mapped/mapped_column syntax — no Column() calls
- Signal model includes all Phase 3 required columns upfront: signal_price, hours_to_expiry, liquidity_at_signal, status enum, resolution_outcome, resolved_at
- Partial unique index ix_signals_market_strategy_active prevents two active signals for the same market+strategy combination
- Alembic initialized with async template; env.py reads DATABASE_URL from environment
- Initial migration written manually to control the exact postgresql_where clause on the partial index

## Task Commits

Each task was committed atomically:

1. **Task 1: SQLAlchemy ORM models and async session factory** - `185a56f` (feat)
2. **Task 2: Alembic async setup and initial migration** - `69244b2` (feat)

**Plan metadata:** (see final docs commit)

## Files Created/Modified
- `arbiter/db/__init__.py` - Empty package init
- `arbiter/db/models.py` - Market, Signal, PriceSnapshot ORM models with Base
- `arbiter/db/session.py` - make_engine() and make_session_factory() factory functions
- `alembic.ini` - Alembic config, script_location = alembic
- `alembic/env.py` - Async env with DATABASE_URL from os.environ, target_metadata = Base.metadata
- `alembic/versions/704f539fec49_initial_schema.py` - Full upgrade/downgrade for all 3 tables
- `pyproject.toml` - Added sqlalchemy[asyncio], asyncpg, alembic, greenlet
- `poetry.lock` - Updated lockfile

## Decisions Made
- greenlet added as explicit dependency: SQLAlchemy asyncio mode requires it and Python 3.14 does not bundle it
- Migration written manually rather than via --autogenerate: autogenerate does not reliably emit the postgresql_where clause on partial indexes
- signal_status ENUM created with raw op.execute() before the table, not via sa.Enum(create_type=True), to ensure correct ordering and avoid conflicts

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added greenlet dependency**
- **Found during:** Task 2 (testing connection path)
- **Issue:** SQLAlchemy asyncio on Python 3.14 raises ValueError("the greenlet library is required") — no pre-built wheel is bundled at this Python version
- **Fix:** `poetry add greenlet`
- **Files modified:** pyproject.toml, poetry.lock
- **Verification:** Import path proceeds past the greenlet check (fails at DB connection as expected)
- **Committed in:** `69244b2` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking dependency)
**Impact on plan:** Necessary for runtime correctness. No scope creep.

## Issues Encountered

**PostgreSQL not installed locally** — no Docker, no Homebrew postgres, no system psql on this machine. The `alembic upgrade head` live verification could not be run. All code is syntactically correct and verified at the import/parse level:
- All three models import cleanly
- Migration file loads without errors (revision, upgrade, downgrade functions confirmed present)
- alembic env.py processes through to the DB connection attempt (fails at socket with ECONNREFUSED, not before)

**Action required before Phase 2:** Provision a PostgreSQL instance (Docker recommended) and run:
```bash
export DATABASE_URL=postgresql+asyncpg://arbiter:arbiter@localhost/arbiter
alembic upgrade head
```

## User Setup Required

PostgreSQL must be provisioned before migrations can run. Suggested docker-compose.yml for local development:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: arbiter
      POSTGRES_PASSWORD: arbiter
      POSTGRES_DB: arbiter
    ports:
      - "5432:5432"
```

Then:
```bash
docker compose up -d postgres
export DATABASE_URL=postgresql+asyncpg://arbiter:arbiter@localhost/arbiter
alembic upgrade head
```

## Next Phase Readiness
- ORM models complete, ready for Phase 2 API client integration
- Session factory pattern established — main.py will call make_engine(settings.database_url) and make_session_factory(engine)
- Blocker: live migration must be run before any code that writes to the database can be tested

---
*Phase: 01-foundation*
*Completed: 2026-02-22*
