# Phase 3: Trade History - Research

**Researched:** 2026-03-01
**Domain:** Polymarket Data API trade ingestion, incremental fetch, SQLAlchemy bulk insert, asyncio loop pattern
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CLIENT-04 | Polymarket CLOB API client fetches trade history for a given market, with a `since` timestamp for incremental fetching | `data-api.polymarket.com/trades` accepts `market` (condition ID) and `offset`/`limit` for pagination; no `after` timestamp param on this endpoint — incremental is achieved by fetching all and filtering by `timestamp > last_ingested_at`, or by iterating offset pages until timestamps fall below the watermark |
| HIST-01 | Ingestion fetches all trades for each tracked market from the Polymarket CLOB API and stores them with wallet_address, market_id, side, size, price, and timestamp | Data API response has `proxyWallet`, `side`, `size`, `price`, `timestamp`, `conditionId` — maps directly to Trade columns; `market_id` resolved via `markets.condition_id` FK lookup |
| HIST-02 | Ingestion is incremental — each market stores a last_ingested_at timestamp, and subsequent runs only fetch trades newer than that timestamp | `markets.last_ingested_at` column already exists (migration 002); fetch pages until all returned trades are older than watermark, then stop; update `last_ingested_at` to max(timestamp) of fetched batch |
| HIST-03 | A single market ingestion failure logs the error and continues processing remaining markets — partial failure is non-fatal | Same per-item try/except pattern as discovery loop; log error, increment failure counter, continue to next market |
</phase_requirements>

---

## Summary

Phase 3 implements a trade ingestion loop that fetches historical CLOB trades from the Polymarket Data API for all tracked markets in the DB, stores them in the `trades` table, and updates `last_ingested_at` on each market after a successful ingest. The API is public (no authentication required), uses offset/limit pagination, and returns trades ordered by timestamp descending.

Incremental ingestion works by reading `markets.last_ingested_at`, fetching pages until a page contains no trades newer than that timestamp, then stopping. On the first run for a market (watermark is NULL), all trade pages are fetched. After success, `last_ingested_at` is updated to the max timestamp seen in this batch. This avoids re-fetching the full history on every run.

The Trade model in the DB already exists from Phase 2 migration. The `condition_id` column on `markets` is already populated by the discovery loop. The lookup chain is: `market.condition_id` → Data API `market` param → response `conditionId` → `proxyWallet`, `side`, `size`, `price`, `timestamp`. No schema migration is required for Phase 3.

**Primary recommendation:** Use `GET https://data-api.polymarket.com/trades?market={condition_id}&limit=500&takerOnly=false&offset={N}` — fetch pages until a page is fully older than the watermark or returns fewer than `limit` records. Bulk-insert new trades using SQLAlchemy `insert().values(batch)` (not upsert — trades are append-only). Update `markets.last_ingested_at` after each market's batch is committed.

---

## Standard Stack

### Core (already in pyproject.toml — no new installs)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | ^0.27 | Async HTTP client for Data API calls | Already in PolymarketClient; same pattern as Gamma API |
| SQLAlchemy | >=2.0 + asyncio | Bulk insert trades, update markets.last_ingested_at | Already used; `insert().values(batch)` for append-only bulk write |
| asyncpg | ^0.31.0 | PostgreSQL async driver | Required for SQLAlchemy async; already installed |
| tenacity | ^9.1.4 | Retry on transient HTTP errors | Already decorating `_fetch_page`; apply same pattern to CLOB fetcher |
| pydantic | ^2.0 | Trade response model for parsing/validation | Already used for Market model |

No new dependencies are required for Phase 3.

### New Config Fields
| Field | Type | Default | Env Var | Purpose |
|-------|------|---------|---------|---------|
| `ingestion_interval_seconds` | `int` | `300` | `INGESTION_INTERVAL_SECONDS` | Seconds between ingestion cycles |
| `ingestion_page_size` | `int` | `500` | `INGESTION_PAGE_SIZE` | Trades per page (max 500 per Data API docs) |
| `ingestion_batch_size` | `int` | `100` | `INGESTION_BATCH_SIZE` | Markets processed per cycle (optional rate-limit guard) |

---

## Architecture Patterns

### Recommended Phase 3 File Structure
```
arbiter/
├── clients/
│   └── polymarket.py     # ADD: get_trades_for_market() + Trade pydantic model
├── ingestion/
│   ├── __init__.py       # NEW: empty
│   └── trades.py         # NEW: ingest_market(), ingestion_loop()
└── config.py             # ADD: ingestion interval + page size config fields
```

