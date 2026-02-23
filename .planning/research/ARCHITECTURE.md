# Architecture Research

**Domain:** Prediction market signal detection and tracking system
**Researched:** 2026-02-22
**Confidence:** HIGH

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Entry Point (main.py)                        │
│          asyncio.gather([discovery_loop, polling_loop])              │
│          Signal handlers for SIGTERM/SIGINT → cancel tasks           │
└────────────────────────┬────────────────────────────────────────────┘
                         │ spawns two concurrent tasks
         ┌───────────────┴───────────────┐
         ▼                               ▼
┌────────────────┐             ┌──────────────────┐
│ Discovery Loop │             │  Polling Loop    │
│  (~5 min)      │             │  (~1 min)        │
│                │             │                  │
│ list_markets() │             │ get_prices()     │
│ upsert markets │             │ for tracked mkts │
│ (no signals)   │             │ run each detector│
└────────┬───────┘             └────────┬─────────┘
         │                              │
         ▼                              ▼
┌─────────────────────────────────────────────────┐
│              Config Layer (config.py)            │
│         pydantic-settings, .env loading          │
└─────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────────────────────────────────────┐
│           API Client Layer (clients/)            │
│     PolymarketClient (Gamma API, CLOB API)       │
└─────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────────────────────────────────────┐
│              Data Layer (db/)                    │
│   markets | signals | price_snapshots            │
│   PostgreSQL + SQLAlchemy async + Alembic        │
└─────────────────────────────────────────────────┘
                         ▲
                         │ read markets, write signals
                         │
┌─────────────────────────────────────────────────┐
│          Detection Layer (detection/)            │
│   BaseDetector ABC                               │
│   ├── LongshotBiasDetector                       │
│   └── TimeDecayDetector                          │
│   DetectorRegistry: runs all detectors per poll  │
└─────────────────────────────────────────────────┘
                         │ emits Signal objects
                         ▼
┌─────────────────────────────────────────────────┐
│        Notification Layer (notifications/)       │
│   BaseNotifier ABC                               │
│   └── DiscordNotifier (webhook)                  │
└─────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Communicates With |
|-----------|----------------|-------------------|
| `main.py` | Start two async tasks, handle shutdown signals | Config, Discovery Loop, Polling Loop |
| `config.py` | Load and validate environment variables | All layers (injected at startup) |
| `clients/polymarket.py` | Fetch markets and prices from Gamma + CLOB APIs | Discovery Loop, Polling Loop |
| `db/models.py` | SQLAlchemy ORM definitions for all tables | DB session, all layers writing to DB |
| `db/session.py` | Create async engine, provide session factory | All layers needing DB access |
| `detection/base.py` | `BaseDetector` ABC with `detect(market) -> Signal | None` | DetectorRegistry |
| `detection/longshot.py` | Flag 75-95% favorites as potentially underpriced | DetectorRegistry |
| `detection/time_decay.py` | Flag near-expiry markets with mispriced "no" | DetectorRegistry |
| `detection/registry.py` | Run all registered detectors, deduplicate signals | Polling Loop, DB layer, Notifier |
| `notifications/discord.py` | POST signal alerts to Discord webhook | DetectorRegistry |

## Recommended Project Structure

```
arbiter/
├── arbiter/
│   ├── main.py                    # asyncio.gather, signal handlers, startup/shutdown
│   ├── config.py                  # pydantic-settings Settings class
│   ├── clients/
│   │   ├── __init__.py
│   │   └── polymarket.py          # Gamma API + CLOB API (existing, extend for prices)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py              # SQLAlchemy ORM: Market, Signal, PriceSnapshot
│   │   └── session.py             # async_engine, async_sessionmaker factory
│   ├── detection/
│   │   ├── __init__.py
│   │   ├── base.py                # BaseDetector ABC + Signal dataclass
│   │   ├── longshot.py            # LongshotBiasDetector
│   │   ├── time_decay.py          # TimeDecayDetector
│   │   └── registry.py            # DetectorRegistry: runs all, handles dedup
│   └── notifications/
│       ├── __init__.py
│       ├── base.py                # BaseNotifier ABC
│       └── discord.py             # DiscordNotifier
├── alembic/
│   ├── env.py
│   └── versions/                  # migration files
├── tests/
│   ├── conftest.py                # shared fixtures, mock DB session
│   ├── unit/
│   │   ├── test_longshot.py
│   │   ├── test_time_decay.py
│   │   └── test_registry.py
│   └── integration/
│       └── test_polling_loop.py
├── pyproject.toml
├── alembic.ini
└── .env.example
```

