# Codebase Concerns

**Analysis Date:** 2026-02-22

## Missing Core Components

**Database layer not implemented:**
- Issue: CLAUDE.md defines extensive PostgreSQL + pgvector storage layer with `arbiter/db/models.py` and `arbiter/db/session.py`, but these files do not exist
- Files: None exist — expected `arbiter/db/models.py`, `arbiter/db/session.py`
- Impact: Cannot persist market data, prices, or matched pairs. The entire system will lose state on restart and cannot operate as designed
- Fix approach: Implement complete DB layer with SQLAlchemy models for `markets`, `market_pairs`, `price_snapshots` tables. Add Alembic migrations. This is blocking all persistence functionality

**Kalshi API client missing:**
- Issue: `arbiter/clients/kalshi.py` is referenced in CLAUDE.md but does not exist. Only Polymarket client is implemented
- Files: None exist — expected `arbiter/clients/kalshi.py`
- Impact: Cannot fetch markets or prices from Kalshi platform. Arbitrage detection requires both platforms
- Fix approach: Implement `KalshiClient` with async httpx wrapper exposing `list_markets()` and `get_prices()` methods, mirroring `polymarket.py` interface

**Market matching system not implemented:**
- Issue: `arbiter/matching/embedder.py` and `arbiter/matching/matcher.py` referenced in architecture but files do not exist
- Files: None exist — expected `arbiter/matching/embedder.py`, `arbiter/matching/matcher.py`
- Impact: No market pair detection. System cannot identify when the same event is listed on both platforms
- Fix approach: Implement embedder using sentence-transformers (all-MiniLM-L6-v2), implement matcher using pgvector similarity + Claude LLM confirmation

**Opportunity detection not implemented:**
- Issue: `arbiter/detection/detector.py` not implemented
- Files: None exist — expected `arbiter/detection/detector.py`
- Impact: Cannot identify profitable spreads between matched pairs
- Fix approach: Implement detector that compares bid/ask prices across platform pairs, checks spread thresholds, emits Opportunity objects

**Notifications system not implemented:**
- Issue: `arbiter/notifications/discord.py` not implemented
- Files: None exist — expected `arbiter/notifications/discord.py`
- Impact: Cannot alert user to opportunities
- Fix approach: Implement `BaseNotifier` abstract class and `DiscordNotifier` subclass using Discord webhooks

**Configuration system not implemented:**
- Issue: `arbiter/config.py` referenced but does not exist. No `.env.example` file provided
- Files: None exist — expected `arbiter/config.py` and `.env.example`
- Impact: No environment variable validation, no way to configure API keys, timeouts, thresholds
- Fix approach: Implement pydantic-settings based config with all required env vars (API keys, database URL, Discord webhook, fee buffer, thresholds)

## Incomplete Implementation

**Polymarket client has fragile JSON parsing:**
- Issue: `_parse_json_field()` in `polymarket.py:10-19` silently returns empty list on parse failure. No logging or indication of data loss
- Files: `arbiter/clients/polymarket.py:10-19`
- Impact: If Gamma API changes response format or returns malformed JSON, field will silently become empty. Debugging will be extremely difficult
- Fix approach: Add logging on parse failure. Consider raising on critical fields (outcomes, prices). Add metrics/monitoring for parse failures

**JSON response parsing is unvalidated:**
- Issue: After `response.raise_for_status()`, code assumes `response.json()` will succeed. If response is not valid JSON, will crash with unhelpful error
- Files: `arbiter/clients/polymarket.py:80-84`, `arbiter/clients/polymarket.py:105-107`
- Impact: API returning non-JSON responses will crash the process
- Fix approach: Wrap `response.json()` in try-catch. Log response content before re-raising

**Duplicate market parsing logic:**
- Issue: Same Market object construction repeated verbatim in `list_markets()` and `get_market()` methods (lines 86-100 and 109-122)
- Files: `arbiter/clients/polymarket.py:86-100`, `arbiter/clients/polymarket.py:109-122`
- Impact: Bug fixes must be applied twice. Will diverge over time
- Fix approach: Extract into `_parse_market_response()` helper method