No Alembic migration needed — `trades`, `markets.condition_id`, and `markets.last_ingested_at` all exist from migration 002.

### Pattern 1: Data API Client Method (append to polymarket.py)
**What:** Add a `get_trades_for_market()` method to `PolymarketClient` that calls the Data API using a separate `httpx.AsyncClient` (different base URL from Gamma API).
**When to use:** Called per market during the ingestion loop.

```python
# Source: https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets.md
DATA_API_BASE_URL = "https://data-api.polymarket.com"

class Trade(BaseModel):
    proxy_wallet: str = Field(alias="proxyWallet")
    side: str                  # "BUY" | "SELL"
    size: float
    price: float
    timestamp: int             # Unix seconds (integer)
    condition_id: str = Field(alias="conditionId")
    outcome: Optional[str] = None  # "Yes" | "No"

    model_config = ConfigDict(populate_by_name=True)

async def get_trades_for_market(
    self,
    condition_id: str,
    since: Optional[datetime] = None,
    page_size: int = 500,
) -> list[Trade]:
    """
    Fetch all trades for a market since the given watermark.
    Pages through offset pagination. Stops when a page is entirely
    older than `since` or returns fewer results than page_size.
    Returns trades newer than `since`, sorted descending by timestamp.
    """
    all_trades: list[Trade] = []
    offset = 0
    since_ts = int(since.timestamp()) if since else None

    while True:
        page = await self._fetch_clob_page(condition_id, offset, page_size)
        if not page:
            break
        if since_ts is not None:
            new_trades = [t for t in page if t.timestamp > since_ts]
            all_trades.extend(new_trades)
            # API returns newest-first. If we've seen trades older than watermark, stop.
            if len(new_trades) < len(page):
                break
        else:
            all_trades.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    return all_trades
```

**Critical detail:** The Data API returns trades in **descending timestamp order** (newest first). Once a page contains trades older than the watermark, no subsequent pages will contain newer trades. Stop fetching immediately when this happens.

### Pattern 2: Ingestion Loop (mirrors discovery_loop pattern)
**What:** An `async def ingestion_loop()` that runs every `INGESTION_INTERVAL_SECONDS`, iterates all markets with `active=True`, fetches trades, inserts them, and updates `last_ingested_at`.
**When to use:** This is the primary HIST-01, HIST-02, HIST-03 implementation.

```python
async def ingestion_loop(settings: Settings, session_factory, client) -> None:
    while True:
        t0 = time.monotonic()
        try:
            processed, total_trades, failures = await run_ingestion_cycle(
                settings, session_factory, client
            )
            elapsed = time.monotonic() - t0
            logger.info(
                "[ingestion] cycle complete in %.1fs — %d markets, %d trades inserted, %d failures",
                elapsed, processed, total_trades, failures,
            )
        except Exception as exc:
            elapsed = time.monotonic() - t0
            logger.error("[ingestion] cycle failed after %.1fs: %s", elapsed, exc)
        await asyncio.sleep(settings.ingestion_interval_seconds)
```

### Pattern 3: Per-Market Ingestion with Failure Isolation (HIST-03)
**What:** Wrap each market's fetch-and-insert in try/except; log the error and continue to the next market.

```python
async def ingest_market(session, client, market, page_size: int) -> int:
    """Returns count of new trades inserted. Raises on error (caller catches)."""
    trades = await client.get_trades_for_market(
        condition_id=market.condition_id,
        since=market.last_ingested_at,
        page_size=page_size,
    )
    if not trades:
        return 0
    rows = [_trade_to_db_row(trade, market.id) for trade in trades]
    await bulk_insert_trades(session, rows)
    # Update watermark to the newest trade's timestamp
    max_ts = max(t.timestamp for t in trades)
    market.last_ingested_at = datetime.fromtimestamp(max_ts, tz=timezone.utc)
    await session.commit()
    return len(rows)


async def run_ingestion_cycle(settings, session_factory, client) -> tuple[int, int, int]:
    processed = 0
    total_trades = 0
    failures = 0

    async with session_factory() as session:
        result = await session.execute(
            select(Market).where(Market.active == True, Market.condition_id.is_not(None))
        )
        markets = result.scalars().all()

    for market in markets:
        try:
            async with session_factory() as session:
                # Re-fetch market within session for update
                mkt = await session.get(Market, market.id)
                count = await ingest_market(session, client, mkt, settings.ingestion_page_size)
                total_trades += count
                processed += 1
        except Exception as exc:
            failures += 1
            logger.error(
                "[ingestion] market %s (%s) failed: %s",
                market.external_id, market.condition_id[:16], exc
            )
    return processed, total_trades, failures
```

