# Phase 2: Data Collection - Research

**Researched:** 2026-02-25
**Domain:** Alembic schema migration, SQLAlchemy async upsert, asyncio polling loop, Polymarket Gamma API market filtering
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Binary-only filter is ON by default (`MARKET_BINARY_ONLY=true`) — only yes/no outcome markets
- Default minimum volume: 1,000 USDC (`MARKET_MIN_VOLUME=1000`)
- Default minimum liquidity: 1,000 USDC (`MARKET_MIN_LIQUIDITY=1000`) — matches volume for simplicity
- All three are env-var configurable; defaults represent a sensible floor that excludes dead markets
- API failures within a cycle: reuse the Phase 1 tenacity retry logic already on the Gamma client — no separate retry layer at the loop level
- After retries exhausted: log the error, skip this cycle, resume on the next tick — always keep running
- No escalation beyond logging — silence in logs (i.e. missing heartbeats) is the signal that something is wrong
- Fatal condition: if the DB connection is permanently lost, the service exits — let the process manager restart it
- Discovery runs immediately on start — first cycle begins as soon as the loop starts, not after the first interval
- Startup health check (`--check` flag from Phase 1): exits immediately on failure — fail fast, no retry-until-ready
- Migrations are manual — `alembic upgrade head` is a deliberate step run before starting the service; the service does not auto-migrate
- Heartbeat log line after each discovery cycle includes: cycle duration, markets upserted, new markets added, markets filtered out
  - e.g. `[discovery] cycle complete in 3.2s — 847 upserted, 12 new, 203 filtered out`
- Plain text logging for now — structured JSON is a future phase

### Claude's Discretion
- (None specified for Phase 2 — all key decisions are locked above)

### Deferred Ideas (OUT OF SCOPE)
- Price snapshot polling — not needed for whale copy trading; add back if a future phase requires current market prices
- Discord alert on consecutive discovery failures — log-only for now; could escalate in a later hardening phase
- Structured JSON logging — noted in v2 requirements (INFRA-V2-01)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFRA-04 | System runs a continuous market discovery loop (every ~5 minutes) that fetches active Polymarket markets matching configured filters and upserts them to the DB | asyncio.sleep loop pattern; SQLAlchemy postgresql.insert().on_conflict_do_update() for upsert |
| INFRA-06 | Discovery loop recovers from transient errors (API failures, DB errors) without crashing the process | try/except around cycle body; log and continue; tenacity already on _fetch_page for API layer |
| INFRA-07 | Discovery loop emits a heartbeat log line each cycle so silence is detectable | logging.info() with timing, counts; use time.monotonic() for duration |
| FILTER-01 | Discovery applies a configurable binary-only filter (`MARKET_BINARY_ONLY`, default true) — only yes/no outcome markets are tracked | Gamma API docs: each Market is binary by design; multi-outcome "markets" are actually multi-market Events; filter by `len(outcomes) == 2` client-side |
| FILTER-02 | Discovery applies a configurable minimum volume filter (`MARKET_MIN_VOLUME` in USDC, default 0) — markets below threshold are skipped | `volume` field already present in Market model from Phase 1; filter client-side |
| FILTER-03 | Discovery applies a configurable minimum liquidity filter (`MARKET_MIN_LIQUIDITY` in USDC, default 0) — markets below threshold are skipped | `liquidity` field (mapped from `liquidityCLOB`) already present in Market model; filter client-side |
</phase_requirements>

---

## Summary

Phase 2 has three distinct work areas: (1) a second Alembic migration that drops the old signal-detection schema and adds the whale-tracking tables, (2) new filter settings added to `config.py`, and (3) a discovery loop wired into `main.py` that runs every 5 minutes, filters markets, upserts them, and emits a heartbeat.

The existing codebase from Phase 1 provides strong foundations. `PolymarketClient.fetch_all_active_markets()` already fetches and paginates correctly with tenacity retry on `_fetch_page`. The SQLAlchemy async engine and `async_sessionmaker` are ready in `db/session.py`. `main.py` already has the startup structure — Phase 2 replaces the placeholder comment with `asyncio.gather(discovery_loop())`. The biggest new pattern is the PostgreSQL upsert via `sqlalchemy.dialects.postgresql.insert()` with `.on_conflict_do_update()`, which is the standard way to handle "insert or update" for the markets table.

