# Project Research Summary

**Project:** Arbiter — Prediction Market Signal Detection
**Domain:** Async Python service — signal detection, persistence, and alerting
**Researched:** 2026-02-22
**Confidence:** MEDIUM (stack HIGH, architecture HIGH, features MEDIUM, pitfalls MEDIUM)

## Executive Summary

Arbiter is a signals-only prediction market tool for Polymarket. This milestone adds PostgreSQL persistence, longshot bias and time decay signal detectors, resolution tracking, and Discord alerting onto an existing Python 3.12 / asyncio / httpx codebase. The recommended approach is additive and conservative: three new dependencies (SQLAlchemy 2.0, asyncpg, Alembic), two async polling loops, and a registry-based detector pattern. Everything else — scheduling, HTTP clients for Discord, signal formatting — is handled by code already in the project.

The most important architectural constraint is that the schema must be designed before the detectors. Signal deduplication, resolution state (YES/NO/NA/DISPUTED), and price-at-signal storage all need to be in the database from day one. Retrofitting them later means data loss or a full schema migration that invalidates historical accuracy data — which is the primary output of this system. Build order: config → DB schema + migrations → extended Polymarket client → detectors → notifications → main loop.

The central risk is strategy validity, not engineering. Research (SSRN 2025) finds no general longshot bias on Polymarket — prices tend to track realized probabilities closely. The time decay strategy has stronger intuitive grounding but lacks Polymarket-specific validation. The system should be designed from day one to measure calibration, not assume edge. If signals fire at 85% win rate for 85%-priced markets, the strategy has no edge and the thresholds need adjustment. Resolution tracking and accuracy reporting are not optional reporting features — they are the mechanism by which the system validates its own hypotheses.

## Key Findings

### Recommended Stack

This milestone adds three packages to an already-solid base. SQLAlchemy 2.0 with asyncpg provides the async PostgreSQL layer; Alembic handles migrations. Everything else — Discord alerting, polling loops, HTTP — is handled by httpx and asyncio already in place. Do not add APScheduler (4.0 is pre-release; asyncio.sleep loops are sufficient), discord-webhook (httpx covers a Discord POST in three lines), or any of the Kalshi/matching libraries (pgvector, sentence-transformers, Anthropic SDK) which are explicitly out of scope for this milestone.

**Core technologies:**
- SQLAlchemy `^2.0.46`: async ORM via `create_async_engine` + `async_sessionmaker` — stable, well-documented, correct for this stack
- asyncpg `^0.31.0`: required PostgreSQL async driver for SQLAlchemy's asyncpg dialect — no sync wrapper overhead
- Alembic `^1.18.4`: schema migrations — ships with SQLAlchemy org, handles async engine config
- httpx (existing): Discord webhook delivery — single POST, no extra library warranted
- asyncio (stdlib): polling loop scheduling — `while True / asyncio.sleep()` is the existing pattern and the right one

**Critical version note:** Use `expire_on_commit=False` on the async session factory. Without it, SQLAlchemy will attempt lazy-loads after commit in an async context, causing errors.

### Expected Features

Signal detection and tracking divides cleanly into must-haves (without which the system produces nothing of value) and quality gates (without which the system produces noisy, misleading output). The distinction matters: noise kills usefulness faster than missing features.

**Must have (table stakes):**
- Signal storage table — without persistence, there's nothing to track or evaluate
- Longshot bias detector (75–95% yes_price window, liquidity + volume filters)
- Time decay detector (< 72h to expiry, 80–97% yes_price, indicating "no" is near-certain)
- Signal deduplication / cooldown per market per strategy — without this, Discord floods immediately
- Discord alert on new signal (question, strategy, direction, price, hours-to-expiry, link)
- Resolution detection in polling loop (detect `resolved=True`, determine outcome from `outcome_prices`)
- Resolution recording (update signal with outcome + `was_correct` bool)
- Performance report CLI — accuracy rate per strategy; minimum 10 resolved signals before displaying %

**Should have (quality gates, ship with or just after):**
- Minimum liquidity filter (`liquidityCLOB >= $1,000` for longshot, `>= $500` for time decay)
- Minimum volume filter (`volume >= $5,000` for longshot)
- Signal status state machine: `open | closed | resolved_correct | resolved_incorrect | resolved_na`
- N/A resolution handling — excluded from accuracy denominator, counted for coverage

