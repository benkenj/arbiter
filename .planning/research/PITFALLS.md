# Pitfalls Research

**Domain:** Prediction market signal detection — longshot bias, time decay, Polymarket API, signal tracking, async service
**Researched:** 2026-02-22
**Confidence:** MEDIUM (Polymarket-specific API behavior from official docs; signal strategy pitfalls from academic literature + WebSearch; async patterns from official Python docs + GitHub issues)

---

## Critical Pitfalls

### Pitfall 1: Longshot Bias Doesn't Reliably Exist on Polymarket

**What goes wrong:**
Longshot bias — the tendency to overpay for unlikely outcomes, making favorites underpriced — is well-documented in sports betting markets. On Polymarket specifically, the SSRN paper "Exploring Decentralized Prediction Markets" (2025) found no evidence of a general longshot bias and concluded that "market prices closely track realized probabilities." The signal detector fires on statistically normal prices, producing zero actual edge.

**Why it happens:**
The strategy is borrowed from sports-betting research where bookmakers set prices, not continuous auctions. Polymarket is a CLOB-based market where informed participants and market makers actively compress mispricings. A price of 0.80 on a binary Polymarket market may accurately reflect 80% probability — not an underpriced favorite.

**How to avoid:**
- Do not treat academic sports-betting literature on longshot bias as validation for Polymarket signal quality.
- Calibrate threshold ranges (75%–95% "favorite" zone) against a sample of already-resolved Polymarket markets before claiming there is edge. The Polymarket `/accuracy` endpoint provides historical calibration data for cross-checking.
- If the hit rate on signals after 30+ resolutions is close to the market-implied probability (e.g., 85% signals win ~85% of the time), there is no edge — the market is correctly priced.
- Consider filtering to illiquid or low-volume markets where arbitrageurs are less active. Research on Kalshi (2025) found the largest favorite-longshot bias in the lowest-volume quintile.

**Warning signs:**
- Signal hit rate closely matches implied probability (e.g., 88% signals resolve YES at ~88%).
- High signal volume on large, active markets (presidential elections, major sporting events) where liquidity is deep.
- Strategy is generating alerts on the same recurring market types with no discernible edge after 50+ resolutions.

**Phase to address:**
Signal detection implementation phase — build resolution tracking and accuracy reporting from day one. Do not run the strategy for months before measuring calibration.

---

### Pitfall 2: Time Decay Signal Fires on Markets Where the Event Is Still Live

**What goes wrong:**
The time decay strategy targets markets near expiry where "No" is mispriced because the event clearly isn't happening. The classic false positive: a market expires in 4 hours, "No" is at 0.93 — but the triggering event hasn't definitively not-happened yet. The signal fires, the event then happens in the last hour, and the signal scores as incorrect. This inflates false positive rate and undermines confidence in the strategy.

**Why it happens:**
Time-to-expiry is a necessary but not sufficient condition. The signal also requires that the outcome is already knowable — the event either happened or clearly won't happen. Markets with event windows that extend to the expiration (e.g., "Will X happen this week?" expiring Friday at midnight) have legitimate remaining uncertainty until the deadline, even when only hours remain.

**How to avoid:**
- Separate the time-decay signal into two components: (1) time-to-expiry threshold (e.g., < 24 hours) AND (2) "No" price above a threshold (e.g., > 0.90). Both are required, but neither alone is sufficient.
- Add a filter: only flag markets where the price trend also shows consistent "No" appreciation over the past several hours — not just a single snapshot. A "No" that jumped from 0.50 to 0.90 in 20 minutes may be an actual event occurring.
- Store price history per market from the polling loop to enable this trend check.
- Consider adding an explicit "hours until expiry" band — e.g., 4–48 hours before expiry. Markets expiring in < 4 hours may have genuine last-minute uncertainty; markets at > 48 hours may be too early.

**Warning signs:**
- Time decay signals fire on markets with broad event windows ("this week," "this month").
- A signal fires and then the market resolves YES (opposite direction).
- Signals cluster on markets that resolve the same day they expire.

**Phase to address:**
Signal detection implementation phase — build the time decay detector with explicit event-window awareness from the start, not as a later patch.

---

### Pitfall 3: Resolution Tracking Breaks on N/A and Disputed Markets

**What goes wrong:**
Polymarket uses the UMA Optimistic Oracle for resolution. Markets can resolve as YES, NO, or as N/A / "clarified" (refunded to all holders). An N/A resolution means the event was ambiguous, the market was malformed, or the resolution criteria were disputed. If the signal tracking schema treats resolution as a boolean (correct/incorrect), N/A markets will corrupt accuracy statistics — they're neither a win nor a loss for the strategy.

