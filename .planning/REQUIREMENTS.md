# Requirements: Arbiter

**Defined:** 2026-02-22
**Revised:** 2026-02-25 — pivoted from signal detection to whale copy trading
**Core Value:** Alert when high-performing Polymarket traders open new positions, enabling copy trading decisions.

## v1 Requirements

### Infrastructure

- [x] **INFRA-01**: System loads all configuration from environment variables with validation at startup
- [x] **INFRA-02**: System fails fast with a clear error message if any required config is missing
- [x] **INFRA-03**: PostgreSQL database schema is managed with Alembic migrations
- [x] **INFRA-04**: System runs a continuous market discovery loop (every ~5 minutes) that fetches active Polymarket markets matching configured filters and upserts them to the DB
- [x] **INFRA-06**: Discovery loop recovers from transient errors (API failures, DB errors) without crashing the process
- [x] **INFRA-07**: Discovery loop emits a heartbeat log line each cycle so silence is detectable

### API Clients

- [x] **CLIENT-01**: Polymarket Gamma API client reliably fetches all active markets with pagination
- [x] **CLIENT-03**: API clients handle rate limits and transient errors with retry logic
- [x] **CLIENT-04**: Polymarket CLOB API client fetches trade history for a given market, with a `since` timestamp for incremental fetching

### Market Filters

- [x] **FILTER-01**: Discovery applies a configurable binary-only filter (`MARKET_BINARY_ONLY`, default true) — only yes/no outcome markets are tracked
- [x] **FILTER-02**: Discovery applies a configurable minimum volume filter (`MARKET_MIN_VOLUME` in USDC, default 0) — markets below threshold are skipped
- [x] **FILTER-03**: Discovery applies a configurable minimum liquidity filter (`MARKET_MIN_LIQUIDITY` in USDC, default 0) — markets below threshold are skipped

### Trade History Ingestion

- [x] **HIST-01**: Ingestion fetches all trades for each tracked market from the Polymarket CLOB API and stores them with wallet_address, market_id, side, size, price, and timestamp
- [x] **HIST-02**: Ingestion is incremental — each market stores a last_ingested_at timestamp, and subsequent runs only fetch trades newer than that timestamp
- [x] **HIST-03**: A single market ingestion failure logs the error and continues processing remaining markets — partial failure is non-fatal

### Whale Identification

- [x] **WHALE-01**: Scoring computes win_rate (correct resolved trades / total resolved trades) and total_volume for each wallet with trade history
- [x] **WHALE-02**: Wallets with fewer than `WHALE_MIN_TRADES` resolved trades are excluded from whale classification (configurable, default 10)
- [x] **WHALE-03**: Wallets meeting both `WHALE_MIN_WIN_RATE` (configurable, default 0.6) and `WHALE_MIN_VOLUME` (configurable, default 1000 USDC) are flagged `is_tracked = true`
- [x] **WHALE-04**: Scoring upserts the wallets table — re-running does not duplicate records
- [x] **WHALE-05**: Scoring runs on a configurable periodic interval (`WHALE_SCORE_INTERVAL_SECONDS`)

### CLI

- [ ] **CLI-01**: `arbiter whales` command displays the current tracked whale list: wallet address (abbreviated), win rate, total volume, total trades, score — sorted by score descending
- [ ] **CLI-02**: `arbiter whales --all` includes non-tracked wallets (below threshold) so the user can inspect borderline cases and tune thresholds
- [ ] **CLI-03**: `arbiter whales <address>` shows full detail for a single wallet: all stats plus recent trade history summary

### Price Impact Analysis

- [ ] **IMPACT-01**: For each trade record, the system fetches and stores the market price at four intervals after the trade timestamp: +1min, +5min, +30min, +1hr
- [ ] **IMPACT-02**: Price impact records are stored in a `trade_price_impacts` table: trade_id, interval_minutes, price, captured_at, available (bool)
- [ ] **IMPACT-03**: Trades where historical price data is unavailable (API gap, market closed) are marked `available=false` rather than left unprocessed
- [ ] **IMPACT-04**: Price impact processing is idempotent — re-running does not create duplicate records for already-captured intervals

### Whale Monitoring