The Gamma API docs confirm that individual Market objects are always binary (each market is a YES/NO question). However, Polymarket also surfaces "events" with multiple child markets (e.g., "which team wins?" with one market per team). These multi-outcome event markets appear as separate Market objects in the API, each with a `["TeamA", "TeamB"]` outcome pair rather than `["Yes", "No"]`. The binary filter should check `len(outcomes) == 2` OR check that outcomes match `["Yes", "No"]` (case-insensitive) depending on which semantics are desired. Checking for exactly 2 outcomes (the simpler check) catches standard binary markets but also passes through some multi-team 2-option markets. Checking for `["Yes", "No"]` is more precise.

**Primary recommendation:** Write the Phase 2 migration manually (not autogenerate) to drop `signals`/`price_snapshots` and create `trades`/`wallets`/`positions`. Build the discovery loop as an `async def discovery_loop()` function that owns its own session per cycle, wraps the cycle body in try/except, and sleeps for `DISCOVERY_INTERVAL_SECONDS` between ticks. Use `sqlalchemy.dialects.postgresql.insert().on_conflict_do_update()` for the upsert.

---

## Standard Stack

### Core (already in pyproject.toml — no new installs needed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | >=2.0 + asyncio extras | Async ORM + PostgreSQL upsert dialect | `sqlalchemy.dialects.postgresql.insert` provides ON CONFLICT DO UPDATE |
| asyncpg | ^0.31.0 | PostgreSQL async driver | Required for SQLAlchemy async; already installed |
| Alembic | ^1.18.4 | Schema migration | Write migration 002 to drop old tables, add new ones |
| tenacity | ^9.1.4 | Retry on `_fetch_page` | Already decorates Gamma API page fetches |
| httpx | ^0.27 | HTTP client for Gamma API | Already in PolymarketClient |
| pydantic-settings | ^2.0 | New filter env vars | Already used for all config |

No new dependencies required for Phase 2.

### New Config Fields (additions to `config.py`)
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `market_binary_only` | `bool` | `True` | `MARKET_BINARY_ONLY` |
| `market_min_volume` | `float` | `1000.0` | `MARKET_MIN_VOLUME` |
| `market_min_liquidity` | `float` | `1000.0` | `MARKET_MIN_LIQUIDITY` |
| `discovery_interval_seconds` | `int` | `300` | `DISCOVERY_INTERVAL_SECONDS` |

`discovery_interval_seconds` is Claude's discretion (not in CONTEXT.md) — 300s (5 min) matches the stated goal and is a sensible default.

---

## Architecture Patterns

### Recommended Phase 2 File Changes
```
arbiter/
├── config.py              # ADD: market filter fields + discovery interval
├── db/
│   └── models.py          # REPLACE: Signal/PriceSnapshot → Trade/Wallet/Position
├── clients/
│   └── polymarket.py      # MODIFY: add apply_filters() helper method
├── discovery/
│   └── loop.py            # NEW: discovery_loop() coroutine
└── main.py                # MODIFY: wire discovery_loop into asyncio.gather

alembic/versions/
└── XXXX_whale_schema.py   # NEW: migration 002
```

The `discovery/` module is Claude's discretion (not in CONTEXT.md). It could also live directly in `main.py`, but extracting to `arbiter/discovery/loop.py` keeps `main.py` from growing large across phases.

### Pattern 1: Alembic Migration to Drop Old + Add New Tables

**What:** Migration 002 drops `price_snapshots`, `signals`, and the `signal_status` enum, then creates `trades`, `wallets`, `positions` tables.

**Critical ordering:** Drop dependent tables before parent tables. Drop the `signal_status` PostgreSQL enum after dropping the table that uses it. Create new tables in FK dependency order.

