# Technology Stack

**Analysis Date:** 2026-02-22

## Languages

**Primary:**
- Python 3.12+ - All application logic, API clients, matching engine, detection, and notifications

**Secondary:**
- None

## Runtime

**Environment:**
- Python 3.12 (specified in `pyproject.toml` as `^3.12`)

**Package Manager:**
- Poetry 2.3.2
- Lockfile: `poetry.lock` (present)

## Frameworks

**Core:**
- asyncio (Python standard library) - Event loop and concurrent execution for market monitoring loops
- httpx 0.27.2 - Async HTTP client for API integrations to Kalshi and Polymarket

**Testing:**
- pytest 8.4.2 - Test runner and framework
- pytest-asyncio 0.23.8 - Async test support for asyncio test functions

**Build/Dev:**
- Poetry - Dependency management and packaging

## Key Dependencies

**Critical:**
- httpx 0.27.2 - Async HTTP client, used by `arbiter/clients/polymarket.py` for Gamma API calls and intended for Kalshi REST API integration in `arbiter/clients/kalshi.py`
- pydantic 2.12.5 - Data validation and parsing using type hints; used in `arbiter/clients/polymarket.py` for Market model validation
- pydantic-settings 2.13.1 - Configuration management from environment variables; intended for `arbiter/config.py` to load API keys, database URLs, Discord webhooks

**Utilities:**
- python-dotenv 1.2.1 - Load `.env` files for local development configuration
- typing-extensions 4.15.0 - Type hint utilities for Python 3.12 compatibility
- typing-inspection 0.4.2 - Runtime type inspection used by pydantic

**HTTP/Networking:**
- anyio 4.12.1 - Async compatibility layer for httpx
- certifi 2026.1.4 - SSL certificate validation
- httpcore 1.0.9 - Low-level HTTP implementation for httpx
- h11 0.16.0 - HTTP/1.1 protocol implementation
- idna 3.11 - Internationalized domain name support
- sniffio 1.3.1 - Async library detection for httpx

## Configuration

**Environment:**
- Loaded via pydantic-settings from `.env` file (local development)
- Environment variables for production configuration
- No `.env.example` file found; project documentation references environment configuration in CLAUDE.md

**Key configs required (from CLAUDE.md architecture):**
- Kalshi API credentials
- Polymarket CLOB REST API credentials
- Anthropic API key (for Claude embeddings/matching)
- Discord webhook URL (for notifications)
- PostgreSQL connection string (not yet integrated in current codebase)
- Database credentials and pgvector configuration

**Build:**
- `pyproject.toml` - Poetry project configuration with dependencies and entry point
- `poetry.lock` - Exact resolved dependency versions

## Platform Requirements

**Development:**
- Python 3.12+
- Poetry (for dependency management)
- PostgreSQL with pgvector extension (future integration, not yet in codebase)

**Production:**
- Python 3.12+
- PostgreSQL database with pgvector extension (for vector similarity search)
- Network access to:
  - Kalshi REST API (`https://api.kalshi.com`)
  - Polymarket Gamma API (`https://gamma-api.polymarket.com`)
  - Anthropic API (`https://api.anthropic.com`)
  - Discord webhook endpoint (for notifications)

## Planned Dependencies (from CLAUDE.md)

Based on architecture documentation, the following are documented as planned but not yet installed:

- PostgreSQL + pgvector (database with vector embeddings)
- SQLAlchemy + Alembic (ORM and migrations) - for `arbiter/db/`
- sentence-transformers (local embeddings using `all-MiniLM-L6-v2` model) - for `arbiter/matching/embedder.py`
- Anthropic SDK (Claude API client) - for `arbiter/matching/matcher.py` (structured confirmation)

## Current Implementation Status

The current implementation includes only:
- Market fetching clients (Polymarket via Gamma API functional, Kalshi client structure planned)
- Pydantic models for type-safe data handling
- Async HTTP infrastructure
- Testing framework setup

The following modules are planned but not yet implemented:
- `arbiter/db/models.py` - SQLAlchemy models for markets, pairs, price snapshots
- `arbiter/db/session.py` - Database session management
- `arbiter/clients/kalshi.py` - Kalshi API client (parallel to polymarket client)
- `arbiter/matching/embedder.py` - Sentence transformer embeddings
- `arbiter/matching/matcher.py` - Claude-powered market matching
- `arbiter/detection/detector.py` - Opportunity detection logic
- `arbiter/notifications/discord.py` - Discord webhook notifications

---

*Stack analysis: 2026-02-22*