Additionally, UMA's dispute resolution process has a 2-hour challenge window followed by an escalation process that can take days. A market's `resolved` field in the Gamma API may flip to `true` before the dispute is fully settled, or it may remain `false` while practically closed to trading. The Gamma API also shows markets as `closed: true` before they are `resolved: true`, creating a state where the market is closed but the final outcome is not recorded.

**Why it happens:**
Resolution tracking is built assuming every market resolves YES or NO cleanly. The developer checks `resolved == true` and reads `outcome_prices` to determine who won. But on N/A markets, prices may be set to 0.5/0.5 or 1.0/1.0 in unexpected ways. Disputed markets may take days to truly finalize. The governance attack on Polymarket in March 2025 showed that oracle manipulation can force a fake resolution.

**How to avoid:**
- Store resolution outcome as an enum: `YES | NO | NA | DISPUTED | PENDING`, not a boolean.
- Never score signal accuracy until the market has been `resolved: true` for at least 24 hours (dispute window + buffer).
- Do not infer the resolution winner from `outcome_prices` — prices after resolution may be 0.0/1.0, 1.0/0.0, or 0.5/0.5 for N/A. Instead, fetch the final outcome from the `result` field if the Gamma API provides it, or from the CLOB API prices once fully settled.
- Track N/A resolutions separately; exclude them from accuracy rate calculations but count them for coverage statistics.
- Log every state transition: `active → closed → resolved → scored`.

**Warning signs:**
- Resolution outcomes in the DB show unexpected price combinations (both near 0.5, or both near 0.0).
- Signal accuracy statistics change when markets from weeks ago update their resolved state.
- A market shows `resolved: true` in the API but later reverts.

**Phase to address:**
Database schema phase — define the resolution state machine before writing signal storage or accuracy reporting.

---

### Pitfall 4: asyncio Tasks That Swallow Exceptions Silently Kill the Strategy Loop

**What goes wrong:**
One polling iteration fails — an httpx exception, a DB connection timeout, a parsing error. The exception is not caught. If the task was spawned with `asyncio.create_task()` and the exception goes unhandled, Python logs a "Task exception was never retrieved" warning to stderr at garbage collection time — but does nothing to restart the loop. The polling loop stops. The process continues running, Discord is silent, and the operator doesn't know signals are no longer being generated.

**Why it happens:**
`asyncio.create_task()` fire-and-forget is the natural pattern for concurrent loops. Developers wrap the outer loop body in a try/except for known errors but miss the case where the task reference is dropped and an unexpected exception surfaces. Python's asyncio does not propagate unhandled task exceptions to the event loop — they become warnings at GC time.

**How to avoid:**
- Every top-level task should have an outer `try/except Exception` that logs the error, sleeps a backoff interval, and then continues the loop — not exits it.
- Use `asyncio.create_task(coro).add_done_callback(handle_task_result)` where `handle_task_result` checks for exceptions and re-raises or logs.
- Set a custom event loop exception handler: `loop.set_exception_handler(handler)` as a catch-all.
- Consider sending a "heartbeat" Discord message every N hours. If the heartbeat stops, the process is unhealthy.
- Pattern: wrap each loop body in a function decorated with error-catching, not the task spawner itself.

```python
async def discovery_loop():
    while True:
        try:
            await run_discovery_cycle()
        except Exception:
            logger.exception("Discovery cycle failed; retrying in 60s")
            await asyncio.sleep(60)
        else:
            await asyncio.sleep(300)
```

**Warning signs:**
- Process is running but Discord has been silent for longer than the polling interval.
- `asyncio: Future exception was never retrieved` messages in stderr.
- The task object is not stored in a variable (fire-and-forget without a reference).

**Phase to address:**
Polling loop implementation phase — build the loop with the error-handling pattern from day one.

---

### Pitfall 5: Signal De-duplication Not Built In — Same Market Alerts Repeatedly

**What goes wrong:**
A market meets the longshot bias threshold on every polling cycle for 3 days straight. The detector fires an alert every cycle. Discord gets flooded with identical alerts. The "new signal" concept isn't enforced — every detection is treated as a new signal rather than a persistent condition.

**Why it happens:**
The detector runs on current prices at polling time. Nothing in the price check tracks whether this market has already been flagged. The signal table stores a new row each time, and the alert fires on each new row.

