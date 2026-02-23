# Phase 1: Foundation - Research

**Researched:** 2026-02-22
**Domain:** pydantic-settings config, SQLAlchemy 2.0 async + Alembic migrations, Gamma API client hardening
**Confidence:** HIGH (stack verified against official docs; patterns from official SQLAlchemy and Alembic sources)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- pydantic-settings config with .env file support; fail-fast with ALL missing vars listed + format hints
- Alembic migrations for markets, signals, price_snapshots tables (with partial unique index for signal dedup)
- SQLAlchemy 2.0 async with asyncpg
- Docker Compose for local PostgreSQL
- Startup: config summary printed, DB + API health check, "service ready" line, retry on DB unreachable
- `--check` flag for pre-deploy config validation
- Gamma API client: full pagination, retry on transient errors, fix existing fragility issues
- Logging: plain text with timestamp, configurable via LOG_LEVEL env var, `--verbose` flag

### Claude's Discretion
- Whether migrations run automatically on startup or require `alembic upgrade head` — use standard Alembic/Python pattern
- Log destination (console vs file) — console only is fine
- Connection pool size and settings — pick sensible defaults
- Exact retry count and backoff for startup DB connection

### Deferred Ideas (OUT OF SCOPE)
- Discord alert on crash/restart — noted for Phase 5 hardening
- Structured JSON logging — user chose plain text for now; could revisit in Phase 5
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFRA-01 | System loads all configuration (DB URL, API keys, Discord webhook, detection thresholds) from environment variables with validation at startup | pydantic-settings BaseSettings with model_config env_file; ValidationError catches all field errors at once |
| INFRA-02 | System fails fast with a clear error message if any required config is missing | pydantic ValidationError collects ALL errors before raising; intercept and reformat with field name + hint |
| INFRA-03 | PostgreSQL database schema managed with Alembic migrations (tables: markets, signals, price_snapshots) | Alembic `init -t async` + async env.py; partial unique index via op.create_index with postgresql_where |
| CLIENT-01 | Polymarket Gamma API client reliably fetches all active markets with pagination | Gamma API uses offset+limit; stop when batch < limit; filters: active=True, closed=False, archived=False |
| CLIENT-03 | Both API clients handle rate limits and transient errors with retry logic | tenacity async retry with exponential backoff on httpx.HTTPStatusError (429, 503) and httpx.NetworkError |
</phase_requirements>

---

## Summary

Phase 1 establishes four independent primitives that all later phases depend on: a validated config layer, a PostgreSQL schema with Alembic migrations, a reliable Gamma API client, and a structured entry point. These are well-understood engineering problems with official documentation and stable libraries — the research surface is narrow.

The most important correctness decisions belong to the schema design, not the config or client. The partial unique index for signal deduplication (`WHERE status = 'active'`), the resolution enum columns, and the `price_at_signal` / `hours_to_expiry` columns on the signals table must all exist in migration 001. Retrofitting them after signals exist requires a destructive migration. The schema for Phase 3 features must be created in Phase 1.

The Gamma API client has two concrete bugs to fix: it does not paginate (fetches only first batch), and it silently eats parse failures. Retry logic via `tenacity` is the standard Python pattern for this — not a custom wrapper. Migration strategy recommendation: run `alembic upgrade head` in the Docker Compose command before starting the service, which is the standard pattern for containerized Python services and avoids startup coupling inside the application code.

**Primary recommendation:** Use `alembic init -t async`, intercept `ValidationError` on settings construction for formatted multi-error output, add `tenacity` for Gamma client retry, and define the full signal schema in migration 001 even though detectors are Phase 3.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic-settings | ^2.13 (already installed) | Load + validate config from env | Official pydantic project; handles .env files natively |
| SQLAlchemy | ^2.0.46 | Async ORM + schema declarations | Official async support since 2.0; asyncpg dialect |
| asyncpg | ^0.31.0 | PostgreSQL async driver | Required by SQLAlchemy asyncpg dialect; no sync overhead |
| Alembic | ^1.18.4 | Schema migrations | Ships from same org as SQLAlchemy; async template included |
| tenacity | ^9.0 | Retry with backoff | De facto Python retry library; native async/await support |
| python-dotenv | ^1.2 (already installed) | .env file loading | Already in project; pydantic-settings calls it internally |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx | ^0.27 (already installed) | HTTP client (already used) | DB health check, Gamma API calls |