**Example:**
```python
# alembic/versions/XXXX_whale_schema.py
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    # Drop old signal-detection tables (FK child before parent)
    op.drop_index("ix_price_snapshots_market_fetched", table_name="price_snapshots")
    op.drop_table("price_snapshots")

    op.drop_index("ix_signals_market_strategy_active", table_name="signals")
    op.drop_table("signals")

    # Drop the PostgreSQL enum type — Alembic does NOT do this automatically
    op.execute("DROP TYPE IF EXISTS signal_status")

    # Create whale-tracking tables
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wallet_address", sa.String(), nullable=False),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),   # "YES" | "NO"
        sa.Column("size", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trades_wallet", "trades", ["wallet_address"])
    op.create_index("ix_trades_market", "trades", ["market_id"])

    op.create_table(
        "wallets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("address", sa.String(), nullable=False, unique=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("total_volume", sa.Float(), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("last_scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_tracked", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_wallets_is_tracked", "wallets", ["is_tracked"])

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wallet_address", sa.String(), nullable=False),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("current_size", sa.Float(), nullable=False),
        sa.Column("avg_price", sa.Float(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_positions_wallet", "positions", ["wallet_address"])


def downgrade() -> None:
    op.drop_index("ix_positions_wallet", table_name="positions")
    op.drop_table("positions")

    op.drop_index("ix_wallets_is_tracked", table_name="wallets")
    op.drop_table("wallets")

    op.drop_index("ix_trades_market", table_name="trades")
    op.drop_index("ix_trades_wallet", table_name="trades")
    op.drop_table("trades")

    # Re-create old tables (simplified — full downgrade would be migration 001 restore)
    op.execute(
        "CREATE TYPE signal_status AS ENUM "
        "('active', 'resolved_correct', 'resolved_incorrect', 'expired', 'void')"
    )
    # ... (planner can stub this; downgrade to 001 is the practical rollback path)
```

### Pattern 2: SQLAlchemy PostgreSQL Upsert (INSERT ON CONFLICT DO UPDATE)

**What:** Use `sqlalchemy.dialects.postgresql.insert()` — NOT the ORM `session.add()` — for upsert. The `stmt.excluded` attribute references the proposed row's values in the SET clause.

**When to use:** Any time you need "insert if not exists, else update" semantics. The markets table uses `external_id` as the natural key.

**Example:**
```python
# Source: https://docs.sqlalchemy.org/en/20/dialects/postgresql.html
from sqlalchemy.dialects.postgresql import insert
from datetime import datetime, timezone

async def upsert_markets(session, market_rows: list[dict]) -> tuple[int, int]:
    """
    Upsert a list of market dicts. Returns (upserted_count, new_count).
    market_rows: list of dicts with keys matching Market table columns.
    """
    if not market_rows:
        return 0, 0

    from arbiter.db.models import Market

    stmt = insert(Market).values(market_rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["external_id"],   # the unique constraint column
        set_={
            "question": stmt.excluded.question,
            "description": stmt.excluded.description,
            "end_date": stmt.excluded.end_date,
            "resolved": stmt.excluded.resolved,
            "closed": stmt.excluded.closed,
            "yes_price": stmt.excluded.yes_price,
            "liquidity": stmt.excluded.liquidity,
            "volume": stmt.excluded.volume,
            "active": stmt.excluded.active,
            "fetched_at": stmt.excluded.fetched_at,
        },
    )
    await session.execute(stmt)
    await session.commit()
```

**Note on counting new vs updated:** `INSERT ON CONFLICT DO UPDATE` does not natively return which rows were inserted vs updated in PostgreSQL without using `RETURNING xmax`. The simplest approach for the heartbeat log is to query `COUNT(*)` before and after, or to track new rows by checking a `created_at` timestamp. Alternative: the heartbeat can report `upserted: N` without distinguishing new vs updated, which satisfies INFRA-07.

### Pattern 3: Discovery Loop with Error Recovery

**What:** An `async def discovery_loop()` that runs immediately on entry, performs one discovery cycle, sleeps, repeats. Wraps the cycle body in try/except to catch and log errors without crashing. Uses `time.monotonic()` for duration measurement.

**When to use:** This is the primary INFRA-04 + INFRA-06 + INFRA-07 implementation.

