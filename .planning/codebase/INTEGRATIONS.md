# External Integrations

**Analysis Date:** 2026-02-22

## APIs & External Services

**Prediction Markets:**
- **Kalshi** - Prediction market platform for event pricing and orderbook access
  - SDK/Client: Custom async wrapper in `arbiter/clients/kalshi.py` (planned)
  - Auth: API credentials from environment variable (not yet specified)
  - Base URL: `https://api.kalshi.com` (inferred from architecture)
  - Methods needed: Market listing, best bid/ask prices

- **Polymarket (Gamma API)** - Automated market maker protocol on Ethereum
  - SDK/Client: Custom async wrapper in `arbiter/clients/polymarket.py` (functional)
  - Base URL: `https://gamma-api.polymarket.com`
  - Authentication: Public API, no auth required for market data
  - Methods implemented: `list_markets()`, `get_market(market_id)`
  - Response parsing: Handles JSON string fields that Gamma API may return as strings or lists

**AI/Matching Engine:**
- **Anthropic Claude API** - LLM for structured market matching confirmation
  - SDK/Client: anthropic-sdk (planned dependency)
  - Auth: Environment variable `ANTHROPIC_API_KEY`
  - Purpose: Structured YES/NO confirmation that markets on Kalshi and Polymarket represent the same event
  - Integration point: `arbiter/matching/matcher.py` (planned)
  - Input: Market title + description pairs from both platforms
  - Output: Confidence score (0-100) and matching decision

## Data Storage

**Databases:**
- **PostgreSQL** (planned, not yet integrated)
  - Connection: Environment variable `DATABASE_URL`
  - Client: SQLAlchemy ORM + Alembic migrations
  - Location: `arbiter/db/models.py` (defines schema), `arbiter/db/session.py` (connection management)
  - Extensions: pgvector for vector similarity search

**Vector Search:**
- **pgvector** (PostgreSQL extension, planned)
  - Used for cosine similarity matching on market embeddings
  - Embeddings generated from market titles via sentence-transformers
  - Schema location: `markets.embedding` column (vector(384))

**File Storage:**
- Local filesystem only - No cloud storage integration

**Caching:**
- None - Results are "cached permanently" via PostgreSQL `market_pairs` table

## Authentication & Identity

**Auth Provider:**
- Custom API key authentication for:
  - Kalshi (API credentials)
  - Anthropic (API key)
- No user authentication required (single-user monitoring bot)
- No session management

## Monitoring & Observability

**Error Tracking:**
- Not detected - No Sentry, DataDog, or similar integration

**Logs:**
- Python `logging` module (console only, no structured logging observed)
- Future: Discord webhook for critical alerts via `arbiter/notifications/discord.py`

## CI/CD & Deployment

**Hosting:**
- Not specified - Deploy target not documented in current codebase
- Designed for cloud-ready asyncio deployment (GCP Cloud Run, AWS Lambda with asyncio adapter, etc.)

**CI Pipeline:**
- Not detected - No GitHub Actions, GitLab CI, or similar

## Environment Configuration

**Required env vars (from CLAUDE.md and architecture):**
- `DATABASE_URL` - PostgreSQL connection string (planned)
- `ANTHROPIC_API_KEY` - Claude API key for matching
- `KALSHI_API_KEY` - Kalshi API authentication (planned)
- `KALSHI_API_SECRET` - Kalshi API secret (if needed)
- `DISCORD_WEBHOOK_URL` - Discord webhook for alerts
- `POLYMARKET_API_KEY` - If Polymarket requires authentication (currently public API)

**Optional env vars:**
- `OPPORTUNITY_MIN_SPREAD_PCT` - Minimum spread threshold for opportunities (default ~3¢ = 3%)
- `DISCOVERY_INTERVAL_SECS` - Market discovery loop interval (default ~300s/5 min)
- `PRICE_POLL_INTERVAL_SECS` - Price polling loop interval (default ~60s/1 min)
- `FEE_BUFFER_PCT` - Transaction fee buffer for arbitrage calculations

**Secrets location:**
- `.env` file (development)
- Environment variables (production)
- No cloud secret manager integration yet (pydantic-settings supports AWS Secrets Manager, Azure Key Vault, GCP Secret Manager via extras)

## Webhooks & Callbacks

**Incoming:**
- Discord webhook (outgoing only for now, no incoming)

**Outgoing:**
- **Discord Webhook** - Alert notifications for profitable arbitrage opportunities
  - Implementation: `arbiter/notifications/discord.py` using `BaseNotifier` abstraction
  - Trigger: When `yes_ask_A + yes_ask_B < 1.0 - fee_buffer` (true arbitrage opportunity)
  - Payload: `Opportunity` object with market details, spread percentage, execution instructions
  - Design: Extensible; `TradeExecutor(BaseNotifier)` can be added in future without changes to detection logic

## Price Data Flow

**Polymarket:**
- Gamma API `/markets` endpoint - Returns list of active markets with implied probabilities
- Gamma API `/markets/{id}` endpoint - Returns single market details
- No direct orderbook access documented (Gamma is AMM-based)

**Kalshi:**
- Market listing and orderbook data (implementation planned)
- Best bid/ask prices expected via REST API

**Update Frequencies (from CLAUDE.md):**
- Market discovery: ~5 minutes (find new matched pairs)
- Price polling: ~1 minute (detect spread opportunities)

## Integration Architecture

**Market Matching Flow (matching loop, ~5 min):**
1. `arbiter/clients/kalshi.py` → Fetch all Kalshi markets
2. `arbiter/clients/polymarket.py` → Fetch all Polymarket markets
3. `arbiter/matching/embedder.py` → Generate embeddings from titles (sentence-transformers, local)
4. `arbiter/matching/matcher.py` → pgvector cosine similarity search → find candidate pairs
5. `arbiter/matching/matcher.py` → Claude API structured confirmation → YES/NO with confidence
6. Store confirmed pairs in `market_pairs` table with confidence score

**Opportunity Detection Flow (polling loop, ~1 min):**
1. For each confirmed pair in `market_pairs`:
   - Fetch current best bid/ask from both platforms
   - Store in `price_snapshots` table (rolling 24h)
2. `arbiter/detection/detector.py` → Calculate spreads
3. If spread > threshold AND `yes_ask_A + yes_ask_B < 1.0`:
   - Emit `Opportunity` object
4. `arbiter/notifications/discord.py` → Send Discord webhook alert

---

*Integration audit: 2026-02-22*
