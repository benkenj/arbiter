# Architecture

**Analysis Date:** 2026-02-22

## Pattern Overview

**Overall:** Asyncio-based event loop with dual concurrent workflows

**Key Characteristics:**
- Single Python process running two independent event loops: market discovery and price polling
- Market discovery runs on ~5-minute intervals to fetch and match markets across platforms
- Price polling runs on ~1-minute intervals to detect arbitrage opportunities
- LLM-based matching (Claude API) only during discovery, results cached permanently
- Async/await throughout using httpx for I/O and asyncio for concurrency
- Vector-based semantic matching using pgvector cosine similarity as first-pass candidate filter

## Layers

**API Integration Layer:**
- Purpose: Provide async HTTP clients for external prediction market APIs
- Location: `arbiter/clients/`
- Contains: Platform-specific API wrappers (`polymarket.py`, `kalshi.py` planned)
- Depends on: httpx, pydantic
- Used by: Market discovery loop, opportunity detector

**Data Layer:**
- Purpose: Persistent storage of markets, market pairs, and price snapshots
- Location: `arbiter/db/`
- Contains: SQLAlchemy models, session management
- Models:
  - `markets`: id, platform, external_id, title, description, expiry, embedding (vector(384)), active
  - `market_pairs`: id, kalshi_market_id, polymarket_market_id, confidence_score, confirmed_at
  - `price_snapshots`: id, market_id, yes_bid, yes_ask, timestamp (rolling 24h)
- Depends on: PostgreSQL + pgvector, SQLAlchemy, Alembic
- Used by: All layers for persistent state and lookup

**Matching Layer:**
- Purpose: Find and confirm cross-platform market matches
- Location: `arbiter/matching/`
- Contains: `embedder.py` (local embeddings), `matcher.py` (vector search + LLM confirmation)
- Flow:
  1. `embedder.py` generates embeddings from market titles using sentence-transformers (all-MiniLM-L6-v2)
  2. `matcher.py` queries pgvector for cosine-similar candidates
  3. Top candidates sent to Claude API for structured binary confirmation (YES/NO + confidence score)
  4. Confirmed pairs stored in `market_pairs` table with permanent caching
- Depends on: sentence-transformers, Anthropic SDK, database layer
- Used by: Market discovery loop only (not during polling)

**Detection Layer:**
- Purpose: Identify profitable arbitrage opportunities from live prices
- Location: `arbiter/detection/detector.py`
- Detects:
  - `yes_ask_A + yes_ask_B < 1.0 - fee_buffer`: true arbitrage
  - Configurable minimum spread threshold (default ~3¢)
- Emits: `Opportunity` objects containing market pair details and spread size
- Depends on: Market pairs table, price snapshots, detection config
- Used by: Price polling loop, notifier

**Notification Layer:**
- Purpose: Alert on detected opportunities and provide extensibility for trade execution
- Location: `arbiter/notifications/`
- Contains:
  - `BaseNotifier`: abstract class defining `notify(opportunity)` interface
  - `DiscordNotifier`: implements notification via Discord webhooks
- Design: Allows future `TradeExecutor(BaseNotifier)` to slot in without modifying other code
- Depends on: Opportunity objects, configuration (webhook URLs)
- Used by: Detection layer

**Configuration Layer:**
- Purpose: Environment-based configuration injection
- Location: `arbiter/config.py` (planned)
- Depends on: pydantic-settings
- Used by: All layers for credentials, API endpoints, thresholds

## Data Flow

**Market Discovery Loop (~5 min):**

1. Poll Kalshi API (`list_markets()`)
2. Poll Polymarket API (`list_markets()`)
3. Store new markets in `markets` table with embeddings
4. For each new market pair combination, run matching:
   a. Generate embeddings for both markets
   b. Store in database with vector(384)
   c. Query pgvector for cosine-similar candidates
   d. Send top-N candidates to Claude API for confirmation
   e. Store confirmed matches in `market_pairs` with confidence score
5. Sleep 5 minutes, repeat

**Price Polling Loop (~1 min):**

1. Load all confirmed market pairs from `market_pairs` table
2. Poll Kalshi API for best bid/ask on Kalshi market IDs
3. Poll Polymarket API for best bid/ask on Polymarket market IDs
4. Store snapshots in `price_snapshots` table
5. For each pair, run opportunity detection:
   a. Get latest prices for both markets
   b. Check if `yes_ask_A + yes_ask_B < 1.0 - fee_buffer`
   c. Compare to minimum spread threshold
   d. Emit `Opportunity` if new/changed
6. For each new/changed opportunity, notify via Discord
7. Prune `price_snapshots` to rolling 24-hour window
8. Sleep 1 minute, repeat

**State Management:**
- Markets are immutable once discovered
- Market pairs are permanent once confirmed (high confidence in Claude match)
- Price snapshots are ephemeral (24h rolling window)
- Opportunities are tracked for novelty (alert only on new or significantly changed spreads)

## Key Abstractions

**Market:**
- Purpose: Represents a single prediction market from one platform
- Examples: `arbiter/clients/polymarket.py:Market` (Pydantic model)
- Properties: id, question, description, end_date, outcomes, outcome_prices, yes_price, no_price
- Pattern: Pydantic BaseModel with computed properties for cross-platform normalization

**MarketPair:**
- Purpose: Represents a confirmed match between Kalshi and Polymarket markets
- Stored in: `market_pairs` database table
- Data: kalshi_market_id, polymarket_market_id, confidence_score (0-100), confirmed_at timestamp

**Opportunity:**
- Purpose: Represents a detected arbitrage or near-arbitrage spread
- Emitted by: `arbiter/detection/detector.py`
- Data: market_pair, spread_size (float, typically cents), yes_bid_spread, no_bid_spread, timestamp

## Entry Points

**CLI Entry:**
- Location: `arbiter/main.py`
- Function: `main_sync()` (synchronous wrapper)
- Triggers: Poetry script entry point `arbiter`
- Responsibilities: Initialize async runtime, load configuration, start both event loops concurrently

**Discovery Loop:**
- Entry: `asyncio.create_task()` in `main()` or similar
- Triggers: Timer event
- Responsibilities: Fetch markets, match new arrivals, store confirmed pairs

**Polling Loop:**
- Entry: `asyncio.create_task()` in `main()` or similar
- Triggers: Timer event
- Responsibilities: Fetch prices, detect opportunities, notify

## Error Handling

**Strategy:** Graceful degradation with retry logic

**Patterns:**
- API client exceptions (httpx.HTTPError): Logged and retried on next loop iteration
- Database connection failures: Logged, loop continues with cached data where possible
- LLM confirmation timeouts: Candidate marked as unconfirmed, retried later
- Malformed API responses: Logged with response sample, market skipped in current iteration
- Configuration errors: Fail-fast at startup in `config.py` validation

## Cross-Cutting Concerns

**Logging:** Console output (main.py shows `print()` patterns); future: structured logging to file/service

**Validation:** Pydantic models enforce schema at API client and database layers

**Authentication:** API credentials via environment variables (pydantic-settings); Discord webhook URL via env var

**Rate Limiting:** Implicit via loop intervals (5min discovery, 1min polling); API rate limits handled by clients with httpx retry config

---

*Architecture analysis: 2026-02-22*
