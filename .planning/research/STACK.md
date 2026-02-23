# Stack Research

**Domain:** Prediction market signal detection — Python async app adding persistence, signal strategies, and alerting
**Researched:** 2026-02-22
**Confidence:** HIGH (all versions verified against PyPI; architecture rationale from official docs)

---

## Context

This is an additive milestone on an existing Python 3.12 / asyncio / httpx / pydantic stack. The Polymarket Gamma API client is functional. The goal is to add:

- PostgreSQL persistence (markets, signals, resolutions)
- Longshot bias and time decay signal detectors
- Discord alerting
- Scheduling/polling loop management

This milestone does NOT include Kalshi, cross-platform matching, or vector similarity search. pgvector, sentence-transformers, and the Anthropic SDK are explicitly out of scope.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| SQLAlchemy | `^2.0.46` | ORM + async query interface | Stable async support via `create_async_engine` + `async_sessionmaker`. 2.0 style is the current idiom; avoids 1.x legacy patterns. Pairs directly with existing pydantic models. |
| asyncpg | `^0.31.0` | PostgreSQL async driver | Required by SQLAlchemy's `postgresql+asyncpg://` dialect. Purpose-built for asyncio; no sync wrapper overhead. The only production-grade async Postgres driver for Python. |
| Alembic | `^1.18.4` | Schema migrations | Ships with SQLAlchemy org; handles `async_engine_from_config` for migrations on async engines. Standard choice whenever SQLAlchemy is used. |
| PostgreSQL | 15 or 16 | Relational persistence | Needed for signals, markets, resolution tracking. Already planned in project architecture. No pgvector extension required for this milestone. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx (existing) | `^0.27` | Discord webhook HTTP calls | Already installed; use `httpx.AsyncClient.post()` directly against the Discord webhook URL. No extra library needed — Discord webhooks are a single POST with JSON payload. |
| python-dotenv (existing) | `^1.2.1` | `.env` loading for local dev | Already installed via transitive dependency. |
| pytest-asyncio (existing) | `^0.23` | Async test support | Already installed. Use `asyncio_mode = "auto"` in pytest config. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Alembic CLI | Generate and apply migrations | Run `alembic revision --autogenerate` after model changes; run `alembic upgrade head` at startup. |
| Poetry | Dependency management | Already established. Add new packages with `poetry add`. |

---

## Installation

```bash
# Core new dependencies
poetry add "sqlalchemy[asyncio]>=2.0.46" "asyncpg>=0.31.0" "alembic>=1.18.4"
```

No additional libraries needed for:
- Discord alerting (use httpx directly — already installed)
- Scheduling/polling (use `asyncio.sleep` loops — already the existing pattern)

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| pgvector | Vector similarity search is only needed for cross-platform market matching (Kalshi), which is out of scope for this milestone | Plain PostgreSQL without the extension |
| sentence-transformers | Embedding generation is only needed for market matching | Not needed until Kalshi milestone |
| Anthropic SDK | LLM confirmation only needed for market matching | Not needed until Kalshi milestone |
| discord-webhook library | Adds an aiohttp transitive dependency; Discord webhooks are a single `POST` with a JSON body — httpx handles this in 3 lines | `httpx.AsyncClient.post(url, json={...})` |
| APScheduler | APScheduler 3.x is stable but overkill for two simple polling loops. APScheduler 4.x is pre-release and not production-safe as of February 2026 | `asyncio.sleep`-based `while True` loops with `asyncio.create_task()` — already the pattern in the codebase |
| Celery / Redis | Distributed task queue is many orders of magnitude more complexity than two in-process async loops | `asyncio.create_task()` |
| aiohttp | Project is standardized on httpx; mixing HTTP clients adds cognitive overhead | httpx (already installed) |

---

## Architecture Decisions

### Polling loops: `asyncio.sleep` over APScheduler

