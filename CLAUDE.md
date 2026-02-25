# Arbiter

## Purpose

Arbiter monitors Kalshi and Polymarket in real time, detects when both platforms are listing the same event, and alerts when there is a profitable spread between them (arbitrage or near-arb opportunity).

---

## Architecture

Single Python process, asyncio-based, two main loops:

- **Market discovery** (~every 5 min): fetch all active markets from both platforms, find new ones, trigger the matcher for new arrivals
- **Price polling** (~every 1 min): fetch best bid/ask for all markets in confirmed pairs, run opportunity detection, fire Discord alerts on new spreads

Matching only runs at discovery time, not during polling — LLM calls are expensive, results are cached permanently.

---

## Components

### 1. API Clients (`arbiter/clients/`)
- `kalshi.py` — async httpx wrapper around the Kalshi REST API
- `polymarket.py` — async httpx wrapper around the Polymarket CLOB REST API
- Both expose: `list_markets()`, `get_prices(market_ids)`

### 2. Storage (`arbiter/db/`)
PostgreSQL + pgvector.

Tables:
- `markets` — id, platform, external_id, title, description, expiry, embedding (vector(384)), active
- `market_pairs` — id, kalshi_market_id, polymarket_market_id, confidence_score, confirmed_at
- `price_snapshots` — id, market_id, yes_bid, yes_ask, timestamp (pruned to rolling 24h)

### 3. Market Matcher (`arbiter/matching/`)
- `embedder.py` — generates embeddings from market titles using `sentence-transformers` (all-MiniLM-L6-v2), runs locally, no API cost
- `matcher.py` — pgvector cosine similarity to find candidates, then Claude (Anthropic API) for structured confirmation (YES/NO + confidence score)

### 4. Opportunity Detector (`arbiter/detection/detector.py`)
For each confirmed pair after a price poll:
- If `yes_ask_A + yes_ask_B < 1.0 - fee_buffer`: true arbitrage
- Configurable minimum spread threshold (default ~3¢)
- Emits `Opportunity` objects to the notifier

### 5. Notifier (`arbiter/notifications/`)
`BaseNotifier` abstract class with `notify(opportunity)`. `DiscordNotifier` implements it via webhook. Designed so a future `TradeExecutor` slots in with no other code changes.

---

## Tech Stack

- Python 3.12+
- asyncio + httpx (async HTTP)
- PostgreSQL + pgvector (storage + vector search)
- SQLAlchemy + Alembic (ORM + migrations)
- sentence-transformers (local embeddings)
- Anthropic SDK / Claude (LLM match confirmation)
- pydantic-settings (config)
- Discord webhook (notifications)

---

## Project Structure

```
arbiter/
├── pyproject.toml
├── .env.example
├── arbiter/
│   ├── main.py
│   ├── config.py
│   ├── db/
│   │   ├── models.py
│   │   └── session.py
│   ├── clients/
│   │   ├── kalshi.py
│   │   └── polymarket.py
│   ├── matching/
│   │   ├── embedder.py
│   │   └── matcher.py
│   ├── detection/
│   │   └── detector.py
│   └── notifications/
│       └── discord.py
└── tests/
```

---

## Future

- Trade execution: implement `TradeExecutor(BaseNotifier)` using Kalshi and Polymarket order APIs
- Historical data ingestion for backtesting arb opportunities
- Market-neutral strategies for longer-expiry events
- Agent-driven probability research to find mispriced markets beyond simple cross-platform arb
