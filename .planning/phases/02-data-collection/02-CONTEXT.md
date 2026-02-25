# Phase 2: Data Collection - Context

**Gathered:** 2026-02-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Schema migration to the whale-tracking model, followed by a continuous market discovery loop that upserts filtered Polymarket market metadata every ~5 minutes. No price polling — that was inherited from the old signal-detection product and is not needed for whale copy trading.

Scope: schema migration + Polymarket CLOB client + market discovery loop with configurable filters + error recovery + heartbeat logging.

</domain>

<decisions>
## Implementation Decisions

### Market filters
- Binary-only filter is ON by default (`MARKET_BINARY_ONLY=true`) — only yes/no outcome markets
- Default minimum volume: 1,000 USDC (`MARKET_MIN_VOLUME=1000`)
- Default minimum liquidity: 1,000 USDC (`MARKET_MIN_LIQUIDITY=1000`) — matches volume for simplicity
- All three are env-var configurable; defaults represent a sensible floor that excludes dead markets

### Error handling & recovery
- API failures within a cycle: reuse the Phase 1 tenacity retry logic already on the Gamma client — no separate retry layer at the loop level
- After retries exhausted: log the error, skip this cycle, resume on the next tick — always keep running
- No escalation beyond logging — silence in logs (i.e. missing heartbeats) is the signal that something is wrong
- Fatal condition: if the DB connection is permanently lost, the service exits — let the process manager restart it

### Startup sequencing
- Discovery runs immediately on start — first cycle begins as soon as the loop starts, not after the first interval
- Startup health check (`--check` flag from Phase 1): exits immediately on failure — fail fast, no retry-until-ready
- Migrations are manual — `alembic upgrade head` is a deliberate step run before starting the service; the service does not auto-migrate

### Observability
- Heartbeat log line after each discovery cycle includes: cycle duration, markets upserted, new markets added, markets filtered out
  - e.g. `[discovery] cycle complete in 3.2s — 847 upserted, 12 new, 203 filtered out`
- Plain text logging for now — structured JSON is a future phase (already noted in v2 requirements)

</decisions>

<specifics>
## Specific Ideas

- Heartbeat format should make silence detectable — if the log goes quiet, something is wrong
- The Gamma API client hardening from Phase 1 (pagination, tenacity retries, typed models) is the foundation — Phase 2 wires it into a loop, doesn't rebuild it

</specifics>

<deferred>
## Deferred Ideas

- Price snapshot polling — not needed for whale copy trading; add back if a future phase requires current market prices
- Discord alert on consecutive discovery failures — log-only for now; could escalate in a later hardening phase
- Structured JSON logging — noted in v2 requirements (INFRA-V2-01)

</deferred>

---

*Phase: 02-data-collection*
*Context gathered: 2026-02-25*