### Not Adding
| Excluded | Reason |
|----------|--------|
| APScheduler | Pre-release 4.0; asyncio.sleep loops are the existing pattern |
| pgvector | Out of scope for this milestone (matching deferred) |
| sentence-transformers, anthropic SDK | Out of scope; Kalshi matching deferred |

**Installation:**
```bash
poetry add sqlalchemy asyncpg alembic tenacity
```

---

## Architecture Patterns

### Recommended Project Structure (Phase 1 additions)
```
arbiter/
├── config.py              # pydantic-settings Settings class (NEW)
├── db/
│   ├── __init__.py
│   ├── models.py          # SQLAlchemy ORM models (NEW)
│   └── session.py         # async engine + sessionmaker factory (NEW)
├── clients/
│   └── polymarket.py      # extend with pagination + retry (MODIFY)
├── main.py                # rewrite: argparse, startup checks (REWRITE)
alembic/
├── alembic.ini
├── env.py                 # async template
└── versions/
    └── 001_initial_schema.py
docker-compose.yml         # NEW
.env.example               # NEW
```

### Pattern 1: pydantic-settings with collected error output

**What:** Construct `Settings()` in a try/except block. pydantic collects ALL field validation errors before raising `ValidationError` — do not catch field by field.

**When to use:** Always — this is the only correct pattern. Single-field error collection is built in.

**Example:**
```python
# Source: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
import sys
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        description="PostgreSQL connection string: postgresql+asyncpg://user:pass@localhost/arbiter"
    )
    polymarket_api_key: str = Field(
        description="Polymarket API key from https://polymarket.com/profile"
    )
    discord_webhook_url: str = Field(
        description="Discord webhook URL: https://discord.com/api/webhooks/..."
    )
    log_level: str = Field(default="INFO", description="One of: DEBUG, INFO, WARNING, ERROR")


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        lines = ["Configuration errors — fix all before starting:\n"]
        for err in exc.errors():
            field = err["loc"][0]
            # Get the Field description as a hint
            field_info = Settings.model_fields.get(str(field))
            hint = field_info.description if field_info else ""
            lines.append(f"  {str(field).upper()}: {err['msg']}")
            if hint:
                lines.append(f"    Hint: {hint}")
        print("\n".join(lines), file=sys.stderr)
        sys.exit(1)
```

### Pattern 2: SQLAlchemy 2.0 async engine + session factory

**What:** Create engine once at module level with `create_async_engine`. Create `async_sessionmaker` with `expire_on_commit=False`. Each task gets its own session via `async with session_factory() as session`.

**When to use:** All DB access. Never share an `AsyncSession` across concurrent asyncio tasks.

**Example:**
```python
# Source: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,   # detect stale connections
    echo=False,
)

session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # REQUIRED: prevents lazy-load errors after commit
)

# Usage in tasks:
async with session_factory() as session:
    async with session.begin():
        session.add(some_object)
    # commit happens automatically on context manager exit

# Cleanup on shutdown:
await engine.dispose()
```

**Critical:** `expire_on_commit=False` is not optional. Without it, accessing any ORM attribute after `session.commit()` triggers a lazy load that fails in async context.

### Pattern 3: Alembic async configuration

**What:** Initialize Alembic with the async template. Configure `env.py` to import settings and set the DB URL programmatically. Create migration script manually (autogenerate is unreliable for partial indexes).

**When to use:** Once during project setup. All future schema changes get new migration files.

**Commands:**
```bash
alembic init -t async alembic
# Then edit alembic/env.py to inject DATABASE_URL from settings
alembic revision -m "initial_schema"   # create empty migration to fill in
alembic upgrade head                   # run migrations
```

**env.py critical section:**
```python
# Source: https://github.com/sqlalchemy/alembic/blob/main/alembic/templates/async/env.py
# In alembic/env.py, after the boilerplate:
import os
from arbiter.db.models import Base

config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
target_metadata = Base.metadata
```