**Defer (v2+):**
- Per-strategy accuracy trend (last-N window) — needs 30+ resolved signals to be meaningful
- Confidence intervals on accuracy rate — needs 50+ signals per strategy
- Strategy parameter auto-tuning
- Additional strategies (whale copy trading, calibration vs Metaculus)
- Alert fatigue management / batching beyond basic dedup

**Anti-features to explicitly exclude:**
- Historical backtesting: no official historical fill API exists; live tracking is the right model
- Continuous re-alerting: one signal per market per strategy until it resolves
- LLM confidence scoring: deterministic threshold checks don't benefit from LLM overhead
- Kelly criterion position sizing: execution is out of scope; sizing logic is premature

### Architecture Approach

The system is two concurrent asyncio tasks coordinated by `main.py`. Discovery (~5 min) fetches all active markets from Polymarket Gamma API and upserts metadata. Polling (~1 min) loads tracked markets, fetches fresh CLOB prices, runs the detector registry, stores signals, and checks for resolutions. A `DetectorRegistry` decouples the polling loop from knowledge of how many detectors exist. Detectors are pure synchronous functions — they receive a hydrated `Market` object and return `Signal | None`. The registry owns deduplication and DB writes. This keeps detectors trivially testable without asyncio fixtures.

**Major components:**
1. `config.py` — pydantic-settings, loads all thresholds and secrets; must be implemented first
2. `db/models.py` + `db/session.py` — SQLAlchemy ORM for markets/signals/price_snapshots, async session factory
3. `clients/polymarket.py` (extend) — add CLOB price fetching; discovery uses Gamma, polling uses CLOB
4. `detection/base.py` + `detection/longshot.py` + `detection/time_decay.py` + `detection/registry.py` — BaseDetector ABC, two concrete detectors, registry that runs all and deduplicates
5. `notifications/discord.py` — thin async wrapper over httpx; receives Signal, POSTs to webhook
6. `main.py` (rewrite) — wires two tasks, registers SIGTERM/SIGINT handlers, disposes engine on shutdown

**Key patterns:**
- Session-per-task: never share an `AsyncSession` across concurrent tasks; use `async_sessionmaker` as a factory
- Graceful shutdown: SIGTERM/SIGINT cancel tasks; loops catch `asyncio.CancelledError` and clean up in `finally`
- Detectors are sync: no async, no DB access; pure input/output, testable in isolation

### Critical Pitfalls

1. **Longshot bias may not exist on Polymarket** — SSRN 2025 finds prices track realized probabilities; build accuracy reporting from day one and measure calibration after 30+ resolutions; if 85%-priced markets resolve YES 85% of the time, there is no edge and thresholds must be rethought
2. **Signal deduplication missing from schema** — a market that meets detector criteria for 3 days fires thousands of Discord alerts; enforce `UNIQUE INDEX ON signals(market_id, strategy) WHERE resolved_at IS NULL` in the initial schema; this is a one-line schema decision with zero recovery cost if done early, high recovery cost if done late
3. **N/A and disputed resolutions corrupt accuracy stats** — UMA oracle can resolve as N/A or be disputed; store resolution as enum (`YES | NO | NA | DISPUTED | PENDING`), apply 24-hour grace period before scoring, exclude N/A from win-rate denominator
4. **Asyncio task swallowing exceptions silently** — an unhandled exception in `asyncio.create_task()` kills the loop silently; wrap every loop body in `try/except Exception` that logs and continues, not exits; consider a heartbeat Discord message every N hours
5. **Performance reporting schema that can't answer questions** — design schema to answer "what is strategy X's win rate over 90 days?" and "what was price at signal vs. resolution?" before writing any code; the `price_at_signal`, `resolved_at`, `was_correct`, and `resolution_outcome` columns are not optional

## Implications for Roadmap

The build has a hard dependency chain: schema before detectors, config before schema, client extension before detectors. Phases that violate this order waste work. Four phases align with that chain.

### Phase 1: Foundation (Config + DB + Polymarket client extension)

