---
phase: 02-data-collection
verified: 2026-03-01T00:00:00Z
status: human_needed
score: 7/8 must-haves verified
re_verification: false
human_verification:
  - test: "Run `docker compose up -d postgres && alembic upgrade head` from migration 001 baseline"
    expected: "Output ends with 'Running upgrade 704f539fec49 -> 1c5960c71bfe, whale_schema'. Tables: markets, trades, wallets, positions. Columns condition_id, last_ingested_at, created_at present on markets."
    why_human: "Docker/postgres not available in code execution environment — pre-existing blocker documented in STATE.md. Migration file is syntactically correct and matches ORM models, but DB-level execution has not been verified."
  - test: "Run `alembic downgrade -1` after upgrading"
    expected: "Reverses cleanly — signals, price_snapshots, signal_status enum re-created. No error."
    why_human: "Same Docker/postgres dependency as above."
  - test: "Run `python -m arbiter` for 30 seconds against a live DB, then Ctrl-C"
    expected: "Log contains '[discovery] cycle complete in Xs — N upserted, N new, N filtered out' within the first 30s. Markets table populated. Ctrl-C exits cleanly with no hang."
    why_human: "Requires live DB + live Polymarket API access to verify end-to-end upsert behavior and filter correctness against real market data."
---

# Phase 2: Data Collection Verification Report

**Phase Goal:** Schema is migrated to the whale-tracking model, and a continuous market discovery loop upserts filtered Polymarket market metadata every 5 minutes, surviving transient failures without crashing.
**Verified:** 2026-03-01
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                                         | Status      | Evidence                                                                                      |
|----|---------------------------------------------------------------------------------------------------------------|-------------|-----------------------------------------------------------------------------------------------|
| 1  | `alembic upgrade head` drops signals/price_snapshots/signal_status and creates trades/wallets/positions       | ? UNCERTAIN | Migration file correct, DB-level execution deferred (no Docker in environment)                |
| 2  | `alembic downgrade -1` reverses the migration without error                                                   | ? UNCERTAIN | downgrade() re-creates signal_status enum + tables correctly; DB execution not verified       |
| 3  | ORM models: Trade, Wallet, Position importable; Signal and PriceSnapshot gone                                 | VERIFIED    | models.py has Trade/Wallet/Position; no Signal or PriceSnapshot classes or imports            |
| 4  | markets table gains condition_id, last_ingested_at, created_at                                                | VERIFIED    | Migration adds all 3 columns nullable; ORM Market model has all 3 mapped columns             |
| 5  | Service runs a discovery cycle immediately on start (sleep is after cycle, not before)                        | VERIFIED    | `asyncio.sleep` is line 157, after try/except block; first cycle runs immediately on entry   |
| 6  | Heartbeat log line emitted after each cycle with upserted/new/filtered counts                                 | VERIFIED    | `logger.info("[discovery] cycle complete in %.1fs — %d upserted, %d new, %d filtered out")` |
| 7  | Binary/volume/liquidity filters exclude non-qualifying markets; None volume/liquidity treated as 0            | VERIFIED    | `_is_binary` checks `["yes","no"]` exactly; `(m.volume or 0)` and `(m.liquidity or 0)` used |
| 8  | Transient API failures log and continue; 5 consecutive DB failures call sys.exit(1)                          | VERIFIED    | `OperationalError` counted separately; generic `Exception` logs and continues; sys.exit(1) at threshold |

**Score:** 6 verified / 2 uncertain (human needed) / 8 total truths

### Required Artifacts

| Artifact                                      | Expected                                          | Status      | Details                                                                                      |
|-----------------------------------------------|---------------------------------------------------|-------------|----------------------------------------------------------------------------------------------|
| `alembic/versions/1c5960c71bfe_whale_schema.py` | Migration 002: drop old tables, add whale tables  | VERIFIED    | 155-line migration; revision 1c5960c71bfe, down_revision 704f539fec49; upgrade/downgrade both substantive |
| `arbiter/db/models.py`                        | ORM models: Market, Trade, Wallet, Position; no Signal/PriceSnapshot | VERIFIED | 73 lines; 4 classes present; no Signal, PriceSnapshot, Enum, or text imports |
| `arbiter/config.py`                           | Market filter + discovery interval settings       | VERIFIED    | market_binary_only (True), market_min_volume (1000.0), market_min_liquidity (1000.0), discovery_interval_seconds (300) |
| `arbiter/discovery/loop.py`                   | discovery_loop(), run_discovery_cycle(), upsert_markets(), _is_binary() | VERIFIED | 157 lines; all functions present; ON CONFLICT upsert excludes created_at; OperationalError handling; sys.exit(1) |
| `arbiter/discovery/__init__.py`               | Empty package init                                | VERIFIED    | File exists (empty, as intended)                                                             |
| `arbiter/main.py`                             | Wires discovery_loop into asyncio.gather          | VERIFIED    | Imports discovery_loop; asyncio.gather(discovery_loop(settings, session_factory, client)); engine.dispose() in finally |

### Key Link Verification