**How to avoid:**
- A signal is a state, not an event. Model it as: a signal "opens" when the market first meets criteria, and "closes" when it no longer meets criteria or resolves.
- Before inserting a new signal, query whether an open signal already exists for this (market, strategy) pair. If so, skip the insert and the alert.
- Only re-alert if the price has moved significantly from the original signal price (e.g., > 5 percentage points in the "wrong" direction and then back), indicating a meaningful change worth calling out again.
- Add a `status` column to signals: `open | closed | resolved`. Alert on open transitions only.

**Warning signs:**
- Signal count grows linearly with polling cycles for the same market.
- Discord notification history shows identical market alerts hours apart.
- No "signal deduplication" or "already active" check in the detector code.

**Phase to address:**
Signal storage schema phase — the `signals` table needs an `open/closed` lifecycle from the first schema design.

---

### Pitfall 6: Performance Reporting Schema That Can't Answer "Is the Strategy Working?"

**What goes wrong:**
After months of signals, the developer queries the DB to check signal accuracy and finds the data can't answer the question. Either: (a) the original price at signal time wasn't stored so there's no baseline, (b) N/A resolutions are mixed in with YES/NO scores inflating "incorrect" counts, (c) there's no way to distinguish "signal fired but market hasn't resolved yet" from "signal fired and was wrong," or (d) strategies can't be compared because signals aren't tagged with enough metadata.

**Why it happens:**
Schema design is driven by what's easy to write, not by what queries need to answer. Resolution tracking is added later as an afterthought and doesn't join cleanly to signal records.

**How to avoid:**
Design the schema to answer these specific queries before writing any code:
1. "What is strategy X's win rate over the last 90 days?" — requires: strategy tag, signal open time, resolution outcome (YES/NO only), resolved_at timestamp.
2. "What was the market price when the signal fired vs. what it resolved at?" — requires: `price_at_signal` stored at signal creation time; resolution price or outcome.
3. "How many of my signals are still open vs. scored?" — requires: `status` field with lifecycle states.
4. "Which market types produce the most false positives?" — requires: market category or metadata joined to signals.

Schema minimum:
```sql
signals (
  id, market_id, strategy, opened_at, price_at_signal,
  status,           -- open | closed | resolved_correct | resolved_incorrect | resolved_na
  resolved_at,      -- null until resolution
  resolution_outcome  -- YES | NO | NA | null
)
```

**Warning signs:**
- `signals` table has no `price_at_signal` column.
- Resolution outcomes are stored as booleans or integers.
- No `opened_at` / `closed_at` lifecycle timestamps.
- Accuracy query requires a multi-step JOIN that doesn't work cleanly.