### Structure Rationale

- **detection/ split by file per strategy:** Each detector is isolated — adding a new strategy is a new file with zero changes to existing code. Registry discovers them via explicit registration, not magic import scanning.
- **db/ separate from clients/:** DB layer owns persistence; clients own HTTP I/O. Neither knows about the other. Polling loop coordinates between them.
- **notifications/ stays thin:** Notifiers receive a `Signal` object and send it. They don't compute anything. Keeps alert format decoupled from detection logic.

## Architectural Patterns

### Pattern 1: BaseDetector ABC with Structured Signal Return

**What:** Each detector implements a single method: `detect(market: Market, current_price: float) -> Signal | None`. Returns `None` if no signal. Returns a `Signal` dataclass if triggered.

**When to use:** Always. This is the core extensibility mechanism. New strategies add a new file and register with the registry.

**Trade-offs:** Requires each detector to be stateless (market state comes from DB/prices, not detector instance). This is the right constraint — detectors should be pure functions of their inputs.

**Example:**
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from arbiter.clients.polymarket import Market

@dataclass
class Signal:
    market_id: str
    strategy: str           # "longshot_bias" | "time_decay"
    direction: str          # "YES" | "NO"
    price_at_signal: float
    confidence: float       # 0.0-1.0, detector-specific scoring
    rationale: str          # human-readable reason for alert
    detected_at: datetime

class BaseDetector(ABC):
    strategy_name: str      # class attribute, used as DB key

    @abstractmethod
    def detect(self, market: Market) -> Signal | None:
        ...
```

### Pattern 2: DetectorRegistry as the Polling Loop's Detection Brain

**What:** A `DetectorRegistry` holds all registered detector instances. The polling loop calls `registry.run_all(markets, session)` once per tick. The registry iterates all markets across all detectors, deduplicates against recent signals in DB, and returns new signals to notify.

**When to use:** Always. Keeps the polling loop clean — it doesn't need to know how many detectors exist.

**Trade-offs:** Registry needs DB access to check deduplication (don't re-alert the same market with the same strategy within a cooldown window). Pass the session factory in, not an active session.

**Example:**
```python
class DetectorRegistry:
    def __init__(self, session_factory, notifier):
        self._detectors: list[BaseDetector] = []
        self._session_factory = session_factory
        self._notifier = notifier

    def register(self, detector: BaseDetector):
        self._detectors.append(detector)

    async def run_all(self, markets: list[Market]) -> None:
        async with self._session_factory() as session:
            for market in markets:
                for detector in self._detectors:
                    signal = detector.detect(market)
                    if signal and not await self._is_duplicate(signal, session):
                        await self._persist_signal(signal, session)
                        await self._notifier.notify(signal)
            await session.commit()
```

### Pattern 3: Session-Per-Task for Asyncio Safety

**What:** Never share an `AsyncSession` across concurrent tasks. The discovery loop and polling loop each get their own session from the factory when they need DB access.

**When to use:** Always with SQLAlchemy asyncio. Sharing a session across tasks causes subtle corruption.

**Trade-offs:** Slightly more boilerplate (async with session_factory() as session: per operation), but eliminates an entire class of concurrency bugs.

**Example:**
```python
# In db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

def create_session_factory(database_url: str):
    engine = create_async_engine(database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)

# In each loop:
async def polling_loop(session_factory, ...):
    while True:
        async with session_factory() as session:
            markets = await fetch_tracked_markets(session)
            # ... use session, commit, close at end of context
        await asyncio.sleep(POLL_INTERVAL)
