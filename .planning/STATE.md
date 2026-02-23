# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-22)

**Core value:** Surface profitable trading signals on Polymarket with enough accuracy to be worth acting on.
**Current focus:** Phase 1 - Foundation

## Current Position

Phase: 1 of 5 (Foundation)
Plan: 3 of 4 in current phase
Status: In Progress
Last activity: 2026-02-23 — Completed 01-03-PLAN.md: PolymarketClient hardening (pagination, retry, parse fixes)

Progress: [███░░░░░░░] 30%

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: ~5 min
- Total execution time: ~10 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| Phase 01 | 3 of 4 | ~10 min | ~5 min |

**Recent Trend:**
- Last 5 plans: 01-01 (2 min), 01-03 (8 min)
- Trend: On track

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: Schema design before detectors — dedup partial index, resolution enum, and price_at_signal must exist in migration 001 before any signal code is written
- [Roadmap]: Longshot bias may not produce edge on Polymarket (SSRN 2025); resolution tracking is the validation mechanism, not an optional reporting add-on
- [Roadmap]: No APScheduler — asyncio.sleep loops are the existing pattern and sufficient
- [Roadmap]: No pgvector, sentence-transformers, or Anthropic SDK in this milestone — Kalshi matching deferred
- [01-01]: Use Field(description=...) not docstrings — pydantic only surfaces descriptions from Field(), not inline docstrings
- [01-01]: sqlalchemy/asyncpg/alembic/tenacity were already in pyproject.toml with asyncio extras — only python-dotenv was added
- [01-02]: greenlet added as explicit dep — required by SQLAlchemy asyncio on Python 3.14 (not bundled)
- [01-02]: Initial migration written manually (not autogenerate) — autogenerate does not reliably emit postgresql_where on partial indexes
- [01-02]: alembic env.py reads DATABASE_URL from os.environ — callers must export before running migrations
- [01-03]: Retry placed on _fetch_page (per-page) not on fetch_all_active_markets — individual page failures retry, accumulated pages kept
- [01-03]: tenacity added as runtime dependency (not dev) — retry is production behavior required in deployed process
- [01-03]: list_markets() kept for Phase 1 backward compat, delegates to _fetch_page with active filters; will be removed in Phase 2

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 2]: CLOB API auth scope — confirm existing API key covers price polling before Phase 2 begins
- [Phase 3]: Signal threshold calibration (75-95% longshot, 72h/80-97% time decay) are starting hypotheses, not validated parameters; plan to adjust after 30+ resolutions
- [01-02]: PostgreSQL not installed locally — alembic upgrade head cannot run until DB is provisioned; run docker compose up -d postgres then alembic upgrade head before Phase 2

## Session Continuity

Last session: 2026-02-23
Stopped at: Completed 01-03-PLAN.md — PolymarketClient hardening (28,994 markets fetched live)
Resume file: None