**Phase to address:**
Database schema phase — define the full signal lifecycle schema before implementing detectors.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Polling `closed: false` markets only for new discoveries | Simpler query, smaller result set | Misses markets that closed and resolved between polling cycles; resolution tracking becomes unreliable | Never — always poll a separate "recently resolved" query |
| Storing `outcome_prices` as strings (current state) | No parsing on write | Repeated float conversion on every read; no DB-level numeric constraints; can't filter/sort by price in SQL | Acceptable in the existing API client; must be parsed to float/numeric before writing to the DB |
| No signal deduplication on first implementation | Faster to build | Alert spam immediately on first production use | Never — deduplication is a one-line check before insert |
| Single polling loop for both discovery and price polling | Simpler control flow | Discovery (expensive: all markets) blocks price polling (cheap but time-sensitive) | Only acceptable for < 100 markets; will cause staleness at scale |
| `print()` instead of structured logging | Fast iteration | Cannot debug production issues, cannot filter by severity, cannot grep for errors | Never past the prototype phase |
| Hard-coding strategy thresholds in detector code | Fast to write | Can't tune parameters without redeployment; can't run A/B comparisons | Acceptable in v1 if thresholds are at least constants at the top of the file |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Polymarket Gamma API | Assuming `resolved: true` means final outcome is in `outcome_prices` | Check `outcome_prices` only after a 24-hour grace period post-resolution; N/A markets may show unexpected price values |
| Polymarket Gamma API | Using `closed: false` as the only filter | `closed` and `resolved` are separate states; a market can be `closed: true, resolved: false` during the 2-hour dispute window |
| Polymarket Gamma API | Fetching all markets in a single call without pagination | Gamma API `/markets` returns max 100 per call (configurable); active market count easily exceeds this; must paginate with `offset` |
| Polymarket Gamma API | Treating `outcomePrices` as always present and numeric | Field sometimes returns as a JSON string needing parsing (already handled in codebase), but can also be null or empty list for markets with unusual structure |
| Polymarket CLOB API | Using `/prices` for polling without tracking rate limits | Rate limit is 1,500 req/10s — generous for a single-user poller but important to track if fetching per-market prices individually instead of batching |
| Polymarket CLOB API | Assuming auth is not needed for read endpoints | CLOB API requires API key even for read operations (order book, prices); Gamma API is public read |
| SQLAlchemy asyncio | Using `scoped_session` from SQLAlchemy 1.x patterns | `async_scoped_session` requires explicit `.remove()` on task completion; failure to call it leaks session and task handles from the registry |
| SQLAlchemy asyncio | Creating a new engine per polling cycle | Engine creation is expensive and creates a new connection pool; create once at startup and reuse |
| Discord webhook | Sending a message per signal in a burst | Discord rate-limits webhooks at 30 messages/minute per channel; if multiple signals fire simultaneously, queue and batch them |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Fetching full market metadata on every price polling cycle | DB and API traffic scales with market count × poll frequency | Cache market metadata (question, end_date, strategy eligibility) after first fetch; only re-fetch if metadata changes | At ~500 tracked markets with 1-minute polling |
| No index on `signals(market_id, strategy, status)` | Deduplication check (`SELECT WHERE market_id=X AND strategy=Y AND status='open'`) does a sequential scan | Add composite index at schema creation | At ~10,000 signal rows |
| Storing price snapshots without a pruning strategy | `price_snapshots` table grows unboundedly; disk fills | Add a scheduled cleanup job or DB partition; keep only last 24–48 hours of snapshots per market | At ~1,000 markets × 1-minute polling = 1.4M rows/day |
| Polling all active markets for price in a single concurrent batch | httpx connection pool exhaustion; API rate limit spike | Use `asyncio.Semaphore` to limit concurrent outbound requests; batch CLOB price calls for multiple markets in one request if the API supports it | At > 50 concurrent market price fetches |
| Asyncio loop blocked by sync DB calls | Event loop freezes; polling intervals slip; all tasks stall | Use only `await session.execute()` and async ORM calls; never call synchronous SQLAlchemy methods inside the event loop | Immediately if sync calls are made in async context |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Logging the Discord webhook URL | Webhook URLs act as credentials; logging them exposes them to log aggregation systems | Never log the full webhook URL; log only a masked version or just the webhook channel ID |
| Storing Polymarket API key in source code or `.env` committed to git | Key exposure allows unauthorized order placement on the user's account | Use `.env` loaded by pydantic-settings, ensure `.env` is in `.gitignore`, add a check in CI |
| No input validation on market IDs in URL paths | Path traversal or injection if market IDs are ever sourced from external input | Validate that market IDs match expected format (alphanumeric/UUID) before constructing API URLs |

---

## "Looks Done But Isn't" Checklist