**Migration strategy (Claude's discretion):** Run `alembic upgrade head` via Docker Compose command before the service starts — this is the standard Python/Alembic pattern for containerized services. Avoids coupling migration logic into application startup code, keeps the service process clean, and makes rollback straightforward.

```yaml
# docker-compose.yml service command:
command: sh -c "alembic upgrade head && python -m arbiter.main"
```

**Alternative for non-Docker local dev:** Document in README that developers run `alembic upgrade head` after `docker compose up -d postgres`.

### Pattern 4: Gamma API full pagination

**What:** Loop with `offset` until a batch returns fewer items than `limit`. Use `active=True, closed=False, archived=False` filters. Stop condition: `len(batch) < limit`.

**Source:** Polymarket first-party [agents/polymarket/gamma.py](https://github.com/Polymarket/agents/blob/main/agents/polymarket/gamma.py)

```python
async def fetch_all_active_markets(self) -> list[Market]:
    all_markets = []
    offset = 0
    limit = 100  # Gamma API max per page

    while True:
        batch = await self._fetch_page(offset=offset, limit=limit)
        all_markets.extend(batch)
        if len(batch) < limit:
            break
        offset += limit

    return all_markets

async def _fetch_page(self, offset: int, limit: int) -> list[Market]:
    params = {
        "active": "true",
        "closed": "false",
        "archived": "false",
        "limit": limit,
        "offset": offset,
    }
    response = await self._client.get("/markets", params=params)
    response.raise_for_status()
    return [self._parse_market(item) for item in response.json()]
```

### Pattern 5: Tenacity retry for async HTTP

**What:** Decorate API call methods with `@retry` from tenacity. Retry on transient network errors and 429/503 HTTP status codes. Exponential backoff with jitter.

```python
# Source: https://tenacity.readthedocs.io/
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import httpx

def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 502, 503, 504)
    return isinstance(exc, (httpx.NetworkError, httpx.TimeoutException))

@retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.NetworkError, httpx.TimeoutException)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
async def _fetch_page(self, offset: int, limit: int) -> list[Market]:
    ...
```

**Note:** `retry_if_exception_type` retries on all matching exceptions. For 429 specifically, you may want to respect `Retry-After` header — but for a polling system that runs every 5 minutes, simple exponential backoff is sufficient.

### Pattern 6: Startup sequence with DB retry

**What:** On startup, attempt DB connection with backoff. Fail clearly after N attempts.

```python
import asyncio
import sys
import logging
from sqlalchemy import text

async def check_db_health(engine, retries: int = 5, backoff: float = 2.0) -> None:
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logging.info("Database connection OK")
            return
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                wait = backoff ** attempt
                logging.warning(f"DB unreachable (attempt {attempt}/{retries}), retrying in {wait:.0f}s")
                await asyncio.sleep(wait)
    logging.error(f"Database unreachable after {retries} attempts: {last_exc}")
    sys.exit(1)
```

### Pattern 7: `--check` flag via argparse

**What:** Standard `argparse` subcommand or flag. When `--check` is passed, run config load + DB health check + Gamma API ping, print result, exit 0/1.

```python
import argparse
import asyncio

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Arbiter signal detection service")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate config and connectivity, then exit",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging (same as LOG_LEVEL=DEBUG)",
    )
    return parser
```

### Pattern 8: Logging setup

**What:** Standard library `logging` module. Format: `%(asctime)s [%(levelname)s] %(message)s`. Date format: `%Y-%m-%d %H:%M:%S`. Level from `LOG_LEVEL` env var; `--verbose` overrides to DEBUG.

```python
import logging
import sys

def configure_logging(level: str = "INFO", verbose: bool = False) -> None:
    effective_level = logging.DEBUG if verbose else getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=effective_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # Errors go to stderr separately — route WARNING+ to stderr if desired
    # For now: stdout only as decided, shell redirection handles file routing
```

### Anti-Patterns to Avoid

- **Sharing AsyncSession across tasks:** Never pass one `AsyncSession` to two `asyncio.gather` tasks simultaneously. Session is not thread/task safe.
- **`expire_on_commit=True` (default):** Accessing ORM attributes after `session.commit()` triggers lazy load, crashes in async.
- **Catching exceptions in paginator loop without re-raising:** A `try/except` that logs and returns empty will hide partial failures. On transient error, let tenacity retry; on permanent error, propagate.
- **`alembic upgrade head` inside `async def main()`:** Alembic's `asyncio.run()` in `run_migrations_online()` cannot run inside an already-running event loop. Run migrations before the main event loop starts, ideally via Docker Compose command.
- **Silent JSON parse failure:** The existing `_parse_json_field()` returns `[]` on failure. For fields critical to signal detection (outcome_prices, clob_token_ids), log the failure with the raw value so issues are detectable.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP retry with backoff | Custom sleep/loop wrapper | `tenacity` | Handles jitter, per-exception filtering, async/await, logging |
| Config validation | Custom env var reader | pydantic-settings | Already in project; collects all errors at once |
| DB migrations | Hand-crafted ALTER TABLE scripts | Alembic | Version history, rollback support, team coordination |
| Async DB connection pooling | Custom pool management | SQLAlchemy `create_async_engine` with pool_size | Handles pre-ping, connection recycling, overflow |

**Key insight:** The retry and pooling problems have subtle edge cases (jitter to avoid thundering herd, stale connection detection, graceful degradation on pool exhaustion) that are handled correctly by tenacity and SQLAlchemy's pool implementation.

---

## Common Pitfalls

### Pitfall 1: Partial index not auto-detected by Alembic autogenerate

**What goes wrong:** `alembic revision --autogenerate` may not detect or correctly render the `WHERE status = 'active'` partial unique index. It generates an empty migration or drops/recreates the index on subsequent runs.

**Why it happens:** Known Alembic limitation — partial indexes with `postgresql_where` are not reliably round-tripped through autogenerate introspection.

**How to avoid:** Write the migration manually. Use `op.create_index(..., postgresql_where="status = 'active'")` directly. Do not rely on autogenerate for this specific index. Use `--autogenerate` only for basic column changes.

**Warning signs:** Running `alembic revision --autogenerate` produces a migration that drops and recreates the index without the WHERE clause.

### Pitfall 2: `expire_on_commit=True` (SQLAlchemy default)

**What goes wrong:** After `session.commit()`, all ORM object attributes are expired. The next attribute access triggers a lazy-load SELECT. In asyncio context, this raises `MissingGreenlet` or `greenlet_spawn has not been called` errors at runtime.

**Why it happens:** SQLAlchemy's expiry mechanism is designed for synchronous greenlet-based access; async context cannot transparently issue the SELECT.

**How to avoid:** Always create the sessionmaker with `expire_on_commit=False`. This is a one-time config decision.

**Warning signs:** `sqlalchemy.exc.MissingGreenlet` or attribute access errors after commit in async code.

### Pitfall 3: `alembic upgrade head` inside an existing event loop

**What goes wrong:** Alembic's async template calls `asyncio.run(run_async_migrations())`. If the application's event loop is already running (i.e., you call this from inside `async def main()`), you get `RuntimeError: This event loop is already running`.

**Why it happens:** `asyncio.run()` creates and runs a new event loop; it cannot be nested inside an existing one.

**How to avoid:** Run migrations before `asyncio.run(main())` in `main_sync()`, or via Docker Compose command (`alembic upgrade head && python -m arbiter.main`).

**Warning signs:** `RuntimeError: This event loop is already running` at startup.

### Pitfall 4: Gamma API `closed=False` string vs boolean

**What goes wrong:** The existing client passes `"closed": str(closed).lower()` which sends the string `"false"`. The Gamma API appears to accept this, but the first-party client uses `"closed": False` (Python bool, serialized by httpx as `false` in query string).

**Why it happens:** httpx serializes `False` as `false` and `"false"` as `"false"` — both should work. But `"active": True` vs `"active": "true"` matters: httpx serializes the Python bool correctly. The concern is that passing Python bool `True` is safer than string `"True"`.

**How to avoid:** Pass Python booleans directly; httpx handles serialization. Use `active=True, closed=False, archived=False`.

### Pitfall 5: Gamma API `active` filter vs `archived` filter

**What goes wrong:** Fetching with only `closed=False` includes markets that are active but archived. The Polymarket first-party client adds `archived=False` as a third filter.

**Why it happens:** Gamma API has three orthogonal states: active (trading open), closed (trading ended), archived (removed from primary listing). All three filters are needed for "currently tradable" markets.

**How to avoid:** Use all three: `active=True, closed=False, archived=False`.

### Pitfall 6: pydantic-settings ValidationError field names vs env var names

**What goes wrong:** pydantic `ValidationError.errors()` reports the Python field name (e.g., `database_url`), not the environment variable name (`DATABASE_URL`). Error messages are confusing to operators.

**Why it happens:** pydantic reports field names; the env var name mapping is the field name uppercased with any prefix applied.

**How to avoid:** In the error handler, reconstruct the env var name: `field_name.upper()` (plus any `env_prefix` from model_config). Display as `"Set DATABASE_URL to ..."` not `"database_url: field required"`.

---

## Code Examples

Verified patterns from official sources:

### SQLAlchemy ORM model declaration (2.0 style)
```python
# Source: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
from sqlalchemy import String, Float, DateTime, Enum, Index, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime
import enum

class Base(DeclarativeBase):
    pass

class SignalStatus(str, enum.Enum):
    active = "active"
    resolved_correct = "resolved_correct"
    resolved_incorrect = "resolved_incorrect"
    expired = "expired"
    void = "void"

class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    market_id: Mapped[str] = mapped_column(String, nullable=False)
    strategy: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[SignalStatus] = mapped_column(
        Enum(SignalStatus), nullable=False, default=SignalStatus.active
    )
    signal_price: Mapped[float] = mapped_column(Float, nullable=False)
    hours_to_expiry: Mapped[float] = mapped_column(Float, nullable=True)
    liquidity_at_signal: Mapped[float] = mapped_column(Float, nullable=True)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    # Partial unique index for deduplication: one active signal per market+strategy
    __table_args__ = (
        Index(
            "ix_signals_market_strategy_active",
            "market_id",
            "strategy",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )
```

### Alembic partial unique index in migration
```python
# In alembic/versions/001_initial_schema.py
def upgrade() -> None:
    op.create_table("signals", ...)

    # Partial unique index — MUST be written manually, not via autogenerate
    op.create_index(
        "ix_signals_market_strategy_active",
        "signals",
        ["market_id", "strategy"],
        unique=True,
        postgresql_where="status = 'active'",
    )

def downgrade() -> None:
    op.drop_index("ix_signals_market_strategy_active", table_name="signals")
    op.drop_table("signals")
```

### Docker Compose for local PostgreSQL
```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: arbiter
      POSTGRES_PASSWORD: arbiter
      POSTGRES_DB: arbiter
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U arbiter"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

### Config summary print
```python
def print_config_summary(settings: Settings) -> None:
    """Print all loaded config values at startup for operator verification."""
    import logging
    logging.info("=== Configuration ===")
    logging.info(f"  DATABASE_URL: {settings.database_url[:20]}...") # truncate secrets
    logging.info(f"  LOG_LEVEL: {settings.log_level}")
    logging.info(f"  LONGSHOT_PRICE_MIN: {settings.longshot_price_min}")
    logging.info(f"  LONGSHOT_PRICE_MAX: {settings.longshot_price_max}")
    # etc. — all values visible, secrets masked after prefix
    logging.info("====================")
```

---

## Schema Design (Migration 001)

This is Phase 1's highest-stakes decision. The schema must anticipate Phase 3 signal storage requirements.

### Tables Required

**markets**
```sql
CREATE TABLE markets (
    id          SERIAL PRIMARY KEY,
    external_id VARCHAR NOT NULL UNIQUE,   -- Polymarket market condition_id
    question    TEXT NOT NULL,
    description TEXT,
    end_date    TIMESTAMPTZ,
    resolved    BOOLEAN NOT NULL DEFAULT FALSE,
    closed      BOOLEAN NOT NULL DEFAULT FALSE,
    yes_price   FLOAT,
    liquidity   FLOAT,
    volume      FLOAT,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    fetched_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_markets_active ON markets(active);
```

**signals**
```sql
CREATE TYPE signal_status AS ENUM (
    'active', 'resolved_correct', 'resolved_incorrect', 'expired', 'void'
);
CREATE TABLE signals (
    id                  SERIAL PRIMARY KEY,
    market_id           INTEGER NOT NULL REFERENCES markets(id),
    market_question     TEXT NOT NULL,      -- cached for reporting without join
    strategy            VARCHAR NOT NULL,   -- 'longshot_bias' | 'time_decay'
    signal_direction    VARCHAR NOT NULL,   -- 'yes' | 'no'
    signal_price        FLOAT NOT NULL,
    hours_to_expiry     FLOAT,
    liquidity_at_signal FLOAT,
    status              signal_status NOT NULL DEFAULT 'active',
    resolution_outcome  VARCHAR,           -- 'YES' | 'NO' | 'NA' | 'DISPUTED'
    fired_at            TIMESTAMPTZ NOT NULL,
    resolved_at         TIMESTAMPTZ
);
-- Partial unique index: one active signal per market+strategy
CREATE UNIQUE INDEX ix_signals_market_strategy_active
    ON signals(market_id, strategy)
    WHERE status = 'active';
```

**price_snapshots**
```sql
CREATE TABLE price_snapshots (
    id          SERIAL PRIMARY KEY,
    market_id   INTEGER NOT NULL REFERENCES markets(id),
    yes_bid     FLOAT,
    yes_ask     FLOAT,
    liquidity   FLOAT,
    fetched_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_price_snapshots_market_fetched ON price_snapshots(market_id, fetched_at DESC);
```

### Why these columns matter

- `market_question` on signals: denormalized for reporting queries without joins — signals outlive markets being "active"
- `signal_price` + `hours_to_expiry`: required to evaluate strategy calibration (was 85% price accurate at 85%?)
- `resolution_outcome` as VARCHAR not BOOL: Polymarket resolves as YES/NO/NA/DISPUTED — boolean loses information
- `status` as enum not boolean: enables state machine enforcement and the partial index WHERE clause
- Partial index on `status = 'active'`: enforces one active signal per market+strategy at DB level; no application-layer dedup needed

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| SQLAlchemy sync with psycopg2 | SQLAlchemy 2.0 async with asyncpg | Required for non-blocking IO in asyncio service |
| Alembic init (sync) | `alembic init -t async` | env.py pre-configured for asyncpg |
| Manual retry loops | tenacity decorators | Cleaner, handles jitter and logging automatically |
| `UNIQUE(market_id, strategy)` | Partial index `WHERE status = 'active'` | Allows historical signals; only enforces uniqueness on open signals |

---

## Open Questions

1. **Migration strategy for non-Docker dev environments**
   - What we know: Docker Compose runs `alembic upgrade head` before service; works cleanly
   - What's unclear: Developers who run without Docker need a documented step
   - Recommendation: Add to .env.example a comment: "After `docker compose up -d`, run `alembic upgrade head` before `arbiter`"

2. **Gamma API `active` field behavior**
   - What we know: Polymarket first-party uses `active=True`; our client does not currently pass this filter
   - What's unclear: Whether `closed=False` alone is sufficient or whether some markets are non-closed but also non-active
   - Recommendation: Match first-party behavior — use all three: `active=True, closed=False, archived=False`. Low risk of over-filtering; prevents fetching stale markets.

3. **asyncpg connection string format**
   - What we know: SQLAlchemy requires `postgresql+asyncpg://` prefix; psycopg2 uses `postgresql://`
   - What's unclear: Whether users might have an existing DATABASE_URL with wrong dialect prefix
   - Recommendation: Validate DATABASE_URL in settings with a Pydantic validator that checks prefix; provide clear hint if wrong format detected.

---

## Sources

### Primary (HIGH confidence)
- [SQLAlchemy Asyncio Docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) — async_sessionmaker, expire_on_commit=False, session-per-task
- [Alembic Async Template env.py](https://github.com/sqlalchemy/alembic/blob/main/alembic/templates/async/env.py) — official async migration template
- [Alembic Operation Reference](https://alembic.sqlalchemy.org/en/latest/ops.html) — op.create_index with postgresql_where
- [Polymarket agents/polymarket/gamma.py](https://github.com/Polymarket/agents/blob/main/agents/polymarket/gamma.py) — first-party pagination pattern and filters
- [Pydantic Settings Docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — BaseSettings, model_config, env_file, ValidationError

### Secondary (MEDIUM confidence)
- [Berk Karaal: FastAPI + Async SQLAlchemy 2 + Alembic + Docker (2024)](https://berkkaraal.com/blog/2024/09/19/setup-fastapi-project-with-async-sqlalchemy-2-alembic-postgresql-and-docker/) — alembic init -t async workflow, Docker Compose migration command
- [Polymarket Fetch Markets Guide](https://docs.polymarket.com/developers/gamma-markets-api/fetch-markets-guide) — pagination parameters confirmed: offset, limit, active, closed
- [Tenacity docs](https://tenacity.readthedocs.io/) — async retry decorator, exponential backoff API

### Tertiary (LOW confidence)
- Alembic partial index autogenerate limitation — inferred from [GitHub Issue #750](https://github.com/sqlalchemy/alembic/issues/750); behavior may have improved in 1.18.x but manual migration is safer regardless

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions verified against PyPI and official docs
- Architecture patterns: HIGH — directly from official SQLAlchemy, Alembic, and Polymarket sources
- Schema design: HIGH — columns derived from downstream requirements (STORE-01, STORE-02, STORE-03) which are locked
- Pitfalls: HIGH for async SQLAlchemy gotchas (official docs); MEDIUM for Gamma API filter behavior (first-party reference)

**Research date:** 2026-02-22
**Valid until:** 2026-05-22 (90 days — stack is stable; SQLAlchemy 2.x has no breaking changes planned)