**No retry logic for API calls:**
- Issue: Network calls have no retry strategy. Transient failures (socket timeout, 429 rate limit, 503 service unavailable) will immediately fail
- Files: `arbiter/clients/polymarket.py:80`, `arbiter/clients/polymarket.py:105`
- Impact: Market discovery loops will stall on any network blip. System unreliable in production
- Fix approach: Implement exponential backoff retry with jitter (httpx library supports this natively via backoff library or custom middleware)

**Hard-coded timeout with no configurability:**
- Issue: httpx client has hard-coded 30.0 second timeout in `PolymarketClient.__init__()`. Not configurable, not consistent across environments
- Files: `arbiter/clients/polymarket.py:62-66`
- Impact: Timeout may be too short for slow networks or too long for low-latency requirements
- Fix approach: Move to config system. Allow per-environment and per-request overrides

**No connection pooling limits:**
- Issue: `AsyncClient` created with default settings. May create unlimited connections, leading to resource exhaustion
- Files: `arbiter/clients/polymarket.py:62-66`
- Impact: Under load, could exhaust system file descriptors or hit API rate limits
- Fix approach: Configure connection pool limits in AsyncClient: `limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)`

## Missing Error Handling

**Main entry point has no error handling:**
- Issue: `main()` in `arbiter/main.py` has no try-catch. Any exception will crash the process
- Files: `arbiter/main.py:6-21`
- Impact: Production deployment will be fragile. Single API failure crashes entire service
- Fix approach: Add exception handling to gracefully degrade and log errors

**No graceful shutdown handling:**
- Issue: AsyncClient must be closed explicitly. If main() is interrupted (Ctrl+C), client won't close properly
- Files: `arbiter/main.py`, `arbiter/clients/polymarket.py`
- Impact: Connection leaks on service restart. Potential resource exhaustion over time
- Fix approach: Ensure proper async context manager usage. Add signal handlers for SIGTERM/SIGINT

**Response status errors silently propagated:**
- Issue: `raise_for_status()` throws httpx exceptions but they're not caught or handled
- Files: `arbiter/clients/polymarket.py:81`, `arbiter/clients/polymarket.py:106`
- Impact: Will crash process rather than gracefully handle API errors
- Fix approach: Catch httpx exceptions, log them, potentially retry or emit alerts

## Testing Gaps

**No test files exist:**
- Issue: `pyproject.toml` lists pytest and pytest-asyncio but no `tests/` directory or test files
- Files: None exist — expected `tests/` directory
- Impact: Cannot verify behavior of API clients, cannot catch regressions, cannot maintain quality
- Fix approach: Implement unit tests for PolymarketClient, mock httpx responses, test edge cases (malformed JSON, empty results, timeouts)

**No integration test strategy:**
- Issue: No way to test against actual APIs or staging environments
- Files: None exist
- Impact: Bugs found in production. Can't verify database layer integrates correctly
- Fix approach: Create integration test suite that runs against staging Polymarket/Kalshi APIs

## Performance Concerns

**No pagination tracking:**
- Issue: `list_markets()` accepts offset/limit but `main.py` only fetches first 20 markets once
- Files: `arbiter/main.py:9`
- Impact: Won't discover new markets as platform grows. Limited market coverage
- Fix approach: Implement pagination loop in market discovery loop. Fetch all markets, respect offset/limit

**No caching of market metadata:**
- Issue: Every market discovery cycle refetches all market metadata (question, description, outcomes)
- Files: `arbiter/main.py`, planned main event loop
- Impact: Unnecessary API load. Market metadata rarely changes; embedding/matching is expensive
- Fix approach: Cache market metadata with TTL. Only refetch on explicit invalidation

**No rate limiting coordination:**
- Issue: No request throttling, backoff, or rate limit awareness
- Files: All API client calls
- Impact: Will hit API rate limits under moderate load. No graceful degradation
- Fix approach: Implement rate limiting middleware (token bucket or leaky bucket). Track rate limit headers from API responses

