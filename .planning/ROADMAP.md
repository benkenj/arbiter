# Roadmap: Arbiter

## Overview

Arbiter goes from a bare Polymarket API client to a live whale copy-trading alert service in five phases. The build order follows a hard dependency chain: infrastructure before data, data before scoring, scoring before monitoring, monitoring before alerts. Trade execution is a future phase added after the alert system is validated.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation** - Config system, DB schema + migrations, Gamma API reliability
- [x] **Phase 2: Data Collection** - Schema migration (drop signals/price_snapshots, add trades/wallets/positions), market discovery loop with configurable filters (completed 2026-03-02)
- [ ] **Phase 3: Trade History** - Ingest historical CLOB trades per market, build wallet activity database
- [ ] **Phase 4: Whale Identification** - Score wallets by win rate + volume, maintain configurable whale list
- [ ] **Phase 5: Price Impact Analysis** - For each ingested trade, capture market price at +1min, +5min, +30min, +1hr to measure how trades move markets
- [ ] **Phase 6: Whale Monitoring + Alerts** - Poll whale positions, Discord alert on new opens

## Phase Details

### Phase 1: Foundation
**Goal**: The system can start, load all config from environment, connect to PostgreSQL, and run migrations — everything downstream can rely on these primitives existing.
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, CLIENT-01, CLIENT-03
**Success Criteria** (what must be TRUE):
  1. Running the service with a missing required env var prints a clear error and exits immediately — no silent misconfiguration
  2. `alembic upgrade head` applies the initial migration cleanly on a fresh PostgreSQL instance
  3. The Gamma API client fetches all active Polymarket markets with pagination and returns typed model objects — verified against the live API
  4. Transient API errors (network timeout, 5xx) trigger retry logic rather than crashing
**Plans**: 4 plans

Plans:
- [x] 01-01-PLAN.md — Config system (pydantic-settings, .env.example, docker-compose, dependencies)
- [x] 01-02-PLAN.md — DB layer (SQLAlchemy ORM models, async session factory, Alembic migrations)
- [x] 01-03-PLAN.md — Gamma API client hardening (pagination, retry, parse fix)
- [ ] 01-04-PLAN.md — Entry point rewrite (argparse, --check flag, startup health checks, logging)

### Phase 2: Data Collection
**Goal**: Schema is migrated to the whale-tracking model, and a continuous market discovery loop upserts filtered Polymarket market metadata every 5 minutes, surviving transient failures without crashing.
**Depends on**: Phase 1
**Requirements**: INFRA-04, INFRA-06, INFRA-07, FILTER-01, FILTER-02, FILTER-03
**Success Criteria** (what must be TRUE):
  1. `alembic upgrade head` drops the `signals` and `price_snapshots` tables and creates `trades`, `wallets`, and `positions` tables cleanly
  2. After starting the service, the markets table is populated with active binary Polymarket markets above configured volume/liquidity thresholds within 5 minutes
  3. When the Polymarket API returns an error during a discovery cycle, the loop logs the error and continues on the next tick — it does not exit
  4. Each discovery cycle emits a heartbeat log line, so silence in logs is detectable
**Plans**: 2 plans

Plans:
- [x] 02-01-PLAN.md — Schema migration 002 (drop Signal/PriceSnapshot, add Trade/Wallet/Position) + ORM model update
- [ ] 02-02-PLAN.md — Market filter config fields + discovery loop + main.py wiring

### Phase 3: Trade History
**Goal**: The system ingests historical trade activity from Polymarket's CLOB API for all tracked markets, incrementally (only fetching new trades after the last ingestion timestamp), and stores wallet-level trade records suitable for win rate and volume computation.
**Depends on**: Phase 2
**Requirements**: CLIENT-04, HIST-01, HIST-02, HIST-03
**Success Criteria** (what must be TRUE):
  1. After running trade ingestion, the trades table contains records with wallet_address, market_id, side, size, price, and timestamp for all tracked markets
  2. Re-running ingestion on a market with existing records only fetches trades newer than the last stored timestamp — no duplicates
  3. Markets that have resolved have their trade outcome (correct/incorrect) derivable from stored data — resolution outcome is linkable to the wallet's position
  4. Ingestion failures for a single market log the error and continue processing other markets — one bad market does not block the rest