```

### Pattern 4: Graceful Shutdown with Task Cancellation

**What:** `main.py` registers SIGTERM and SIGINT handlers that cancel all running tasks. Each loop catches `asyncio.CancelledError` to clean up before exiting. The httpx client and DB engine are disposed in finally blocks.

**When to use:** Any long-running Python service. Without this, Ctrl+C during a DB write or HTTP call leaves connections open.

**Example:**
```python
async def main():
    session_factory = create_session_factory(config.database_url)
    tasks = [
        asyncio.create_task(discovery_loop(session_factory, config)),
        asyncio.create_task(polling_loop(session_factory, config)),
    ]

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: [t.cancel() for t in tasks])

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await engine.dispose()
```

## Data Flow

### Discovery Loop (every 5 minutes)

```
PolymarketClient.list_markets()
    ↓ paginated, all active markets
Upsert into markets table
    (INSERT ... ON CONFLICT DO NOTHING or update active flag)
    ↓ no signal generation at discovery time
Sleep 5 minutes
```

### Polling Loop (every 1 minute)

```
Load active markets from DB (markets table)
    ↓
PolymarketClient.get_prices(market_ids)
    [CLOB API: /book endpoint per token_id for yes_bid/yes_ask]
    ↓
INSERT price_snapshots rows
    ↓
DetectorRegistry.run_all(markets with fresh prices)
    ↓ for each market × each detector:
BaseDetector.detect(market) → Signal | None
    ↓ if Signal and not duplicate:
INSERT into signals table
    ↓
DiscordNotifier.notify(signal) → HTTP POST to webhook
    ↓
Prune price_snapshots older than 24h
    ↓
Sleep 1 minute
```

### Resolution Tracking Flow

```
[On next polling tick, after market closes/resolves:]
PolymarketClient: market.resolved = True, market.resolution = "YES"|"NO"
    ↓
UPDATE markets SET resolved=True, resolution=value, resolved_at=now
    ↓
Query signals WHERE market_id = this market AND resolved_at IS NULL
    ↓ for each open signal:
Determine correct: signal.direction matches market.resolution?
UPDATE signals SET resolved_at=now, was_correct=bool
```

Resolution checking runs inside the polling loop when it notices a market has flipped to `resolved=True`. It backfills all open signals for that market in the same transaction.

## Database Schema

### Tables

```sql
-- Markets tracked by the system
CREATE TABLE markets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id     TEXT NOT NULL UNIQUE,   -- Polymarket condition_id or market id
    platform        TEXT NOT NULL DEFAULT 'polymarket',
    question        TEXT NOT NULL,
    description     TEXT,
    end_date        TIMESTAMPTZ,
    active          BOOLEAN NOT NULL DEFAULT true,
    resolved        BOOLEAN NOT NULL DEFAULT false,
    resolution      TEXT,                   -- "YES" | "NO" | null
    resolved_at     TIMESTAMPTZ,
    volume          NUMERIC,
    liquidity       NUMERIC,
    clob_token_ids  TEXT[],                 -- for CLOB price lookups
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Price snapshots for the rolling 24h window
CREATE TABLE price_snapshots (
    id          BIGSERIAL PRIMARY KEY,
    market_id   UUID NOT NULL REFERENCES markets(id),
    yes_bid     NUMERIC,
    yes_ask     NUMERIC,
    no_bid      NUMERIC,
    no_ask      NUMERIC,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_price_snapshots_market_fetched
    ON price_snapshots(market_id, fetched_at DESC);

-- Signals generated by detectors
CREATE TABLE signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id       UUID NOT NULL REFERENCES markets(id),
    strategy        TEXT NOT NULL,          -- "longshot_bias" | "time_decay"
    direction       TEXT NOT NULL,          -- "YES" | "NO"
    price_at_signal NUMERIC NOT NULL,       -- yes_ask at detection time
    confidence      NUMERIC NOT NULL,       -- 0.0-1.0, detector-provided
    rationale       TEXT NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    alerted_at      TIMESTAMPTZ,            -- null until Discord notified
    -- Resolution fields (backfilled after market resolves)
    resolved_at     TIMESTAMPTZ,
    was_correct     BOOLEAN,                -- null until resolved
    resolution_price NUMERIC                -- price at market resolution time
);
CREATE INDEX idx_signals_market_strategy
    ON signals(market_id, strategy);