### Pattern 4: Bulk Insert Trades (append-only, no upsert needed)
**What:** Trades are append-only — no conflict resolution needed. Use plain `insert().values()` without `on_conflict_do_update()`.

```python
async def bulk_insert_trades(session, trade_rows: list[dict]) -> None:
    if not trade_rows:
        return
    from sqlalchemy import insert as sa_insert
    from arbiter.db.models import Trade
    await session.execute(sa_insert(Trade).values(trade_rows))
    # Caller commits after updating last_ingested_at
```

**Why no upsert:** Each trade is a unique event. We never re-insert the same trade because incremental fetching stops before the watermark. No `UNIQUE` constraint exists on trades — adding one would complicate things and isn't needed if watermark logic is correct.

### Pattern 5: Wire into main.py via asyncio.gather
**What:** Add `ingestion_loop` to the existing `asyncio.gather()` call in `main.py`.

```python
await asyncio.gather(
    discovery_loop(settings, session_factory, client),
    ingestion_loop(settings, session_factory, client),
)
```

Both loops run concurrently. The `PolymarketClient` instance is shared. The CLOB Data API calls are non-blocking (async httpx), so both loops proceed independently.

### Anti-Patterns to Avoid
- **Fetching all pages and then filtering watermark in memory:** This re-fetches all historical trades every run. Stop as soon as a page is fully below the watermark.
- **Using a single session for the entire ingestion cycle:** Holding a session open across all market fetches (which involve async HTTP calls) ties up a DB connection for the full cycle duration. Use a session per market.
- **Using `upsert` for trades:** Trades are append-only. Upsert adds complexity and a UNIQUE constraint cost. Incremental watermark logic prevents duplicates.
- **Fetching with `takerOnly=True` (the default):** The default behavior omits maker-side trades. For computing wallet win rates, we need ALL trades a wallet made — set `takerOnly=false`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP retry on CLOB API | Custom retry loop | tenacity decorator (same as `_fetch_page`) | Already in project, covers transient 5xx and network errors |
| Pagination loop | Manual while-True with cursor state | Simple offset/limit loop with early exit on watermark | Data API uses offset/limit, not cursor — straightforward to implement |
| Trade deduplication | Hash-based dedup table | Watermark (last_ingested_at) logic | Correct watermark prevents re-fetching; no hash storage needed |
| Config validation | Manual env var checks | pydantic-settings (Field in Settings) | Already the project pattern; just add new fields |

**Key insight:** The Data API is offset-paginated, public, and returns descending timestamps — the watermark early-exit is O(pages fetched since last run) not O(all pages ever), which makes incremental ingestion efficient.

---

## Common Pitfalls

### Pitfall 1: Data API vs. CLOB API — Different Endpoints for Different Things
**What goes wrong:** Using `clob.polymarket.com/data/trades` (requires auth) when `data-api.polymarket.com/trades` (no auth, public) is what we want.
**Why it happens:** Documentation references both. The CLOB `/data/trades` endpoint is for authenticated user trade queries. The Data API `/trades` endpoint is for public market trade history.
**How to avoid:** Use `https://data-api.polymarket.com/trades?market={condition_id}&takerOnly=false`. No API key, no HMAC headers required.
**Warning signs:** 401/403 errors, or unexpectedly few trades (if `takerOnly=true` is inadvertently used).

### Pitfall 2: `takerOnly=true` Default Misses Half the Trades
**What goes wrong:** The Data API defaults `takerOnly=true`, which returns only trades where the wallet was the taker (the aggressive side). Maker-side trades are omitted.
**Why it happens:** The API is designed for user-facing "my trades" views, not full market history analysis.
**How to avoid:** Always pass `takerOnly=false` to get all trades for the market regardless of maker/taker role.
**Warning signs:** Trade count per market seems too low; wallets with known activity show no trades.