**Rationale:** Config is required by every other component. DB schema must be finalized before any detector code can be tested end-to-end — the dedup index, resolution enum, and price_at_signal column need to exist before a single signal is written. Polymarket CLOB price fetching is needed by the polling loop.

**Delivers:** Running PostgreSQL with migrated schema, config loading from .env, CLOB price fetching

**Addresses:** Signal storage (table stakes), structured config (PROJECT.md requirement), CLOB prices for polling

**Avoids:** Schema pitfalls (dedup index, N/A enum, price_at_signal) — all must be correct in migration 001

**Research flag:** Standard patterns; skip research phase. SQLAlchemy async + Alembic are well-documented. CLOB API auth requirement (API key for reads) is documented and already flagged in codebase CONCERNS.md.

### Phase 2: Signal Detection (DetectorRegistry + LongshotBiasDetector + TimeDecayDetector)

**Rationale:** Detectors depend on the DB schema (for dedup queries) and the extended Polymarket client (for fresh CLOB prices). This phase should not begin until Phase 1 is tested and migrations are applied.

**Delivers:** Two working detectors integrated into the polling loop, signals written to DB, deduplication enforced at the DB level

**Uses:** `BaseDetector` ABC pattern, `DetectorRegistry`, async session factory (session-per-task pattern)

**Implements:** Detection layer (`detection/base.py`, `detection/longshot.py`, `detection/time_decay.py`, `detection/registry.py`)

**Avoids:** Signals-during-discovery anti-pattern (detectors only run in polling loop, not discovery loop); hardcoded thresholds (all in config); re-alerting anti-pattern (dedup index in DB prevents insert, not just application-layer check)

**Research flag:** Signal threshold calibration (75–95% for longshot, 72h/80–97% for time decay) is MEDIUM confidence — treat as starting point. Do not invest in tuning until 30+ resolved signals exist.

### Phase 3: Notifications + Resolution Tracking

**Rationale:** Discord alerting can be built in parallel with Phase 2 but must complete before the polling loop goes live. Resolution tracking shares the polling loop and must be added before the first market resolves (otherwise signals are never scored).

**Delivers:** Discord alerts on new signals, resolution detection in polling loop, signal accuracy recorded in DB

**Uses:** `DiscordNotifier` over httpx, resolution state machine in polling loop, 24-hour grace period before scoring

**Avoids:** N/A resolution corrupting stats (enum + grace period), alert burst rate limit (Discord: 30 msg/min — queue if simultaneous signals), silent exception swallowing (wrap every polling body in try/except)

**Research flag:** Discord rate limiting at burst — simulate 10 simultaneous signals in tests before shipping. Resolution state machine (`closed: true` vs `resolved: true` are distinct Polymarket states) needs explicit handling; add integration test.

### Phase 4: Reporting + Operational Hardening

**Rationale:** Accuracy reporting requires resolved signals, so it comes last. Operational hardening (loop exception handling, heartbeat, graceful shutdown, connection pool monitoring) is typically underestimated and should be formalized before declaring the system production-ready.

**Delivers:** CLI performance report (accuracy per strategy), graceful SIGTERM shutdown, exception-resilient polling loops, price_snapshots pruning

**Uses:** SQL aggregates on signals table, asyncio signal handlers, `asyncio.gather(*tasks, return_exceptions=True)`

**Avoids:** Reporting before sufficient data (10+ resolved signals gate), silent loop death (heartbeat or structured logging), connection leaks (`async with session_factory()` enforced everywhere)

**Research flag:** Standard patterns for all of this. No additional research needed.

### Phase Ordering Rationale

- Config and schema are Phase 1 because every other component depends on them; fixing schema after signals exist means data loss or complex migration
- Detectors are Phase 2 because they need both the schema (dedup queries) and the CLOB client (fresh prices); testing detectors without these is hollow
- Notifications and resolution are Phase 3 because they integrate at the polling-loop layer, not the schema layer, and can be developed once the polling loop works
- Reporting is last because it is read-only against accumulated data; it cannot be meaningfully tested until signals and resolutions exist
- This order also front-loads the highest-risk schema decisions (dedup, N/A, price_at_signal) where they can be fixed cheaply