**Example:**
```python
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

async def discovery_loop(settings, session_factory, client) -> None:
    """Run market discovery every DISCOVERY_INTERVAL_SECONDS. Never exits on transient errors."""
    while True:
        cycle_start = time.monotonic()
        try:
            upserted, new_count, filtered = await run_discovery_cycle(
                settings, session_factory, client
            )
            duration = time.monotonic() - cycle_start
            logger.info(
                "[discovery] cycle complete in %.1fs — %d upserted, %d new, %d filtered out",
                duration, upserted, new_count, filtered,
            )
        except Exception as exc:
            duration = time.monotonic() - cycle_start
            logger.error(
                "[discovery] cycle failed after %.1fs: %s",
                duration, exc,
            )
        await asyncio.sleep(settings.discovery_interval_seconds)


async def run_discovery_cycle(settings, session_factory, client) -> tuple[int, int, int]:
    """Fetch all active markets, apply filters, upsert to DB."""
    all_markets = await client.fetch_all_active_markets()  # tenacity retry inside

    filtered_out = 0
    market_rows = []
    for m in all_markets:
        if settings.market_binary_only and not _is_binary(m):
            filtered_out += 1
            continue
        if settings.market_min_volume and (m.volume or 0) < settings.market_min_volume:
            filtered_out += 1
            continue
        if settings.market_min_liquidity and (m.liquidity or 0) < settings.market_min_liquidity:
            filtered_out += 1
            continue
        market_rows.append(_to_db_row(m))

    upserted = len(market_rows)
    async with session_factory() as session:
        new_count = await upsert_markets(session, market_rows)

    return upserted, new_count, filtered_out


def _is_binary(market) -> bool:
    """Return True if market has exactly Yes/No outcomes."""
    outcomes = [o.lower() for o in market.outcomes]
    return outcomes == ["yes", "no"]
```

### Pattern 4: Wiring the Loop into main.py

**What:** Replace the Phase 1 placeholder comment with `asyncio.gather(discovery_loop(...))`. Single loop for now; `asyncio.gather` allows adding more loops (trade ingestion, scoring) in future phases without restructuring.

**Example:**
```python
# In main.py async def main():
    await run_checks(settings)
    logging.info("Service ready. Starting discovery loop.")

    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    async with PolymarketClient() as client:
        await asyncio.gather(
            discovery_loop(settings, session_factory, client),
        )
```

### Anti-Patterns to Avoid

- **Using `session.merge()` for upsert:** `session.merge()` does a SELECT + INSERT/UPDATE, two round-trips. Use `postgresql.insert().on_conflict_do_update()` for single-statement upsert.
- **Creating a new session per market row:** Create one session per cycle, upsert all rows in one statement. Per-row sessions multiply DB round-trips by market count (~28k markets).
- **Catching `asyncio.CancelledError` in the loop body:** If the process receives SIGTERM, `asyncio.CancelledError` propagates. Do not catch it with bare `except Exception` — only `except Exception` (not `BaseException`) passes through `CancelledError`.
- **Running migrations inside `async def main()`:** Alembic calls `asyncio.run()` internally; nesting inside an already-running event loop raises `RuntimeError`. Migrations must be run before `asyncio.run(main())`.
- **Sleeping before first cycle:** The decision is "discovery runs immediately on start" — the sleep goes AFTER the cycle, not before it.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Upsert logic | Manual SELECT + INSERT/UPDATE two-step | `postgresql.insert().on_conflict_do_update()` | Atomic, race-condition-free, single DB round-trip |
| HTTP retry on discovery | Custom retry loop at discovery layer | Existing tenacity decorator on `_fetch_page` | Already covers transient errors; no new code needed |
| Interval scheduling | APScheduler or custom timer class | `asyncio.sleep` loop | Already the project pattern; APScheduler 4.0 is pre-release |
| Config validation | Manual env var parsing | pydantic-settings | Already used; just add new fields to Settings |

**Key insight:** The hardest problem in this phase — atomic upsert with conflict handling — is one SQL statement in SQLAlchemy. Everything else is wiring existing Phase 1 primitives together.

---

## Common Pitfalls

### Pitfall 1: Dropping the `signal_status` Enum

**What goes wrong:** `op.drop_table("signals")` succeeds but then subsequent migration steps fail because the `signal_status` PostgreSQL enum type still exists. Or a future `alembic upgrade head` on a fresh DB fails because the enum doesn't exist to drop.

**Why it happens:** Alembic does NOT automatically drop PostgreSQL enum types when dropping the table that uses them. The enum is a separate DB-level type.

**How to avoid:** After `op.drop_table("signals")`, add `op.execute("DROP TYPE IF EXISTS signal_status")`. Use `IF EXISTS` to make the migration idempotent.

**Warning signs:** `psycopg2.errors.UndefinedObject: type "signal_status" does not exist` on fresh schema, or `type "signal_status" already exists` if upgrade is run twice.

### Pitfall 2: Upsert `index_elements` Must Match an Actual Unique Constraint