CREATE INDEX idx_signals_unresolved
    ON signals(resolved_at) WHERE resolved_at IS NULL;
CREATE UNIQUE INDEX idx_signals_dedup
    ON signals(market_id, strategy)
    WHERE resolved_at IS NULL;             -- one open signal per market+strategy
```

### Key Schema Decisions

**Dedup via partial unique index:** `idx_signals_dedup` enforces at most one open (unresolved) signal per market per strategy. This prevents re-alerting a market that already has an active signal for the same strategy. When the market resolves, the signal gets `resolved_at` set, which removes it from the partial index, allowing future signals on re-opened markets.

**`resolution_price` on signals:** Store the price at resolution time to calculate P&L later (price moved from `price_at_signal` to 1.0 or 0.0). Supports backtesting accuracy and calibration analysis.

**`alerted_at` separate from `detected_at`:** If Discord webhook fails, the signal is in DB but not alerted. On next tick, retry logic can find `alerted_at IS NULL` and re-attempt notification without duplicate detection re-running.

**No `market_pairs` table for this milestone:** Kalshi cross-platform arb is deferred. Dropping this table from scope eliminates the pgvector dependency, sentence-transformers, and Claude API calls entirely. The `markets` table stays single-platform.

## Build Order (Dependency Chain)

```
1. config.py
   └── Required by everything that reads environment variables

2. db/models.py + db/session.py + Alembic initial migration
   └── Required by discovery loop, polling loop, detectors

3. clients/polymarket.py (extend existing for CLOB prices)
   └── Required by both loops; discovery uses Gamma, polling uses CLOB

4. Detection layer: base.py → longshot.py → time_decay.py → registry.py
   └── Depends on: Market model (clients), Signal dataclass (base.py), DB session

5. notifications/discord.py
   └── Depends on: Signal dataclass, config (webhook URL)

6. main.py (rewrite from current stub)
   └── Depends on: everything above; wires it all together
