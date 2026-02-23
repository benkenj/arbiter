# Requirements: Arbiter

**Defined:** 2026-02-22
**Core Value:** Surface profitable trading signals on Polymarket with enough accuracy to be worth acting on.

## v1 Requirements

### Infrastructure

- [x] **INFRA-01**: System loads all configuration (DB URL, API keys, Discord webhook, detection thresholds) from environment variables with validation at startup
- [x] **INFRA-02**: System fails fast with a clear error message if any required config is missing
- [ ] **INFRA-03**: PostgreSQL database schema is managed with Alembic migrations (tables: markets, signals, price_snapshots)
- [ ] **INFRA-04**: System runs a continuous market discovery loop (every ~5 minutes) that fetches all active Polymarket markets and stores new ones
- [ ] **INFRA-05**: System runs a continuous price polling loop (every ~1 minute) that fetches current prices for tracked markets and drives signal detection
- [ ] **INFRA-06**: Polling loops recover from transient errors (API failures, DB errors) without crashing the process
- [ ] **INFRA-07**: Polling loops emit a heartbeat log line each cycle so silence is detectable

### API Clients

- [x] **CLIENT-01**: Polymarket Gamma API client reliably fetches all active markets with pagination (question, end_date, resolved status, outcome_prices, liquidityCLOB)
- [ ] **CLIENT-02**: Polymarket CLOB API client fetches current best bid/ask prices and order book liquidity for given market IDs
- [x] **CLIENT-03**: Both API clients handle rate limits and transient errors with retry logic

### Signal Detection

- [ ] **DETECT-01**: Longshot bias detector fires a signal when a market's yes_price is within a configurable window (default 0.75–0.95), liquidity exceeds a configurable threshold (default 1000 USDC), and no signal has fired for this market+strategy within a configurable cooldown (default 24h)
- [ ] **DETECT-02**: Time decay detector fires a signal when a market's hours_to_expiry is within a configurable window (default ≤72h), yes_price is within a configurable window (default 0.80–0.97), liquidity exceeds a configurable threshold (default 500 USDC), and no signal has fired for this market+strategy within a configurable cooldown (default 12h)
- [ ] **DETECT-03**: All detection thresholds (price windows, liquidity minimums, cooldown durations) are configurable via environment variables, not hardcoded
- [ ] **DETECT-04**: Detectors are structured as independent, synchronous, unit-testable components that receive a market object and return a signal or nothing

### Signal Storage

- [ ] **STORE-01**: Each fired signal is persisted with: market_id, market_question (cached), strategy, signal_direction (yes/no), signal_price, hours_to_expiry, liquidity_at_signal, status, fired_at
- [ ] **STORE-02**: Signal status follows a full state machine: active → resolved_correct / resolved_incorrect / expired / void
- [ ] **STORE-03**: Database enforces one open (active) signal per market+strategy combination (partial unique index)

### Resolution Tracking

- [ ] **TRACK-01**: Polling loop detects when a tracked market transitions to resolved=True and closed=True
- [ ] **TRACK-02**: On resolution, system determines the winning side from outcome_prices and records resolution_outcome, resolved_at, and correct (bool) on all active signals for that market
- [ ] **TRACK-03**: N/A resolutions (void markets) set signal status to void and are excluded from accuracy calculations
- [ ] **TRACK-04**: Markets that close without resolving (no resolution within reasonable window after end_date) transition active signals to expired

### Notifications

- [ ] **NOTIFY-01**: System sends a Discord alert when a new signal fires, containing: market question, strategy name, BUY YES/NO recommendation, price at signal time, hours to expiry, liquidity, and a link to the Polymarket market
- [ ] **NOTIFY-02**: Duplicate signals are suppressed (one alert per market+strategy per cooldown window)

### Reporting

- [ ] **REPORT-01**: `arbiter report` CLI command displays per-strategy accuracy: total signals, resolved count, correct count, accuracy percentage
- [ ] **REPORT-02**: Accuracy percentage is suppressed (shows "insufficient data") until at least 10 resolved signals exist for a strategy
- [ ] **REPORT-03**: Report includes a count of currently active (unresolved) signals per strategy

## v2 Requirements

### Enhanced Reporting

- **REPT2-01**: Per-strategy accuracy trend over last N resolved signals (not just all-time)
- **REPT2-02**: Mean hours_to_expiry at signal time per strategy (shows if time_decay fires too early/late)
- **REPT2-03**: Confidence intervals on accuracy rates (requires 50+ resolved signals)

### Signal Quality

- **QUAL-01**: Alert fatigue management — rate-limit Discord messages if many signals fire in one polling cycle
- **QUAL-02**: Strategy parameter auto-tuning suggestions based on accuracy data

### Additional Strategies

- **STRAT-01**: Whale copy trading — detect and alert when high-ROI Polymarket traders enter new positions
- **STRAT-02**: Calibration arbitrage — compare Polymarket prices against Metaculus/Good Judgment forecasts and alert on large disagreements

### Infrastructure

- **INFRA-V2-01**: Structured JSON logging for production observability
- **INFRA-V2-02**: Docker/containerization for consistent deployment

## Out of Scope

| Feature | Reason |
|---------|--------|
| Trade execution | Validate edge before automating money. Signals-only for now. |
| Kalshi integration | Polymarket-only for v1; Kalshi deferred. Arb execution requires dual-funded accounts and latency we can't achieve with REST polling. |
| Historical backtesting | No official Polymarket bulk history API. Live tracking starting from now is the validation method. |
| LLM-based signal evaluation | Expensive per-signal; strategies are deterministic threshold checks that don't need LLM confirmation |
| Kelly criterion / position sizing | No execution = no positions to size |
| Continuous re-alerting on active signals | Creates noise; trains user to ignore alerts |
| Multi-market portfolio view | No execution = no portfolio |
| Resolution criteria edge trading | Interesting long-term; too complex for v1 |
| Chatbot / agent interface | Far future |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Complete |
| INFRA-02 | Phase 1 | Complete |
| INFRA-03 | Phase 1 | Pending |
| INFRA-04 | Phase 2 | Pending |
| INFRA-05 | Phase 2 | Pending |
| INFRA-06 | Phase 2 | Pending |
| INFRA-07 | Phase 2 | Pending |
| CLIENT-01 | Phase 1 | Complete |
| CLIENT-02 | Phase 2 | Pending |
| CLIENT-03 | Phase 1 | Complete |
| DETECT-01 | Phase 3 | Pending |
| DETECT-02 | Phase 3 | Pending |
| DETECT-03 | Phase 3 | Pending |
| DETECT-04 | Phase 3 | Pending |
| STORE-01 | Phase 3 | Pending |
| STORE-02 | Phase 3 | Pending |
| STORE-03 | Phase 3 | Pending |
| TRACK-01 | Phase 4 | Pending |
| TRACK-02 | Phase 4 | Pending |
| TRACK-03 | Phase 4 | Pending |
| TRACK-04 | Phase 4 | Pending |
| NOTIFY-01 | Phase 4 | Pending |
| NOTIFY-02 | Phase 4 | Pending |
| REPORT-01 | Phase 5 | Pending |
| REPORT-02 | Phase 5 | Pending |
| REPORT-03 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 26 total
- Mapped to phases: 26
- Unmapped: 0

---
*Requirements defined: 2026-02-22*
*Last updated: 2026-02-22 after roadmap creation*