### Research Flags

Needs deeper research or explicit validation during planning:
- **Phase 2:** Signal threshold calibration — the 75–95% longshot window and 72h/80–97% time decay parameters are starting points derived from academic literature and community practice, not validated against Polymarket data. Plan to measure and adjust after 30+ resolutions.
- **Phase 3:** Polymarket resolution state machine — `closed` and `resolved` are distinct fields; N/A and disputed markets behave unexpectedly. Review Polymarket Help docs on UMA oracle resolution before implementing the resolution tracker.

Standard patterns (skip research phase):
- **Phase 1:** SQLAlchemy 2.0 async + Alembic is well-documented with clear official examples
- **Phase 4:** Graceful asyncio shutdown and CLI reporting are well-established Python patterns

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against PyPI; SQLAlchemy asyncio patterns from official docs |
| Architecture | HIGH | Standard async service patterns; concrete examples from official SQLAlchemy and Python asyncio docs |
| Features | MEDIUM | Feature list well-defined; threshold parameters (75–95%, 72h) derived from academic literature + community practice, not Polymarket-specific experiments |
| Pitfalls | MEDIUM | API behavior from official docs; strategy pitfalls grounded in SSRN 2025 paper; async patterns from Python official docs and GitHub issues |

**Overall confidence:** MEDIUM

### Gaps to Address

- **Longshot bias edge on Polymarket:** SSRN 2025 explicitly finds no general longshot bias. The strategy may produce signals with calibrated (not alpha-generating) accuracy. Resolution tracking is the validation mechanism — build it before the first signal fires, not after.
- **Time decay threshold validation:** The 72-hour window and 80% yes_price floor come from options theta literature and one community example, not a systematic Polymarket study. Treat as a hypothesis, not a validated edge.
- **CLOB API auth scope:** CLOB API requires authentication even for read operations. Confirm the existing API key setup covers price polling before Phase 2 begins.
- **Polymarket API pagination:** Gamma API returns max 100 markets per call. Discovery loop must paginate with `offset`. Verify the existing client handles this; CONCERNS.md indicates it may not.

## Sources

### Primary (HIGH confidence)
- [SQLAlchemy Asyncio Docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) — async_sessionmaker, expire_on_commit=False, session-per-task pattern
- [Polymarket Developer Docs](https://docs.polymarket.com) — API field definitions, rate limits, CLOB auth
- [Polymarket GitHub: agents/polymarket/gamma.py](https://github.com/Polymarket/agents/blob/main/agents/polymarket/gamma.py) — first-party field reference
- [Snowberg & Wolfers (2010), NBER WP w15923](https://www.nber.org/system/files/working_papers/w15923/w15923.pdf) — favorite-longshot bias in betting markets (academic basis)
- [UCD Economics WP2025_19](https://www.ucd.ie/economics/t4media/WP2025_19.pdf) — Kalshi prediction market bias study, volume sensitivity

### Secondary (MEDIUM confidence)
- [SSRN 2025: Exploring Decentralized Prediction Markets](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5910522) — no general longshot bias found on Polymarket; critical strategy validity caveat
- [Polymarket Help: How Markets Are Resolved](https://help.polymarket.com/en/articles/13364518-how-are-prediction-markets-resolved) — UMA oracle, 2-hour dispute window
- [QuantPedia: Systematic Edges in Prediction Markets](https://quantpedia.com/systematic-edges-in-prediction-markets/) — bias strongest in low-volume markets
- [PyPI: SQLAlchemy 2.0.46, asyncpg 0.31.0, Alembic 1.18.4](https://pypi.org) — version verification

### Tertiary (LOW confidence)
- [DataWallet: Top 10 Polymarket Trading Strategies](https://www.datawallet.com/crypto/top-polymarket-trading-strategies) — time decay example (single source, no systematic study)
- [Polymarket py-clob-client GitHub issues](https://github.com/Polymarket/py-clob-client/issues) — rate limit behavior, resolved market data gaps
- APScheduler 4.0 pre-release status — inferred from GitHub issues; verify before recommending against it in future milestones

---
*Research completed: 2026-02-22*
*Ready for roadmap: yes*