```

**Do not start #4 until #2 and #3 are complete.** The detector dedup logic queries the signals table — schema must exist and be migrated before detectors can be tested end-to-end. Running detectors without the schema means their output has nowhere to go, and testing is hollow.

**Config first, always.** Every other component reads from `Settings`. Implement and validate config before any other code to avoid hardcoded values leaking into components that are awkward to refactor.

## Anti-Patterns

### Anti-Pattern 1: Generating Signals During Discovery

**What people do:** Run detectors inside the discovery loop on newly fetched markets.

**Why it's wrong:** Discovery sees market metadata only — it does not have fresh prices from the CLOB API. A longshot detector needs the current best ask, not stale Gamma API price fields. Signals fired at discovery time will be based on potentially hours-old prices.

**Do this instead:** Discovery only upserts market metadata. Polling fetches fresh prices and runs detectors. Keep them in separate loops as designed.

### Anti-Pattern 2: One Session for the Whole Loop

**What people do:** Create an `AsyncSession` at startup and pass it to all coroutines for the lifetime of the process.

**Why it's wrong:** SQLAlchemy's asyncio session is not safe across concurrent tasks. The discovery loop and polling loop run as separate `asyncio.Task` objects and can interleave at await points. A shared session will corrupt transaction state.

**Do this instead:** Use `async_sessionmaker` as a factory. Each DB operation block opens its own `async with session_factory() as session:` scope and closes it at the end.

### Anti-Pattern 3: Hardcoding Detector Thresholds

**What people do:** Put `if yes_ask < 0.90 and yes_ask > 0.75:` directly in detector logic with no external configuration.

**Why it's wrong:** Thresholds need tuning. If they're hardcoded, changing them requires code deploys. You'll want to adjust them as you accumulate signal resolution data.

**Do this instead:** Read thresholds from `config.py` (environment variables). Detectors receive a config object or are initialized with threshold parameters from config.

### Anti-Pattern 4: Re-Alerting Every Poll Cycle

**What people do:** Notify Discord every time a market meets detector criteria, on every poll tick.

**Why it's wrong:** A market that meets longshot criteria for 3 days straight will spam the channel with 4,320 duplicate alerts before it resolves. Signal-to-noise collapses.

**Do this instead:** Use the `UNIQUE INDEX ON signals(market_id, strategy) WHERE resolved_at IS NULL` constraint. One open signal per strategy per market. Detect → insert → alert exactly once. Re-alert only when the market resolves and re-enters eligible criteria later.

### Anti-Pattern 5: Blocking HTTP Calls in the Polling Loop Without Timeout

**What people do:** Call `await client.get_prices(...)` with no timeout configured on the httpx client.

**Why it's wrong:** A single Polymarket CLOB endpoint that hangs will stall the entire polling loop for the duration of the default timeout (or indefinitely with no timeout). With 100+ markets tracked, this cascades.

**Do this instead:** Configure explicit per-request timeouts on the httpx client (5-10 seconds is usually sufficient). Log timeout events. Skip the stalled market and continue — stale data is better than a frozen loop.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Polymarket Gamma API | HTTP GET `/markets` with pagination | Market discovery; no auth required |
| Polymarket CLOB API | HTTP GET `/book?token_id=X` | Price polling; may need API key for higher rate limits |
| Discord Webhook | HTTP POST JSON payload | Fire-and-forget; retry on 429/5xx |
| PostgreSQL | SQLAlchemy asyncpg driver | `postgresql+asyncpg://` URL in config |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Polling Loop → DetectorRegistry | Direct async call, pass `list[Market]` with current prices | Registry returns nothing; side effects are DB writes and notifications |
| DetectorRegistry → BaseDetector | Synchronous call to `detect(market)` | Detectors are pure functions — no async, no DB access |
| DetectorRegistry → DB | Async session via factory | Session opened per registry.run_all() call |
| DetectorRegistry → Notifier | Async call to `notify(signal)` | Notifier is awaitable; awaited before session commits |
| Discovery Loop → DB | Async session via factory | Upsert markets; close session before sleeping |

**Detectors are synchronous by design.** They receive a fully-hydrated `Market` object with current prices already fetched. They run pure computation and return a `Signal` or `None`. Keeping them sync makes them trivially testable without asyncio fixtures.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 100-500 markets | Current design handles comfortably; single process, 1 DB connection per loop tick |
| 500-5,000 markets | CLOB price fetching becomes the bottleneck; batch price requests or parallelize with `asyncio.gather()` per market batch |
| 5,000+ markets | Consider splitting discovery and polling into separate processes; add a job queue (Redis + arq or Celery) for signal dispatch |

The current architecture targets the 100-500 market range. Polymarket has ~2,000 active markets, but a Arbiter will likely track a filtered subset (active, sufficient liquidity, sufficient volume). Pagination in the discovery loop is necessary but single-process throughput is fine.

## Sources

- [SQLAlchemy Asyncio Documentation](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) — session-per-task pattern, async_sessionmaker, expire_on_commit=False
- [Elastic Blog: 3 Essential Async Patterns](https://www.elastic.co/blog/async-patterns-building-python-service) — graceful shutdown, task cancellation, sleep interruption
- [Python asyncio Coroutines and Tasks](https://docs.python.org/3/library/asyncio-task.html) — asyncio.gather, task cancellation
- [Roguelynn: Graceful Shutdowns with asyncio](https://roguelynn.com/words/asyncio-graceful-shutdowns/) — SIGTERM/SIGINT handling patterns
- [Refactoring Guru: Strategy Pattern in Python](https://refactoring.guru/design-patterns/strategy/python/example) — BaseDetector ABC pattern rationale

---
*Architecture research for: Polymarket signal detection system*
*Researched: 2026-02-22*