**What goes wrong:** `on_conflict_do_update(index_elements=["external_id"])` silently fails if `external_id` is not backed by a `UNIQUE` constraint or unique index in the actual DB.

**Why it happens:** PostgreSQL requires the conflict target to reference an existing constraint or unique index.

**How to avoid:** The `markets.external_id` column has `unique=True` in the ORM model and `sa.UniqueConstraint("external_id")` in migration 001. Verify the constraint exists before relying on it. The existing migration 001 has this correct.

**Warning signs:** `sqlalchemy.exc.ProgrammingError: there is no unique or exclusion constraint matching the ON CONFLICT specification`.

### Pitfall 3: `asyncio.CancelledError` Swallowed by Bare `except Exception`

**What goes wrong:** On SIGTERM, `asyncio.CancelledError` is raised inside the loop. A `except Exception` block correctly passes it through (since `CancelledError` is a `BaseException` subclass, not `Exception`). But if someone changes it to `except BaseException`, the loop will catch and log `CancelledError` as an error and continue, preventing clean shutdown.

**Why it happens:** Python 3.8+ makes `CancelledError` a subclass of `BaseException` to prevent exactly this issue. `except Exception` is the correct scope.

**How to avoid:** Always use `except Exception` (not `except BaseException`) in the loop recovery block.

**Warning signs:** Service hangs on SIGTERM; no shutdown log line.

### Pitfall 4: Binary Filter Edge Cases

**What goes wrong:** Some Polymarket markets have `outcomes = ["Yes", "No"]` but others have outcomes like `["Team A", "Team B"]` or `["0", "1"]`. A filter that only checks `len(outcomes) == 2` passes through non-standard binary markets. A filter that checks for exactly `["yes", "no"]` (case-insensitive) is more precise.

**Why it happens:** Polymarket Events can have multiple Markets. "Who wins the Super Bowl" might produce 32 Markets each with team-name outcomes. Each has exactly 2 outcomes but is not a yes/no question.

**How to avoid:** The `_is_binary()` function should check `[o.lower() for o in outcomes] == ["yes", "no"]`. This is the correct semantics for the whale-tracking use case.

**Warning signs:** Markets like "Will Team X win?" appearing in the filtered set with non-standard outcome labels.

### Pitfall 5: Markets With `None` Volume or Liquidity

**What goes wrong:** Filtering `m.volume < settings.market_min_volume` raises `TypeError` if `m.volume` is `None`. The Gamma API sometimes returns `null` for volume/liquidity on newly-created markets.

**Why it happens:** The Market pydantic model has `volume: Optional[float] = None`, so None is a valid value. Comparison with float fails.

**How to avoid:** Treat `None` as 0: `(m.volume or 0) < settings.market_min_volume`. A market with unknown volume should be excluded when a minimum is configured.

**Warning signs:** `TypeError: '<' not supported between instances of 'NoneType' and 'float'` in the discovery cycle.

### Pitfall 6: `fetched_at` Must Be Timezone-Aware

**What goes wrong:** `datetime.now()` returns a naive datetime. The `markets.fetched_at` column is `DateTime(timezone=True)`. PostgreSQL will store it but asyncpg may reject naive datetimes.

**Why it happens:** The column was defined with `timezone=True` in migration 001 and the ORM model. Naive datetimes lack timezone info.

**How to avoid:** Always use `datetime.now(timezone.utc)` or `datetime.utcnow().replace(tzinfo=timezone.utc)` when setting `fetched_at`.

**Warning signs:** `asyncpg.exceptions.DataError: invalid input for query argument $N: datetime.datetime(...)` (without tzinfo).

---

## Code Examples

Verified patterns from official sources:

### Polymarket Binary Market Filter
```python
# Based on: Polymarket Gamma structure docs (gamma-api.polymarket.com)
# Each Market has outcomes: list[str] — binary markets have ["Yes", "No"]
def _is_binary(market) -> bool:
    outcomes_lower = [o.lower() for o in (market.outcomes or [])]
    return outcomes_lower == ["yes", "no"]
```