- [ ] **MONITOR-01**: System polls current open positions for all `is_tracked = true` wallets on a configurable interval (`WHALE_POLL_INTERVAL_SECONDS`)
- [ ] **MONITOR-02**: System detects when a whale opens a new position not present in the previous poll (by diffing against stored positions)
- [ ] **MONITOR-03**: A single wallet position fetch failure logs the error and continues to the next wallet — one failure does not stop the cycle

### Notifications

- [ ] **NOTIFY-01**: System sends a Discord alert when a tracked whale opens a new position, containing: abbreviated wallet address, market question, side (YES/NO), position size, entry price, and a link to the market
- [ ] **NOTIFY-02**: Alert deduplication — the same whale+market position does not produce a second Discord alert within a configurable window
- [ ] **NOTIFY-03**: Discord alerts are sent via webhook — no bot token or OAuth required

## v2 Requirements

### Trade Execution

- **EXEC-01**: When a whale alert fires, system can optionally place a copy trade on Polymarket via the order API (requires `EXECUTION_ENABLED=true`)
- **EXEC-02**: Position sizing is configurable (`COPY_TRADE_USDC_SIZE`) — a fixed USDC amount per trade, not proportional to whale size
- **EXEC-03**: Execution result (filled, partial, failed) is logged and reported in the Discord alert
- **EXEC-04**: Execution is gated on a maximum per-trade and per-day spend limit to prevent runaway trading

### Whale Intelligence

- **INTEL-01**: Category-scoped whale identification — track whales who specialize in a specific market category (politics, sports, crypto)
- **INTEL-02**: ROI-weighted scoring — weight win rate by average return per trade, not just correct/incorrect
- **INTEL-03**: Recency weighting — more recent trades count more in the score than older ones

### Infrastructure

- **INFRA-V2-01**: Structured JSON logging for production observability
- **INFRA-V2-02**: Docker/containerization for consistent deployment

## Out of Scope (v1)

| Feature | Reason |
|---------|--------|
| Trade execution | Validate alert quality before automating money |
| Kalshi integration | No trading access; deferred until available |
| Event-driven positioning | Higher complexity; much later phase |
| Probability trading / mispriced markets | Requires reliable calibration data; deferred |
| Historical backtesting | No official Polymarket bulk history API |
| LLM-based market analysis | Expensive; deterministic scoring is sufficient for v1 |
| Kelly criterion / position sizing | No execution = no positions to size |
| Portfolio view | No execution = no portfolio |
| Price snapshot polling | Not needed for whale copy trading; add back if a future phase requires current prices |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Complete |
| INFRA-02 | Phase 1 | Complete |
| INFRA-03 | Phase 1 | Complete |
| INFRA-04 | Phase 2 | Complete |
| INFRA-06 | Phase 2 | Complete |
| INFRA-07 | Phase 2 | Complete |
| CLIENT-01 | Phase 1 | Complete |
| CLIENT-03 | Phase 1 | Complete |
| CLIENT-04 | Phase 3 | Complete |
| FILTER-01 | Phase 2 | Complete |
| FILTER-02 | Phase 2 | Complete |
| FILTER-03 | Phase 2 | Complete |
| HIST-01 | Phase 3 | Complete |
| HIST-02 | Phase 3 | Complete |
| HIST-03 | Phase 3 | Complete |
| WHALE-01 | Phase 4 | Complete |
| WHALE-02 | Phase 4 | Complete |
| WHALE-03 | Phase 4 | Complete |
| WHALE-04 | Phase 4 | Complete |
| WHALE-05 | Phase 4 | Complete |
| CLI-01 | Phase 4 | Pending |
| CLI-02 | Phase 4 | Pending |
| CLI-03 | Phase 4 | Pending |
| IMPACT-01 | Phase 5 | Pending |
| IMPACT-02 | Phase 5 | Pending |
| IMPACT-03 | Phase 5 | Pending |
| IMPACT-04 | Phase 5 | Pending |
| MONITOR-01 | Phase 6 | Pending |
| MONITOR-02 | Phase 6 | Pending |
| MONITOR-03 | Phase 6 | Pending |
| NOTIFY-01 | Phase 6 | Pending |
| NOTIFY-02 | Phase 6 | Pending |
| NOTIFY-03 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 33 total
- Mapped to phases: 28
- Unmapped: 0

---
*Requirements defined: 2026-02-22*
*Last updated: 2026-02-25 — pivoted to whale copy trading*