| From                         | To                           | Via                                                   | Status   | Details                                                                          |
|------------------------------|------------------------------|-------------------------------------------------------|----------|----------------------------------------------------------------------------------|
| `arbiter/discovery/loop.py`  | `arbiter/db/models.py`       | `insert(Market)` with `on_conflict_do_update`         | WIRED    | Line 9: `from sqlalchemy.dialects.postgresql import insert`; line 78: `insert(Market).values(...)` |
| `arbiter/discovery/loop.py`  | `arbiter/config.py`          | `settings.market_binary_only / market_min_volume / market_min_liquidity` | WIRED | Lines 31, 34, 37 use all three filter settings; line 157 uses `settings.discovery_interval_seconds` |
| `arbiter/main.py`            | `arbiter/discovery/loop.py`  | `asyncio.gather(discovery_loop(...))`                 | WIRED    | Line 11: `from arbiter.discovery.loop import discovery_loop`; line 108: `await asyncio.gather(discovery_loop(...))` |
| `alembic/versions/1c5960c71bfe_whale_schema.py` | `arbiter/db/models.py` | Migration must match ORM column definitions | VERIFIED | All columns (wallet_address, market_id, is_tracked, condition_id, last_ingested_at, created_at) present in both |
| `arbiter/db/models.py` (external_id unique) | `alembic/versions/` | `external_id unique=True` for ON CONFLICT target | VERIFIED | ORM: `unique=True` on external_id; migration 001 has `UniqueConstraint("external_id")`; migration 002 preserves it |

### Requirements Coverage

| Requirement | Source Plan | Description                                                                                    | Status      | Evidence                                                                      |
|-------------|-------------|------------------------------------------------------------------------------------------------|-------------|-------------------------------------------------------------------------------|
| INFRA-04    | 02-01, 02-02 | Continuous market discovery loop (~5 min) that fetches and upserts filtered markets           | VERIFIED    | `discovery_loop` with `asyncio.sleep(settings.discovery_interval_seconds)`; default 300s |
| INFRA-06    | 02-02        | Discovery loop recovers from transient errors without crashing                                 | VERIFIED    | `except Exception` continues; `OperationalError` with consecutive counter; `sys.exit(1)` only after 5 consecutive DB failures |
| INFRA-07    | 02-02        | Discovery loop emits a heartbeat log line each cycle so silence is detectable                 | VERIFIED    | `logger.info("[discovery] cycle complete in %.1fs — %d upserted, %d new, %d filtered out")` |
| FILTER-01   | 02-02        | Binary-only filter (`MARKET_BINARY_ONLY`, default true) — only yes/no markets                 | VERIFIED    | `_is_binary`: `[o.lower() for o in outcomes] == ["yes", "no"]`; applied in `_apply_filters` |
| FILTER-02   | 02-02        | Minimum volume filter (`MARKET_MIN_VOLUME` in USDC)                                           | VERIFIED    | `(m.volume or 0) < settings.market_min_volume` — None treated as 0           |
| FILTER-03   | 02-02        | Minimum liquidity filter (`MARKET_MIN_LIQUIDITY` in USDC)                                     | VERIFIED    | `(m.liquidity or 0) < settings.market_min_liquidity` — None treated as 0     |

All 6 requirements claimed by the phase plans are accounted for. No orphaned requirements found — REQUIREMENTS.md traceability table maps all 6 to Phase 2.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | -    | -       | -        | No TODO/FIXME/placeholder comments found; no empty implementations; no stubs |

### Docs Inconsistency (Non-Blocking)

ROADMAP.md line 54 shows `[ ] 02-02-PLAN.md — Market filter config fields + discovery loop + main.py wiring` as unchecked, despite the work being complete with commits `2dce797`, `13bab09`, `1e338d6`. This is a docs-only inconsistency that does not affect runtime behavior.

### Human Verification Required

#### 1. Alembic Upgrade: Migration 002 Applies Cleanly

**Test:** With Docker postgres running, from a DB at migration 001 baseline:
```bash
docker compose up -d postgres
alembic upgrade head
```
**Expected:** Output ends with "Running upgrade 704f539fec49 -> 1c5960c71bfe, whale_schema". `psql $DATABASE_URL -c "\dt"` shows markets, trades, wallets, positions (no signals, price_snapshots). `psql $DATABASE_URL -c "\d markets"` shows condition_id, last_ingested_at, created_at as nullable columns.

**Why human:** Docker/postgres not available in code execution environment. Pre-existing blocker documented in STATE.md under "[01-02]: PostgreSQL not installed locally". All Python-level verification passes; DB-level execution is the only remaining gap.

#### 2. Alembic Downgrade: Migration 002 Reverses Cleanly

**Test:** After upgrading, run:
```bash
alembic downgrade -1
```
**Expected:** Reverses without error. signals and price_snapshots tables re-created. signal_status enum re-created. markets loses condition_id, last_ingested_at, created_at.

**Why human:** Same Docker/postgres dependency.

#### 3. End-to-End Discovery Cycle

**Test:** With DB at migration head and valid .env, run `python -m arbiter` for 30+ seconds then Ctrl-C.

**Expected:**
- Config summary logs MARKET_BINARY_ONLY, MARKET_MIN_VOLUME, MARKET_MIN_LIQUIDITY, DISCOVERY_INTERVAL_SECONDS
- "Service ready. Starting discovery loop." appears
- Within 30s: `[discovery] cycle complete in Xs — N upserted, N new, N filtered out` with N > 0
- `SELECT COUNT(*) FROM markets` returns > 0 rows
- Ctrl-C exits without hang (asyncio.CancelledError propagates, not caught by `except Exception`)

**Why human:** Requires live DB and live Polymarket API. Tests filter behavior against real market data and confirms the upsert pipeline reaches the DB.

### Gaps Summary

No code gaps. All artifacts exist, are substantive, and are wired. The only items requiring human verification are DB-level migration execution and the live end-to-end cycle test — both blocked by the pre-existing Docker/postgres absence in the execution environment, not by any coding error or omission.

The `bccdc84` commit (labeled "fix(02): revise discovery loop to exit on permanent DB failure") is a documentation-only commit that revised the PLAN.md before code was written. The actual sys.exit(1) behavior was implemented as planned in commit `13bab09`.

---

_Verified: 2026-03-01_
_Verifier: Claude (gsd-verifier)_