### Full Upsert Statement
```python
# Source: https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert
from sqlalchemy.dialects.postgresql import insert
from datetime import datetime, timezone

async def upsert_markets(session, market_rows: list[dict]) -> None:
    if not market_rows:
        return
    from arbiter.db.models import Market
    stmt = insert(Market).values(market_rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["external_id"],
        set_={
            "question": stmt.excluded.question,
            "description": stmt.excluded.description,
            "end_date": stmt.excluded.end_date,
            "resolved": stmt.excluded.resolved,
            "closed": stmt.excluded.closed,
            "yes_price": stmt.excluded.yes_price,
            "liquidity": stmt.excluded.liquidity,
            "volume": stmt.excluded.volume,
            "active": stmt.excluded.active,
            "fetched_at": stmt.excluded.fetched_at,
        },
    )
    await session.execute(stmt)
    await session.commit()
```

### Discovery Loop with Heartbeat
```python
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

async def discovery_loop(settings, session_factory, client) -> None:
    while True:
        t0 = time.monotonic()
        try:
            upserted, new_count, filtered = await _run_cycle(settings, session_factory, client)
            elapsed = time.monotonic() - t0
            logger.info(
                "[discovery] cycle complete in %.1fs — %d upserted, %d new, %d filtered out",
                elapsed, upserted, new_count, filtered,
            )
        except Exception as exc:
            elapsed = time.monotonic() - t0
            logger.error("[discovery] cycle failed after %.1fs: %s", elapsed, exc)
        await asyncio.sleep(settings.discovery_interval_seconds)
```

### New Config Fields (pydantic-settings)
```python
# In arbiter/config.py — additions to Settings class
market_binary_only: bool = Field(
    default=True,
    description="Only track binary (Yes/No) markets",
)
market_min_volume: float = Field(
    default=1000.0,
    description="Minimum trading volume in USDC to track a market",
)
market_min_liquidity: float = Field(
    default=1000.0,
    description="Minimum liquidity (open interest) in USDC to track a market",
)
discovery_interval_seconds: int = Field(
    default=300,
    description="Seconds between market discovery cycles",
)
```