The existing `main.py` uses `asyncio.create_task()` and `asyncio.sleep()` loops. This is the right pattern for two fixed-interval loops. APScheduler 3.x is stable but adds boilerplate, a scheduler object, and trigger configuration for something that is `while True: await asyncio.sleep(N)`. APScheduler 4.0 is pre-release and explicitly not recommended for production (confirmed via project GitHub issues, Feb 2026).

Keep the existing pattern. Add drift-resistant timing if needed:
```python
async def polling_loop(interval_seconds: int):
    while True:
        start = asyncio.get_event_loop().time()
        await run_one_cycle()
        elapsed = asyncio.get_event_loop().time() - start
        await asyncio.sleep(max(0, interval_seconds - elapsed))
```

### Discord alerting: direct httpx

The Discord webhook API is a single `POST /webhooks/{id}/{token}` with a JSON body (`content`, `embeds`). No authentication headers, no state. Using `discord-webhook` or `dhooks` introduces dependencies (aiohttp) for what is three lines of code:

```python
async with httpx.AsyncClient() as client:
    await client.post(webhook_url, json={"content": message})
```

Keep it in `arbiter/notifications/discord.py` as a thin async class over httpx.

### SQLAlchemy async session pattern

Use `async_sessionmaker` (SQLAlchemy 2.0 style) rather than the older `sessionmaker` with a sync engine. The session should be a dependency passed into service functions, not a global:

```python
engine = create_async_engine("postgresql+asyncpg://...")
AsyncSession = async_sessionmaker(engine, expire_on_commit=False)

async with AsyncSession() as session:
    session.add(signal)
    await session.commit()
```

`expire_on_commit=False` is important for async — avoids lazy-loading after commit in an async context.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| asyncpg | psycopg3 (async) | If you need COPY protocol or advanced Postgres features not in asyncpg; psycopg3 async is production-ready but asyncpg has wider SQLAlchemy documentation coverage |
| `asyncio.sleep` loops | APScheduler 3.x | If you need cron-style scheduling (specific times of day), multiple independent triggers, or job persistence across restarts — none of which apply here |
| httpx direct | discord-webhook 1.4.1 | If you want embed formatting helpers, rate-limit retry logic, or will send to many webhooks — not needed for single-user alerting |
| SQLAlchemy 2.0 | Raw asyncpg queries | If query performance is the bottleneck and you need 45%+ throughput improvement (benchmarked). Not a concern at single-user polling scale. |

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| SQLAlchemy `^2.0.46` | asyncpg `^0.31.0` | Official supported combination; use `postgresql+asyncpg://` connection string |
| Alembic `^1.18.4` | SQLAlchemy `^2.0` | Alembic 1.x tracks SQLAlchemy 2.x; use `async_engine_from_config` for async migrations |
| asyncpg `^0.31.0` | Python 3.12 | Supports Python 3.9–3.14 per PyPI |
| SQLAlchemy `^2.0.46` | Python 3.12 | Supported; 2.1.0b1 available but beta-only |

---

## Sources

- [PyPI: SQLAlchemy 2.0.46](https://pypi.org/project/SQLAlchemy/) — current stable version confirmed
- [PyPI: asyncpg 0.31.0](https://pypi.org/project/asyncpg/) — current stable version confirmed (Nov 24, 2025)
- [PyPI: Alembic 1.18.4](https://pypi.org/project/alembic/) — current stable version confirmed (Feb 10, 2026)
- [PyPI: discord-webhook 1.4.1](https://pypi.org/project/discord-webhook/) — current version; async requires `[async]` extra
- [SQLAlchemy asyncio docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) — `create_async_engine`, `async_sessionmaker` patterns (HIGH confidence)
- [APScheduler GitHub issue #465](https://github.com/agronholm/apscheduler/issues/465) — APScheduler 4.0 pre-release, not production-safe (MEDIUM confidence)
- [APScheduler migration guide](https://apscheduler.readthedocs.io/en/master/migration.html) — 4.0 breaking changes confirmed
- WebSearch: asyncpg vs SQLAlchemy performance benchmarks 2026 (MEDIUM confidence — single source)

---

*Stack research for: Arbiter — signal detection milestone*
*Researched: 2026-02-22*