### Pitfall 3: Timestamp Format — Unix Seconds (integer), Not Milliseconds
**What goes wrong:** Comparing `last_ingested_at` (Python datetime) against `trade.timestamp` (integer) without unit alignment. The Data API `timestamp` field is Unix seconds as an integer.
**Why it happens:** Some APIs use milliseconds; the Data API uses seconds. Converting `last_ingested_at` to Unix seconds via `int(since.timestamp())` is correct.
**How to avoid:** Explicitly convert: `since_ts = int(market.last_ingested_at.timestamp())`. Store trades in DB as `datetime.fromtimestamp(trade.timestamp, tz=timezone.utc)`.
**Warning signs:** Watermark comparison is off by 1000x — either all trades are always "new" or always "old".

### Pitfall 4: `condition_id` is the Market Identifier for Data API, not `external_id`
**What goes wrong:** Passing `markets.external_id` (Gamma API's market ID, a short integer like `"503743"`) as the `market` parameter to the Data API, which expects a `conditionId` (a 64-char hex hash like `"0xdd22..."`).
**Why it happens:** The Gamma API and Data API use different market identifiers. `external_id` is the Gamma ID; `condition_id` is the CLOB/on-chain identifier.
**How to avoid:** The `markets` table has `condition_id` populated by the discovery loop (from `conditionId` in the Gamma API response). Use `market.condition_id` as the Data API `market` parameter. Skip markets where `condition_id IS NULL`.
**Warning signs:** 400 errors or empty responses from the Data API.

### Pitfall 5: Markets with NULL condition_id Should Be Skipped
**What goes wrong:** Some markets in the DB may have `condition_id = NULL` (e.g., older markets ingested before the column existed, or markets where Gamma returned `conditionId: null`). Attempting to fetch trades for a NULL condition_id causes an API error or empty result.
**Why it happens:** The `condition_id` column is nullable in the DB schema. The discovery loop sets it from the Gamma API response, but some markets may not have one.
**How to avoid:** In the ingestion cycle query, filter with `Market.condition_id.is_not(None)`. Log a warning if a market is skipped for this reason.
**Warning signs:** HTTP 400 or empty response for markets with `condition_id=null`; silent data gaps.

### Pitfall 6: Session Scope During Async HTTP Calls
**What goes wrong:** Holding a SQLAlchemy session open while awaiting `client.get_trades_for_market()` (which does async HTTP). If the HTTP call takes 10 seconds, the DB connection is held idle for that duration, starving other operations.
**Why it happens:** Using `async with session_factory() as session: ... await http_call()` nests the HTTP call inside the session context.
**How to avoid:** Fetch all trades from the API first (HTTP call), then open a session just for the DB write. The session context should be narrow: fetch → open session → insert + update → commit → close session.
**Warning signs:** DB connection pool exhaustion under load; `TimeoutError` acquiring pool connections.

### Pitfall 7: Winning Outcome Not in Trade Records — Must Derive from Market State
**What goes wrong:** Expecting a "winning trade" field in each trade record from the API. No such field exists. A wallet's win/loss on a market must be derived by comparing their `side` against the market's resolved outcome.
**Why it happens:** Trade records represent the execution event, not the resolution event. Resolution outcome is on the market, not the trade.
**How to avoid:** Store `side` (BUY/SELL) and `outcome` (YES/NO) from the Data API response. Market resolution is determined from the Gamma API `outcomePrices` field on a resolved market: if `outcomePrices[0] == "1.0"`, YES won. Phase 4 (whale scoring) will join trades against market outcome to classify correct/incorrect.
**Implementation note:** The Data API trade response includes an `outcome` field ("Yes" or "No") indicating which outcome token the wallet traded. Store this alongside `side` in the trades table, OR derive it from `outcomeIndex`. This is crucial for Phase 4 win-rate scoring.
**Warning signs:** Phase 4 cannot compute win rates because there is no way to know if a BUY was correct or incorrect.

---

## Code Examples

### Data API httpx Client Setup
```python
# Source: https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets.md
DATA_API_BASE_URL = "https://data-api.polymarket.com"

# In PolymarketClient.__init__:
self._data_client = httpx.AsyncClient(
    base_url=DATA_API_BASE_URL,
    timeout=30.0,
    headers={"Accept": "application/json"},
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
)
```

### Fetching a Page of Trades (with tenacity retry)
```python
@retry(
    retry=retry_if_exception_type(
        (httpx.HTTPStatusError, httpx.NetworkError, httpx.TimeoutException)
    ),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
async def _fetch_clob_page(
    self, condition_id: str, offset: int, limit: int
) -> list[Trade]:
    params = {
        "market": condition_id,
        "takerOnly": "false",    # MUST be false — get all trades, not just taker-side
        "limit": limit,
        "offset": offset,
    }
    response = await self._data_client.get("/trades", params=params)
    response.raise_for_status()
    return [Trade.model_validate(item) for item in response.json()]
```

### Trade to DB Row Mapping
```python
def _trade_to_db_row(trade: Trade, market_id: int) -> dict:
    return {
        "wallet_address": trade.proxy_wallet,
        "market_id": market_id,
        "side": trade.side,       # "BUY" or "SELL"
        "size": trade.size,
        "price": trade.price,
        "timestamp": datetime.fromtimestamp(trade.timestamp, tz=timezone.utc),
    }
```

### Incremental Watermark Fetch Logic
```python
async def get_trades_for_market(
    self,
    condition_id: str,
    since: Optional[datetime] = None,
    page_size: int = 500,
) -> list[Trade]:
    """Fetch trades newer than `since`. Returns empty list if none."""
    all_trades: list[Trade] = []
    offset = 0
    since_ts: Optional[int] = int(since.timestamp()) if since else None

    while True:
        page = await self._fetch_clob_page(condition_id, offset, page_size)
        if not page:
            break

        if since_ts is not None:
            # API returns newest-first; filter trades newer than watermark
            new_trades = [t for t in page if t.timestamp > since_ts]
            all_trades.extend(new_trades)
            # If this page had trades at or below watermark, we've caught up — stop
            if len(new_trades) < len(page):
                break
        else:
            all_trades.extend(page)

        # Last page (less than full) — done
        if len(page) < page_size:
            break
        offset += page_size

    return all_trades
```

### Updating last_ingested_at After Success
```python
# After inserting trade rows, update the market's watermark
if trades:
    max_ts = max(t.timestamp for t in trades)
    market_obj.last_ingested_at = datetime.fromtimestamp(max_ts, tz=timezone.utc)
    await session.commit()
```

### Wiring ingestion_loop into main.py
```python
# In async def main() in main.py — add ingestion_loop to gather:
from arbiter.ingestion.trades import ingestion_loop

await asyncio.gather(
    discovery_loop(settings, session_factory, client),
    ingestion_loop(settings, session_factory, client),
)
```

---

## Schema Analysis

The existing schema (from migration 002) already provides everything Phase 3 needs. No new migration required.

### trades table (already exists)
```sql
-- From migration 1c5960c71bfe
CREATE TABLE trades (
    id              SERIAL PRIMARY KEY,
    wallet_address  VARCHAR NOT NULL,       -- maps from proxyWallet
    market_id       INTEGER NOT NULL REFERENCES markets(id),
    side            VARCHAR(10) NOT NULL,   -- "BUY" | "SELL"
    size            FLOAT NOT NULL,
    price           FLOAT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL    -- from unix seconds: datetime.fromtimestamp(ts, UTC)
);
```

### markets table additions relevant to Phase 3
```sql
-- condition_id: used as Data API `market` parameter (added in migration 002)
condition_id    VARCHAR NULL
-- last_ingested_at: incremental watermark (added in migration 002)
last_ingested_at TIMESTAMPTZ NULL
```

### Winning outcome derivation (Phase 4 concern, but must design for now)
The Data API trade response includes `outcome` ("Yes"/"No") and `side` ("BUY"/"SELL"). To know if a trade was correct:
1. If a wallet BUYs "Yes" tokens and YES wins → correct
2. If a wallet SELLs "Yes" tokens and NO wins → also correct (sold the losing side)

The `outcome` field in the Data API response tells us WHICH token the trade was for. The current `trades` schema does not store `outcome`. **Phase 4 whale scoring will need to know the outcome token to determine wins.** There are two options:
- **Option A (recommended):** The Data API response has both `side` and `outcome` fields. We could store `outcome` in a new column now. BUT the current schema has no `outcome` column.
- **Option B (defer):** Phase 4 can re-query the Data API or use market resolution data from Gamma to infer win/loss from `side` alone (BUY Yes = wins if Yes resolves to 1.0).

Since the current `trades` schema stores `side` (BUY/SELL), the resolution can be derived by Phase 4 comparing `side + market.outcomePrices` on resolved markets. No immediate schema change is needed for Phase 3 correctness, but this is an open question worth flagging.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Authenticated CLOB `/data/trades` | Public `data-api.polymarket.com/trades` | Available as of 2024 | No API key needed for read access |
| Cursor-based pagination | Offset/limit pagination (Data API) | Current API design | Simple to implement with early-exit watermark logic |
| Poll all trades every cycle | Incremental via `last_ingested_at` watermark | Phase 3 design decision | Reduces API calls significantly after initial backfill |

---

## Open Questions

1. **Does the Data API `trades` endpoint have an `after` timestamp parameter?**
   - What we know: The official spec shows `limit`, `offset`, `takerOnly`, `filterType`, `filterAmount`, `market`, `eventId`, `user`, `side` — no `after` or `before` timestamp params.
   - What's unclear: Community usage of the CLOB authenticated endpoint has `after`/`before` params. The Data API (public, no auth) does not appear to have them.
   - Recommendation: Use the offset-pagination + watermark-exit approach described above. If experimentation reveals an `after` param exists, switch to it for efficiency (fewer pages on large markets).

2. **Should `outcome` be stored in the trades table?**
   - What we know: Data API response includes an `outcome` field ("Yes"/"No") indicating which token was traded. The current `trades` schema does not have an `outcome` column.
   - What's unclear: Phase 4 scoring needs to determine correct/incorrect trades. Deriving outcome from `side` + market `outcomePrices` is possible but requires joining two tables at score time. Storing `outcome` now would simplify Phase 4.
   - Recommendation: Add `outcome VARCHAR(10) NULL` to the `trades` table in a Phase 3 Alembic migration and store it during ingestion. This is low cost now and avoids a more disruptive change in Phase 4.

3. **How many markets will have active trades? Initial backfill time estimate?**
   - What we know: Typical Polymarket has ~1,000-5,000 active binary markets above volume threshold. Data API allows 500 trades/page, 200 req/10s rate limit.
   - What's unclear: Historical trade depth per market. Popular markets may have 10,000+ trades requiring 20+ pages per market.
   - Recommendation: Implement with concurrency limit (process markets one at a time or in small batches of 5) to stay well within rate limits. Log initial backfill progress. Consider allowing a "cold start" flag to limit initial historical depth.

4. **Should ingestion run at discovery interval or a separate interval?**
   - What we know: Discovery runs every 5 minutes. Ingestion may take longer than 5 minutes on initial backfill.
   - Recommendation: Use a separate `INGESTION_INTERVAL_SECONDS` config (default 300s). The loops run concurrently via `asyncio.gather`. Ingestion naturally completes at its own pace.

---

## Sources

### Primary (HIGH confidence)
- [Polymarket Data API — Get Trades for a User or Markets](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets.md) — confirmed public endpoint, full response schema, no auth required
- [Polymarket CLOB API — Rate Limits](https://docs.polymarket.com/api-reference/rate-limits.md) — confirmed 200 req/10s for data-api `/trades`
- Existing codebase — `arbiter/clients/polymarket.py`, `arbiter/discovery/loop.py`, `arbiter/db/models.py` — all patterns verified by reading source
- Migration `1c5960c71bfe_whale_schema.py` — confirmed `condition_id`, `last_ingested_at` already exist in `markets` table

### Secondary (MEDIUM confidence)
- [Polymarket py-clob-client — TradeParams](https://github.com/Polymarket/py-clob-client) — confirmed CLOB-side `after`/`before` params; Data API is a distinct endpoint
- [Polymarket Data API Docs Gist](https://gist.github.com/shaunlebron/0dd3338f7dea06b8e9f8724981bb13bf) — confirmed `proxyWallet`, `timestamp` (unix seconds), `conditionId`, `side`, `outcome` response fields

### Tertiary (LOW confidence)
- WebSearch on `outcomePrices` convention for resolved markets — training data + community sources suggest `["1.0", "0.0"]` indicates YES won; needs validation against live resolved market API response

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; all libraries already in project
- Data API endpoint and response schema: HIGH — official Polymarket docs confirmed, no auth required
- Incremental watermark pattern: HIGH — standard industry pattern, aligns with `last_ingested_at` column that already exists
- `takerOnly=false` requirement: HIGH — confirmed from Data API spec defaults
- `after` param absence on Data API: MEDIUM — spec doesn't list it, but could exist undocumented (flag for experimentation)
- `outcome` column design decision: MEDIUM — practical concern, not yet validated against Phase 4 needs
- `outcomePrices` win determination: MEDIUM — consistent with general knowledge and community sources

**Research date:** 2026-03-01
**Valid until:** 2026-04-01 (30 days — Data API is stable but Polymarket evolves; re-verify endpoint before implementation)