### Alembic Migration: Drop Enum After Table
```python
# Pattern for cleaning up PostgreSQL enum types after dropping the table
op.drop_table("signals")
op.execute("DROP TYPE IF EXISTS signal_status")  # Alembic does NOT do this automatically
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `session.merge()` for upsert | `postgresql.insert().on_conflict_do_update()` | SQLAlchemy 2.0 | Single atomic statement, no SELECT round-trip |
| APScheduler for periodic tasks | `asyncio.sleep` loop | Project decision (Roadmap) | No APScheduler dependency; simpler control flow |
| `datetime.utcnow()` | `datetime.now(timezone.utc)` | Python 3.12 (deprecated utcnow) | Timezone-aware; no deprecation warning |

**Deprecated/outdated:**
- `datetime.utcnow()`: deprecated in Python 3.12 with planned removal. Use `datetime.now(timezone.utc)`.
- `session.merge()` for upsert semantics: works but performs a SELECT before deciding INSERT/UPDATE — use dialect-specific upsert for performance.

---

## Open Questions

1. **Counting new markets in heartbeat**
   - What we know: The heartbeat format specifies "N new" — markets upserted for the first time
   - What's unclear: `INSERT ON CONFLICT DO UPDATE` does not natively distinguish new inserts from updates without `RETURNING xmax`
   - Recommendation: Use `RETURNING xmax = 0 AS is_insert` (PostgreSQL-specific: xmax=0 means newly inserted row) or add a `created_at` timestamp column to `markets` to detect first-time inserts. Simplest: track count before and after with a separate `SELECT COUNT(*)` query, or accept that "new" = "rows where we didn't have a DB record before" by adding `created_at` to markets in this migration.

2. **`markets` table `last_ingested_at` column**
   - What we know: Phase 3 (Trade History) requires incremental ingestion keyed on `last_ingested_at` per market
   - What's unclear: Should this column be added in Phase 2 migration or Phase 3 migration?
   - Recommendation: Add it in Phase 2 migration as `nullable=True` so it exists when Phase 3 starts writing to it. Avoids a migration in Phase 3 that modifies the `markets` table.

3. **`markets` table schema gap: no `condition_id` separate from `external_id`**
   - What we know: The existing `markets.external_id` maps to `market.id` from the Gamma API. The Gamma API also returns `condition_id` which is the on-chain identifier used by the CLOB API.
   - What's unclear: Phase 3 trade ingestion will need to link trades to markets — does it use `external_id` (Gamma `id`) or `condition_id`?
   - Recommendation: Verify during Phase 3 research whether CLOB trade records identify the market by `conditionId` or a different field. If `conditionId` is needed, add it to `markets` in Phase 2 migration while the schema is being restructured.

---

## Schema Design (Migration 002)

### Tables to Drop
- `price_snapshots` (no FK to other tables besides `markets`)
- `signals` (FK to `markets`)
- PostgreSQL enum type `signal_status` (used by `signals`)

### Tables to Add

**trades**
```sql
CREATE TABLE trades (
    id              SERIAL PRIMARY KEY,
    wallet_address  VARCHAR NOT NULL,
    market_id       INTEGER NOT NULL REFERENCES markets(id),
    side            VARCHAR(10) NOT NULL,   -- 'YES' | 'NO'
    size            FLOAT NOT NULL,
    price           FLOAT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_trades_wallet ON trades(wallet_address);
CREATE INDEX ix_trades_market ON trades(market_id);
```

**wallets**
```sql
CREATE TABLE wallets (
    id              SERIAL PRIMARY KEY,
    address         VARCHAR NOT NULL UNIQUE,
    win_rate        FLOAT,
    total_volume    FLOAT,
    total_trades    INTEGER,
    score           FLOAT,
    last_scored_at  TIMESTAMPTZ,
    is_tracked      BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX ix_wallets_is_tracked ON wallets(is_tracked);
```

**positions**
```sql
CREATE TABLE positions (
    id              SERIAL PRIMARY KEY,
    wallet_address  VARCHAR NOT NULL,
    market_id       INTEGER NOT NULL REFERENCES markets(id),
    current_size    FLOAT NOT NULL,
    avg_price       FLOAT NOT NULL,
    opened_at       TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_positions_wallet ON positions(wallet_address);
```

### Markets Table Changes
The `markets` table from Phase 1 is kept as-is. The only potential addition is `last_ingested_at TIMESTAMPTZ` (nullable) if the team decides to add it now for Phase 3 compatibility (see Open Questions #2).

---

## Sources

### Primary (HIGH confidence)
- [SQLAlchemy 2.0 PostgreSQL Upsert docs](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert) — `insert().on_conflict_do_update()`, `stmt.excluded`, bulk values list
- [Polymarket Gamma Structure docs](https://docs.polymarket.com/developers/gamma-markets-api/gamma-structure) — confirmed each Market is binary YES/NO; Events group multiple Markets
- Phase 1 Research (`01-RESEARCH.md`) — Alembic async patterns, SQLAlchemy session patterns, tenacity retry on `_fetch_page`
- Existing codebase — `arbiter/clients/polymarket.py`, `arbiter/db/models.py`, `arbiter/db/session.py`, `arbiter/main.py` — all Phase 1 foundations verified by reading source

### Secondary (MEDIUM confidence)
- [Polymarket agents gamma.py](https://github.com/Polymarket/agents/blob/main/agents/polymarket/gamma.py) — confirmed `outcomes` field structure and `outcomePrices`; binary markets use `["Yes", "No"]`
- [Alembic PostgreSQL Enum Pitfall](https://dev.to/ralexandrov/alembic-issues-with-postgresql-enum-processing-69d) — manual `DROP TYPE` required after `op.drop_table()` for enum-backed columns

### Tertiary (LOW confidence)
- WebSearch results on multi-outcome Polymarket markets — confirmed Events have multiple child Markets, each with distinct outcome pairs

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; all libraries verified from Phase 1 and official docs
- Migration pattern: HIGH — official Alembic docs; manual write required (established in Phase 1)
- Upsert pattern: HIGH — official SQLAlchemy 2.0 PostgreSQL dialect docs
- Discovery loop pattern: HIGH — asyncio standard library; established project pattern
- Polymarket binary filter: MEDIUM — confirmed by official Gamma structure docs that markets are binary, but multi-team markets with 2 outcomes are a nuance that needs careful implementation
- Schema design (new tables): HIGH — directly from REQUIREMENTS.md (CLAUDE.md architecture section)
- Open questions: LOW — these are gaps, not verified facts

**Research date:** 2026-02-25
**Valid until:** 2026-05-25 (90 days — SQLAlchemy 2.x, Alembic, and Polymarket Gamma API are stable)
