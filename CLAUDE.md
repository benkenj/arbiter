# Arbiter

## Purpose

Arbiter monitors Polymarket in real time, identifies high-performing large traders ("whales") by tracking their win rates and trade volumes, and alerts when those whales open new positions — enabling copy trading decisions.

---

## Architecture

Single Python process, asyncio-based. Three concurrent concerns:

- **Market discovery** (~every 5 min): fetch active Polymarket markets matching configured filters (binary, min volume, min liquidity), upsert to DB
- **Price polling** (~every 1 min): fetch best bid/ask for all tracked markets, store snapshots
- **Trade ingestion** (periodic): fetch trade history from Polymarket CLOB by market, store wallet activity, drive whale scoring

Whale scoring runs after ingestion — ranks wallets by win rate + volume, updates the whale list. Whale monitoring polls top-ranked wallets for new position opens and fires Discord alerts.

---

## Components

### 1. API Client (`arbiter/clients/`)
- `polymarket.py` — async httpx wrapper around the Polymarket Gamma + CLOB REST APIs
- Exposes: `list_markets()`, `get_prices(market_ids)`, `get_trades(market_id, since)`

### 2. Storage (`arbiter/db/`)
PostgreSQL.

Tables:
- `markets` — id, external_id, title, description, expiry, volume, liquidity, active
- `price_snapshots` — id, market_id, yes_bid, yes_ask, timestamp (pruned to rolling 24h)
- `trades` — id, wallet_address, market_id, side, size, price, timestamp
- `wallets` — id, address, win_rate, total_volume, total_trades, score, last_scored_at, is_tracked
- `positions` — id, wallet_address, market_id, current_size, avg_price, opened_at

### 3. Trade Ingestion (`arbiter/ingestion/`)
- `trades.py` — fetches CLOB trade history per market, stores records, tracks last-ingested timestamp per market for incremental updates

### 4. Whale Scorer (`arbiter/scoring/`)
- `whales.py` — computes win rate (correct/total resolved) and volume per wallet, applies configurable thresholds to classify whales, updates `wallets` table

### 5. Position Monitor (`arbiter/monitoring/`)
- `positions.py` — polls current positions for tracked whale wallets, detects new opens by diffing against last known state, emits alert events

### 6. Notifier (`arbiter/notifications/`)
- `discord.py` — sends Discord webhook alerts when a whale opens a new position: wallet (abbreviated), market question, side, size, entry price, link

---

## Tech Stack

- Python 3.12+
- asyncio + httpx (async HTTP)
- PostgreSQL (storage)
- SQLAlchemy + Alembic (ORM + migrations)
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
│   │   └── polymarket.py
│   ├── ingestion/
│   │   └── trades.py
│   ├── scoring/
│   │   └── whales.py
│   ├── monitoring/
│   │   └── positions.py
│   └── notifications/
│       └── discord.py
└── tests/
```

---

## Configuration (Market Filters)

Discovery applies configurable filters at fetch time:
- `MARKET_BINARY_ONLY` (bool, default true) — restrict to yes/no binary markets
- `MARKET_MIN_VOLUME` (float, default 0) — minimum trading volume in USDC
- `MARKET_MIN_LIQUIDITY` (float, default 0) — minimum open interest in USDC

---

## Future

- **Trade execution**: Polymarket order API for automated copy trading (architecture is alert-driven now, designed to slot execution in without restructuring)
- **Event-driven positioning**: enter positions ahead of scheduled events with predictable resolution patterns
- **Kalshi arbitrage**: cross-platform spread detection when Kalshi trading access is available
- **Whale specialization**: category-scoped whales, niche market experts, ROI-weighted scoring
