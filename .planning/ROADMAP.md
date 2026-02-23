# Roadmap: Arbiter

## Overview

Arbiter goes from a bare Polymarket API client to a live, self-validating signal detection service in five phases. The build order follows a hard dependency chain: config and DB schema must exist before any other component can be built or tested end-to-end. Polling loops come before detectors. Notifications and resolution tracking share the polling loop and ship together. Reporting is last because it reads from accumulated signal data that cannot exist until everything above it is running.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation** - Config system, DB schema + migrations, Gamma API reliability
- [ ] **Phase 2: Data Collection** - CLOB client, market discovery loop, price polling loop
- [ ] **Phase 3: Signal Detection** - Detector framework, longshot bias + time decay detectors, signal storage
- [ ] **Phase 4: Resolution + Notifications** - Discord alerts, resolution tracking, signal state machine
- [ ] **Phase 5: Reporting + Hardening** - CLI accuracy report, graceful shutdown, exception resilience

## Phase Details

### Phase 1: Foundation
**Goal**: The system can start, load all config from environment, connect to PostgreSQL, and run migrations — everything downstream can rely on these primitives existing.
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, CLIENT-01, CLIENT-03
**Success Criteria** (what must be TRUE):
  1. Running the service with a missing required env var prints a clear error and exits immediately — no silent misconfiguration
  2. `alembic upgrade head` applies the initial migration cleanly on a fresh PostgreSQL instance, creating the markets, signals, and price_snapshots tables with all indexes including the dedup partial unique index
  3. The Gamma API client fetches all active Polymarket markets with pagination and returns typed model objects — verified against the live API
  4. Transient API errors (network timeout, 5xx) trigger retry logic rather than crashing
**Plans**: TBD

### Phase 2: Data Collection
**Goal**: Two concurrent async loops run continuously — discovery upserts market metadata every 5 minutes, polling fetches CLOB prices every 1 minute — and both survive transient failures without crashing.
**Depends on**: Phase 1
**Requirements**: INFRA-04, INFRA-05, INFRA-06, INFRA-07, CLIENT-02
**Success Criteria** (what must be TRUE):
  1. After starting the service, the markets table is populated with active Polymarket markets within 5 minutes
  2. After each polling tick, fresh CLOB bid/ask prices are stored in price_snapshots for all tracked markets
  3. When the Polymarket API returns an error during a polling tick, the loop logs the error and continues on the next tick — it does not exit
  4. Each discovery and polling cycle emits a heartbeat log line, so silence in logs is detectable
**Plans**: TBD

### Phase 3: Signal Detection
**Goal**: The polling loop runs two signal detectors on every tick, persists signals to the database with full deduplication, and exactly one open signal per market per strategy is ever active at a time.
**Depends on**: Phase 2
**Requirements**: DETECT-01, DETECT-02, DETECT-03, DETECT-04, STORE-01, STORE-02, STORE-03
**Success Criteria** (what must be TRUE):
  1. A market priced between 0.75 and 0.95 with sufficient liquidity triggers a longshot bias signal — visible in the signals table — exactly once while it stays in that range
  2. A market within 72 hours of expiry priced between 0.80 and 0.97 triggers a time decay signal exactly once while the condition holds
  3. Keeping the service running while a market stays in detector range for 24+ hours produces exactly one active signal row, not duplicates — enforced by the dedup index at the database level
  4. Detector thresholds (price windows, liquidity minimums, cooldown durations) can be changed via environment variables without modifying code
  5. Each detector can be unit-tested synchronously with a mock market object and returns a signal or None — no asyncio required to test the detection logic
**Plans**: TBD

### Phase 4: Resolution + Notifications
**Goal**: Every new signal fires a Discord alert immediately, and when a market resolves the system scores all open signals for that market as correct or incorrect — building the accuracy dataset automatically.
**Depends on**: Phase 3
**Requirements**: NOTIFY-01, NOTIFY-02, TRACK-01, TRACK-02, TRACK-03, TRACK-04
**Success Criteria** (what must be TRUE):
  1. When a detector fires a new signal, a Discord message appears in the configured channel within one polling cycle, containing the market question, strategy, recommendation (BUY YES/NO), price, hours to expiry, liquidity, and a link to the market
  2. The same market+strategy combination does not produce a second Discord alert while its signal is open — silence is correct, not a bug
  3. When a market transitions to resolved in Polymarket, the polling loop sets was_correct on all open signals for that market within one polling cycle
  4. Markets that resolve as N/A (UMA oracle void) set signal status to void and those signals are excluded from accuracy calculations
  5. Markets that close without resolving within a reasonable window transition their open signals to expired rather than leaving them indefinitely active
**Plans**: TBD

### Phase 5: Reporting + Hardening
**Goal**: The `arbiter report` command shows per-strategy accuracy from live data, and the service handles SIGTERM gracefully and survives any single-component failure without dying.
**Depends on**: Phase 4
**Requirements**: REPORT-01, REPORT-02, REPORT-03
**Success Criteria** (what must be TRUE):
  1. Running `arbiter report` prints per-strategy accuracy: total signals, resolved count, correct count, accuracy percentage — with accuracy suppressed and labeled "insufficient data" until 10+ resolved signals exist for that strategy
  2. The report shows a count of currently active (unresolved) signals per strategy
  3. Sending SIGTERM to the running service causes it to finish its current DB operation, close connections, and exit cleanly — no hanging processes or connection leaks
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 0/TBD | Not started | - |
| 2. Data Collection | 0/TBD | Not started | - |
| 3. Signal Detection | 0/TBD | Not started | - |
| 4. Resolution + Notifications | 0/TBD | Not started | - |
| 5. Reporting + Hardening | 0/TBD | Not started | - |
