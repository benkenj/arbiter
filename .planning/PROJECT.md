# Arbiter

## What This Is

Arbiter is a personal prediction market trading assistant that monitors Polymarket in real time, detects actionable trading signals, and tracks signal performance over time. It applies systematic strategies — starting with longshot bias exploitation and time decay — to find edges in market pricing. Built for one user, with trade execution as a future goal.

## Core Value

Surface profitable trading signals on Polymarket with enough accuracy to be worth acting on.

## Requirements

### Validated

- ✓ Fetch active Polymarket markets via Gamma API — existing
- ✓ Parse market data (question, outcomes, yes/no prices) into typed models — existing

### Active

- [ ] Persistent storage for markets, signals, and resolution outcomes (PostgreSQL)
- [ ] Structured config system for API keys, thresholds, and settings
- [ ] Reliable polling loop that fetches Polymarket markets and prices on a schedule
- [ ] Longshot bias detector: flag markets where the favored side (75–95%) appears underpriced
- [ ] Time decay detector: flag near-expiry markets where "no" is mispriced due to retail neglect
- [ ] Signal storage: persist each signal (market, strategy, price at signal time, timestamp)
- [ ] Resolution tracking: after a market resolves, record whether the signal was correct
- [ ] Performance reporting: show signal accuracy rate per strategy over time
- [ ] Discord alerts when a new signal is detected

### Out of Scope

- Trade execution — future milestone; signals-only for now
- Whale / copy trading — next strategy milestone after longshot bias + time decay ship
- Kalshi integration — deferred; Polymarket-only for now
- Cross-platform arb execution — deferred; arb monitoring is a lower-priority future signal
- Historical data backtesting — decided: live tracking only; store signals going forward and evaluate on resolution
- Calibration arbitrage (vs Metaculus) — later strategy milestone
- Resolution criteria edge trading — long-term backburner; interesting but complex
- Chatbot / agent interface — far future

## Context

**Existing codebase:** Polymarket API client is functional (`arbiter/clients/polymarket.py`). Basic async main loop exists. Most of the originally planned architecture (DB, matching, detection, notifications, config) is documented but not implemented. This is a brownfield project with a solid foundation but significant build-out needed.

**Strategy rationale:**
- *Longshot bias*: Bettors systematically over-bet longshots (exciting, high-payout), making heavy favorites (75–95%) underpriced. Systematic betting on favorites has documented edge in prediction markets.
- *Time decay*: Near-expiry markets where an event clearly isn't happening trade at inefficient "no" prices because retail bettors ignore boring positions. Similar to options theta.

**Signal tracking model:** Fire alerts on new signals. After market resolution, check whether the signal was correct (favored side won / "no" resolved YES). Build accuracy history per strategy.

**Platform:** Polymarket via Gamma API (market data) and CLOB API (order book, prices). No Kalshi dependency for now.

## Constraints

- **Tech stack**: Python 3.12+, asyncio, Poetry — established by existing codebase
- **Data access**: Polymarket Gamma API only; no official "historical fill" endpoint, so signal history starts from when Arbiter runs
- **Deployment**: Single-process for now; designed to run continuously (cron or always-on)
- **Budget**: No per-signal cloud cost tolerance — embeddings/LLM calls should be reserved for expensive operations only (e.g., market matching if Kalshi added later)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Polymarket-only for v1 | Kalshi access limited; single platform reduces complexity | — Pending |
| Longshot bias + time decay first | Systematic and automatable; lower complexity than whale following | — Pending |
| Live signal tracking (not backtesting) | No historical fill API; start collecting data now, evaluate on resolution | — Pending |
| Signals-only, no execution | Execution adds significant risk and complexity; validate edge first | — Pending |
| Cross-platform arb as monitoring signal only | Arb execution requires pre-funded accounts on both platforms, tight latency, survives fee compression poorly | — Pending |

---
*Last updated: 2026-02-22 after initialization*
