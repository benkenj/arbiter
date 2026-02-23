# Codebase Structure

**Analysis Date:** 2026-02-22

## Directory Layout

```
arbiter/
├── pyproject.toml              # Poetry project config, dependencies, entry point
├── poetry.lock                 # Locked dependency versions
├── CLAUDE.md                   # Project architecture and purpose documentation
├── .env.example                # Example environment variables (planned)
├── .planning/
│   └── codebase/               # GSD codebase analysis documents
├── arbiter/                    # Main package
│   ├── __init__.py             # Package marker (empty)
│   ├── main.py                 # Entry point, event loop orchestration
│   ├── config.py               # Configuration management (planned)
│   ├── clients/                # External API wrappers
│   │   ├── __init__.py
│   │   ├── polymarket.py       # Polymarket Gamma API client (current)
│   │   └── kalshi.py           # Kalshi REST API client (planned)
│   ├── db/                     # Data persistence layer
│   │   ├── models.py           # SQLAlchemy models (planned)
│   │   └── session.py          # Session management (planned)
│   ├── matching/               # Market pair matching
│   │   ├── embedder.py         # Local sentence-transformer embeddings (planned)
│   │   └── matcher.py          # pgvector search + Claude confirmation (planned)
│   ├── detection/              # Arbitrage opportunity detection
│   │   └── detector.py         # Spread calculation and thresholding (planned)
│   └── notifications/          # Alert delivery
│       └── discord.py          # Discord webhook notifier (planned)
└── tests/                      # Test suite (structure planned)
```

## Directory Purposes

**arbiter/clients/:**
- Purpose: Platform-specific API integrations
- Contains: Async HTTP clients wrapping REST/CLOB endpoints
- Key files: `polymarket.py` (Gamma API), `kalshi.py` (planned)
- Pattern: Each client module exports a `Client` class with `list_markets()`, `get_market()`, and `list_prices()` methods

**arbiter/db/:**
- Purpose: Data access and persistence
- Contains: SQLAlchemy ORM models and database session factory
- Key files: `models.py` (Market, MarketPair, PriceSnapshot), `session.py` (engine, sessionmaker)
- Pattern: Declarative models with relationships; session context managers for query safety

**arbiter/matching/:**
- Purpose: Cross-platform market identification and confirmation
- Contains: Vector embeddings and semantic matching with LLM confirmation
- Key files: `embedder.py` (local embeddings), `matcher.py` (search + Claude API)
- Pattern: Two-stage matching (vector similarity -> LLM confirmation) for accuracy and cost efficiency

**arbiter/detection/:**
- Purpose: Real-time arbitrage opportunity identification
- Contains: Spread calculation and threshold evaluation
- Key files: `detector.py` (main logic)
- Pattern: Iterator or generator yielding Opportunity objects from PriceSnapshot pairs

**arbiter/notifications/:**
- Purpose: Alert delivery and future trade execution
- Contains: Abstract notifier interface and concrete implementations
- Key files: `discord.py` (webhook delivery)
- Pattern: Inheritance from BaseNotifier for extensibility (slots in TradeExecutor later)

## Key File Locations

**Entry Points:**
- `arbiter/main.py`: Synchronous wrapper and async event loop orchestration. Spawns discovery and polling loops.

**Configuration:**
- `arbiter/config.py`: Pydantic-settings model loading env vars (API keys, thresholds, database URL, Discord webhook)
- `.env.example`: Template for required environment variables

**Core Logic:**
- `arbiter/clients/polymarket.py`: Polymarket API wrapper with Market Pydantic model
- `arbiter/matching/matcher.py`: pgvector + Claude matching orchestration
- `arbiter/detection/detector.py`: Spread calculation and thresholding

**Data Persistence:**
- `arbiter/db/models.py`: Market, MarketPair, PriceSnapshot SQLAlchemy models
- `arbiter/db/session.py`: PostgreSQL connection and session factory

**Notifications:**
- `arbiter/notifications/discord.py`: Discord webhook implementation

**Testing:**
- `tests/`: Co-located test files (pattern: `tests/unit/`, `tests/integration/`)

## Naming Conventions

**Files:**
- Module files: lowercase with underscores (e.g., `polymarket.py`, `embedder.py`)
- Package marker: `__init__.py` (empty or imports for convenience)
- Tests: `test_*.py` or `*_test.py` alongside implementation

**Directories:**
- Package names: lowercase, no underscores (e.g., `clients`, `matching`, `db`)
- Test directories: `tests/` at root

**Functions:**
- Async functions: verb-first, e.g., `list_markets()`, `get_market()`, `detect_opportunities()`
- Factory/initialization: snake_case, e.g., `create_session()`, `init_notifier()`
- Private functions: leading underscore, e.g., `_parse_json_field()`

**Classes:**
- PascalCase, e.g., `PolymarketClient`, `Market`, `MarketPair`, `Opportunity`, `DiscordNotifier`
- Abstract base: `BaseNotifier`
- Models: Pydantic `BaseModel` for data validation

**Variables:**
- Constants: UPPER_CASE, e.g., `GAMMA_BASE_URL`, `DISCOVERY_INTERVAL_SECONDS`
- Instance variables: snake_case, e.g., `yes_price`, `confidence_score`
- Private instance: leading underscore, e.g., `_client` (in PolymarketClient)

**Types:**
- Platform IDs: strings, e.g., market_id, kalshi_market_id
- Prices/probabilities: float (0.0-1.0), e.g., yes_price, yes_ask
- Timestamps: ISO format string or datetime, e.g., end_date, confirmed_at

## Where to Add New Code

**New API Integration (e.g., new prediction market):**
- Primary code: `arbiter/clients/{platform_name}.py`
- Follow PolymarketClient pattern: expose `list_markets()`, `get_market()`, async context manager
- Define platform-specific Market Pydantic model or adapt existing

**New Feature or Module:**
- Feature code: appropriate subdirectory in `arbiter/`
- Tests: `tests/` with matching directory structure
- Config variables: add to `arbiter/config.py` with env var binding

**Utilities or Helpers:**
- Shared helpers: `arbiter/utils/` (create if needed)
- Platform-specific helpers: within respective client module

**Tests:**
- Unit tests: `tests/unit/{module_name}/`
- Integration tests: `tests/integration/{feature}/`
- Fixtures/mocks: `tests/conftest.py`

## Special Directories

**arbiter/:**
- Purpose: Main package code
- Generated: No
- Committed: Yes

**.planning/codebase/:**
- Purpose: GSD codebase analysis documents
- Generated: Yes (by codebase mapper)
- Committed: Yes

**tests/:**
- Purpose: Test suite
- Generated: No
- Committed: Yes

**.env and .env.example:**
- Purpose: Environment configuration
- `.env`: Development secrets (not committed)
- `.env.example`: Template with placeholder values (committed)

**poetry.lock:**
- Purpose: Dependency version lock
- Generated: Yes (by Poetry)
- Committed: Yes (for reproducible installs)

## Import Organization

**Order (enforced by linting config when added):**
1. Standard library: `asyncio`, `json`, `logging`
2. Third-party: `httpx`, `pydantic`, `sqlalchemy`
3. Relative imports: `from arbiter.clients import PolymarketClient`

**Path Aliases:**
- Not currently configured; future consideration for deeply nested modules

## Module Exports

**arbiter/clients/__init__.py:**
- Convenience exports: `from .polymarket import PolymarketClient` (optional, allows `from arbiter.clients import PolymarketClient`)

**arbiter/__init__.py:**
- Typically empty; package version defined in pyproject.toml

---

*Structure analysis: 2026-02-22*