- [ ] **Signal deduplication:** Detector code exists, but verify there is a DB query that checks for an existing open signal before inserting a new one. A working detector without dedup will spam Discord on first run.
- [ ] **Resolution tracking:** Signals table exists, but verify there is a scheduled job or hook that actually queries Polymarket for resolved markets and updates signal outcomes. It won't happen automatically.
- [ ] **N/A exclusion in accuracy reports:** Accuracy query exists, but verify it excludes `resolved_na` signals from the win-rate denominator. Without this, N/A markets count as losses.
- [ ] **Pagination in market discovery:** Market listing works for the first 100 markets, but verify the discovery loop iterates `offset` until an empty page is returned.
- [ ] **Polling loop survives exceptions:** Loop runs in dev with stable network, but verify the inner body is wrapped in a try/except that logs and continues rather than propagates and kills the loop.
- [ ] **Price at signal time is stored:** Signal alert fires correctly, but verify `price_at_signal` is written to the DB at creation time. Without it, retrospective accuracy analysis has no baseline.
- [ ] **SQLAlchemy sessions close on every cycle:** Session is created per cycle, but verify `async with AsyncSession() as session:` is used (not a bare `session = AsyncSession()` that never closes). Connection leaks won't surface until the process has been running for hours.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| No price_at_signal stored — accuracy analysis impossible | HIGH | Rewrite signal schema with migration; historical signals have no baseline and must be dropped or treated as unscoreable; start fresh data collection |
| Signal dedup not implemented — Discord spam | LOW | Add dedup check, mark existing duplicate signals as superseded in DB, throttle future alerts |
| Resolution tracking breaks on N/A markets | MEDIUM | Add NA status to enum with migration; re-fetch and re-score recent resolved markets; exclude NA from historical accuracy |
| Polling loop dies silently | LOW | Add exception wrapping + heartbeat Discord message; restart process manually for now; automate with systemd or supervisord |
| Threshold parameters wrong — no edge found | MEDIUM | Change thresholds at module level, redeploy; historical signals at old thresholds must be tagged with old threshold version for comparison |
| Connection leaks cause DB pool exhaustion after hours | MEDIUM | Restart process; fix session lifecycle to use context managers; add connection pool monitoring |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Longshot bias edge may not exist | Signal detection phase | Build accuracy reporting before claiming strategy works; measure calibration after 30+ resolutions |
| Time decay fires on live-event markets | Signal detection phase | Unit test detector with markets that have broad event windows; add trend filter before shipping |
| N/A / disputed resolution corrupts accuracy | DB schema phase | Schema review: resolution enum includes NA and DISPUTED states before any signal is written |
| Asyncio task swallows exceptions silently | Polling loop phase | Integration test: inject a failing mock and verify loop continues and logs the error |
| Signal deduplication missing | Signal detection + DB schema phase | Test: run detector twice on same market state; verify only one open signal in DB |
| Performance reporting schema insufficient | DB schema phase | Write the three accuracy queries before finalizing schema; if queries don't work cleanly, fix schema |
| Pagination not implemented in discovery | Market discovery phase | Test: mock API to return exactly 100 markets on first page and 10 on second; verify both pages fetched |
| SQLAlchemy session leaks | DB layer phase | Run for 4+ hours in dev; monitor connection count with `SELECT count(*) FROM pg_stat_activity` |
| Discord rate limit hit on burst signals | Notification phase | Simulate 10 simultaneous signals; verify messages are queued rather than dropped |
| `closed` vs `resolved` state confusion | Resolution tracking phase | Document state machine and assert `resolved: true` is checked, not just `closed: true`, before scoring |

---

## Sources

- [Exploring Decentralized Prediction Markets: Accuracy, Skill, and Bias on Polymarket (SSRN 2025)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5910522) — no general longshot bias on Polymarket
- [Systematic Edges in Prediction Markets — QuantPedia](https://quantpedia.com/systematic-edges-in-prediction-markets/) — longshot bias edge sizes and sensitivity to volume
- [The Favourite-Longshot Bias is Not a Bias — DataGolf](https://datagolf.com/fav-longshot-not-a-bias) — mathematical argument for why the bias may be structural, not exploitable
- [Risk Aversion and Favourite-Longshot Bias — Whelan 2024, Economica](https://onlinelibrary.wiley.com/doi/10.1111/ecca.12500) — bias stronger in lower-volume markets
- [Polymarket API Rate Limits — Official Docs](https://docs.polymarket.com/quickstart/introduction/rate-limits) — Gamma API 300 req/10s, CLOB 1,500 req/10s
- [How Are Prediction Markets Resolved — Polymarket Help](https://help.polymarket.com/en/articles/13364518-how-are-prediction-markets-resolved) — UMA optimistic oracle, 2-hour dispute window, bond mechanics
- [API Rate Limit — Burst vs Throttle Issue #147 — Polymarket py-clob-client GitHub](https://github.com/Polymarket/py-clob-client/issues/147) — sliding window behavior
- [/prices-history returns empty data for resolved markets Issue #216 — py-clob-client GitHub](https://github.com/Polymarket/py-clob-client/issues/216) — data quality gap for resolved markets
- [How We Discovered a Connection Leak in Async SQLAlchemy — Medium](https://medium.com/@har.avetisyan2002/how-we-discovered-and-fixed-a-connection-leak-in-async-sqlalchemy-during-chaos-testing-bf45acf65559) — session scoping memory leak pattern
- [SQLAlchemy async_scoped_session docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) — remove() requirement
- [Asyncio tasks and exception handling — Python discussion](https://discuss.python.org/t/asyncio-tasks-and-exception-handling-recommended-idioms/23806) — recommended idioms for task exception handling
- [PEP 789 — task cancellation bugs in asyncio](https://peps.python.org/pep-0789/) — task cancellation and retry decorator interaction
- [Polymarket governance attack March 2025 — Mitrade](https://www.mitrade.com/insights/news/live-news/article-3-720697-20250326) — oracle manipulation forcing fake resolution
- Codebase: `.planning/codebase/CONCERNS.md` — existing identified issues with Polymarket client

---

*Pitfalls research for: Arbiter — prediction market signal detection system*
*Researched: 2026-02-22*
