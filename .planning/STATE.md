# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-22)

**Core value:** Alert when high-performing Polymarket traders open new positions, enabling copy trading decisions.
**Current focus:** Phase 1 - Foundation (plan 04 remaining), then Phase 2

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

- [2026-02-25 Pivot]: Project pivoted from signal detection (longshot bias, time decay) to whale copy trading — monitor high-performing wallets on Polymarket and alert on new position opens
- [2026-02-25 Pivot]: Kalshi integration deferred indefinitely (no trading access); Polymarket-only for all phases
- [2026-02-25 Pivot]: Event-driven positioning deferred to much later; copy trading is the primary strategy
- [2026-02-25 Pivot]: Alert-driven architecture (no execution in v1), but designed so a TradeExecutor slots in without restructuring
- [2026-02-25 Pivot]: Whale scoring = win rate (correct/total resolved) + volume; configurable thresholds for classification
- [2026-02-25 Pivot]: Market filters (binary-only, min volume, min liquidity) are user-configurable via env vars
- [2026-02-25 Pivot]: signals table (created in Phase 1) will be dropped in Phase 2 migration; trades/wallets/positions tables added
- [Roadmap]: No APScheduler — asyncio.sleep loops are the existing pattern and sufficient
- [Roadmap]: No pgvector, sentence-transformers, or Anthropic SDK — no LLM needed for whale scoring
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
- [Phase 2]: signals table was created in Phase 1 migration 001; Phase 2 must include a migration to drop it and add trades/wallets/positions
- [Phase 3]: Polymarket CLOB trade history API — verify endpoint, pagination, and rate limits before Phase 3 planning
- [01-02]: PostgreSQL not installed locally — alembic upgrade head cannot run until DB is provisioned; run docker compose up -d postgres then alembic upgrade head before Phase 2

## Session Continuity

Last session: 2026-02-23
Stopped at: Completed 01-03-PLAN.md — PolymarketClient hardening (28,994 markets fetched live)
Resume file: None