## Architectural Concerns

**Event loop not structured for continuous operation:**
- Issue: `main()` fetches markets once and exits
- Files: `arbiter/main.py:6-21`
- Impact: System won't run as specified (two continuous loops: discovery ~5min, polling ~1min)
- Fix approach: Implement proper asyncio event loop with scheduled tasks for discovery and polling

**No separation of concerns between CLI and service logic:**
- Issue: `main_sync()` is mixed with application logic. Makes testing hard
- Files: `arbiter/main.py:24-29`
- Impact: Cannot easily run as service, library, or in tests
- Fix approach: Move core logic to separate modules. Make main.py a thin CLI wrapper

**No logging system:**
- Issue: No structured logging framework. Only print() statements in main.py
- Files: Entire codebase
- Impact: Cannot debug production issues. Cannot monitor system health
- Fix approach: Integrate python logging or structured logging library (loguru, structlog). Configure for JSON output in production

## Security Considerations

**API keys could be exposed:**
- Risk: No config system exists, so API keys might end up in code or unencrypted files
- Files: None yet — but `config.py` will be critical
- Current mitigation: None yet
- Recommendations: Implement pydantic-settings with environment variable only loading. Never log secrets. Use AWS Secrets Manager or similar for sensitive config in production

**Unauthenticated API calls vulnerable to MITM:**
- Risk: Polymarket calls use HTTP timeout but no SSL verification configuration shown. Could be vulnerable to certificate pinning bypass
- Files: `arbiter/clients/polymarket.py:62-66`
- Current mitigation: httpx defaults to SSL verification enabled
- Recommendations: Explicitly configure SSL verification and certificate pinning. Audit third-party dependencies for known CVEs

**No input validation on market IDs:**
- Risk: `get_market(market_id)` uses string directly in URL path without validation
- Files: `arbiter/clients/polymarket.py:103-105`
- Current mitigation: None
- Recommendations: Validate market_id format before constructing requests. Use proper URL encoding

## Deployment Concerns

**No Docker/containerization:**
- Issue: No Dockerfile or docker-compose for easy deployment
- Files: None exist
- Impact: Difficult to deploy consistently. Hard to scale
- Fix approach: Create Dockerfile with proper Python base, poetry setup, health checks

**No database migrations strategy:**
- Issue: Alembic referenced in docs but no migration files exist
- Files: None exist — expected `alembic/versions/` directory
- Impact: Cannot version schema changes. Hard to deploy updates
- Fix approach: Initialize Alembic. Create initial migration for tables

**Dependencies vulnerable or outdated:**
- Issue: No lock file validation strategy. `poetry.lock` exists but no check for CVEs
- Files: `poetry.lock`
- Impact: Could ship with known vulnerabilities
- Fix approach: Integrate dependabot or similar. Run `poetry audit` in CI

## Data Quality Concerns

**No data validation on Market objects:**
- Issue: Pydantic Market model has many Optional fields with defaults to None/empty list
- Files: `arbiter/clients/polymarket.py:22-37`
- Impact: Invalid markets (no question, no outcomes, malformed prices) will silently enter system
- Fix approach: Add Pydantic validators to enforce minimum required fields. Raise on invalid data

**outcome_prices stored as strings:**
- Issue: Prices are stored as strings and parsed on-the-fly as floats in properties
- Files: `arbiter/clients/polymarket.py:32`, `arbiter/clients/polymarket.py:40-46`
- Impact: Repeated string-to-float conversion. No validation that strings are valid floats. Type mismatch risks
- Fix approach: Parse to float in factory method or validator. Store as proper numeric type

**No data freshness tracking:**
- Issue: Markets have no timestamp. Can't distinguish old prices from fresh ones
- Files: `arbiter/clients/polymarket.py:22-37`
- Impact: Price polling won't know how stale data is. Could base trades on outdated info
- Fix approach: Add `fetched_at` timestamp to Market model

---

*Concerns audit: 2026-02-22*