**Plans**: 3 plans

Plans:
- [ ] 03-01-PLAN.md — CLOB Data API client extension (Trade model, _fetch_clob_page, get_trades_for_market) + ingestion config fields
- [ ] 03-02-PLAN.md — Alembic migration 003 (add outcome column to trades) + Trade ORM model update
- [ ] 03-03-PLAN.md — Ingestion module (arbiter/ingestion/trades.py) + main.py wiring

### Phase 4: Whale Identification
**Goal**: A scoring job runs periodically, ranks all wallets in the trades table by a composite score of win rate and volume, and maintains a `wallets` table with configurable thresholds determining which wallets are classified as tracked whales.
**Depends on**: Phase 3
**Requirements**: WHALE-01, WHALE-02, WHALE-03, WHALE-04, WHALE-05, CLI-01, CLI-02, CLI-03
**Success Criteria** (what must be TRUE):
  1. After scoring runs, the wallets table contains win_rate, total_volume, total_trades, and score for every wallet with recorded trades
  2. Wallets with fewer than `WHALE_MIN_TRADES` resolved trades are excluded from classification (small sample bias)
  3. Wallets meeting both `WHALE_MIN_WIN_RATE` and `WHALE_MIN_VOLUME` thresholds have `is_tracked = true`
  4. All thresholds (`WHALE_MIN_TRADES`, `WHALE_MIN_WIN_RATE`, `WHALE_MIN_VOLUME`) are configurable via environment variables
  5. Scoring can be re-run without duplicating records — it upserts, not inserts
  6. `arbiter whales` prints tracked whales sorted by score with win rate, volume, and trade count
  7. `arbiter whales --all` includes below-threshold wallets for threshold tuning
  8. `arbiter whales <address>` shows full stats for a single wallet
**Plans**: TBD

### Phase 5: Price Impact Analysis
**Goal**: For every trade ingested in Phase 3, the system captures the market price at four intervals after execution (+1min, +5min, +30min, +1hr), enabling analysis of how individual trades move markets and which wallets consistently enter before price moves.
**Depends on**: Phase 3
**Requirements**: IMPACT-01, IMPACT-02, IMPACT-03, IMPACT-04
**Success Criteria** (what must be TRUE):
  1. For each trade in the trades table, price impact records exist (or are marked unavailable) for all four intervals: +1min, +5min, +30min, +1hr
  2. `arbiter whales <address>` shows price movement data alongside trade history — how often did the market move in their direction at each interval
  3. Trades where historical price data is unavailable are marked as such rather than silently skipped
  4. Price impact processing runs as a background job that catches up on unprocessed trades without reprocessing already-captured intervals
**Plans**: TBD

### Phase 6: Whale Monitoring + Alerts
**Goal**: The system polls current open positions for all tracked whale wallets at a configurable interval, detects when a whale opens a new position not seen in the previous poll, and fires a Discord alert containing wallet, market, side, size, and entry price.
**Depends on**: Phase 4
**Requirements**: MONITOR-01, MONITOR-02, MONITOR-03, NOTIFY-01, NOTIFY-02, NOTIFY-03
**Success Criteria** (what must be TRUE):
  1. When a tracked whale opens a new position on Polymarket, a Discord alert appears in the configured channel within one monitoring cycle
  2. The alert contains: abbreviated wallet address, market question, side (YES/NO), size, entry price, and a link to the market
  3. The same whale+market position does not produce a second Discord alert if no new position was opened (idempotent polling)
  4. When the monitoring loop fails to fetch a wallet's positions, it logs the error and continues to the next wallet — one failure does not stop the cycle
  5. Monitoring interval is configurable via `WHALE_POLL_INTERVAL_SECONDS`
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 3/4 | In Progress | - |
| 2. Data Collection | 2/2 | Complete   | 2026-03-02 |
| 3. Trade History | 0/3 | Not started | - |
| 4. Whale Identification | 0/TBD | Not started | - |
| 5. Price Impact Analysis | 0/TBD | Not started | - |
| 6. Whale Monitoring + Alerts | 0/TBD | Not started | - |
