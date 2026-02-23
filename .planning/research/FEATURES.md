# Feature Research

**Domain:** Prediction market signal detection (Polymarket — longshot bias + time decay)
**Researched:** 2026-02-22
**Confidence:** MEDIUM — academic backing for bias existence; specific thresholds calibrated from community practice and backtesting reports, not controlled experiments on Polymarket data

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features that must work for the milestone to be useful at all. Missing any of these = the signal system doesn't function.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Longshot bias detector | Core strategy #1 — the reason the milestone exists | MEDIUM | Price threshold logic is simple; the tricky part is filtering noise and avoiding duplicate signals |
| Time decay detector | Core strategy #2 — companion to longshot bias | MEDIUM | Requires parsing end_date and computing hours-to-expiry; already have the field in Market model |
| Signal persistence | Without storage, there's nothing to track or report on | MEDIUM | New DB table; extends existing planned DB layer |
| Discord alert on new signal | Expected parity with existing arb alert design | LOW | Pattern already established by BaseNotifier/DiscordNotifier |
| Resolution detection | Without resolution tracking, signal accuracy is unmeasurable | MEDIUM | Gamma API already returns `resolved=True` and converging outcome_prices; needs polling loop |
| Resolution outcome recording | Which way a market resolved (yes or no won) | LOW | Derivable from `outcome_prices` when `resolved=True` — `["1.0", "0.0"]` = yes won |
| Signal accuracy report | The whole point of tracking — was this strategy profitable? | LOW | SQL aggregate query per strategy; not complex to compute |

### Differentiators (Competitive Advantage)

Features that separate a disciplined signal tool from a noisy alert bot.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Cooldown / dedup per market | Prevents re-firing the same signal when price oscillates around threshold | LOW | One column: `last_signal_at`; skip if fired within cooldown window |
| Minimum liquidity filter | Low-liquidity markets have erratic prices and fake signals; filtering by liquidity improves signal quality dramatically | LOW | Gamma API returns `liquidityCLOB`; add a config threshold (default ~$1,000) |
| Minimum volume filter | Thin markets can spike briefly without real edge; volume acts as a quality gate | LOW | Market model has `volume` field; configurable threshold |
| Confidence score on each signal | Show users why a signal fired (price, threshold, hours-to-expiry, liquidity) so they can sanity-check before acting | LOW | Part of signal record; enriches Discord message |
| Per-strategy accuracy trend | Not just "X% accuracy all-time" but "last 30 signals" trend — shows if a strategy is degrading | MEDIUM | Window function over signals table; add after 50+ signals accumulate |
| Signal state machine (active / expired / resolved) | Signals should transition through states so stale alerts don't clutter reports | LOW | Single `status` enum column: `active`, `expired`, `resolved_correct`, `resolved_incorrect` |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Historical backtesting against past Polymarket data | "We could validate the strategy before going live" | No official historical fill API. Gamma API doesn't expose resolved market history in a queryable bulk format. Building a scraper creates maintenance overhead and data quality risk. The edge may also not transfer to live conditions. | Accept that live tracking is the validation method. Collect signals now, evaluate on resolution. This is explicitly decided in PROJECT.md. |
| Continuous re-alerting on active signals | "Remind me about opportunities I haven't acted on" | Prediction markets move fast; re-alerting creates noise and trains the user to ignore alerts. Also unnecessary for a signals-only (no execution) system. | Include signal age in Discord embed if needed. One alert per signal (with cooldown). |
| Kelly criterion position sizing | "Optimize bet size based on edge and bankroll" | Trade execution is explicitly out of scope. Adding position-size logic now over-engineers a signals-only tool. | Document the Kelly formula for each strategy in the alert message as a reference without computing it. |
| Signal confidence scoring via LLM | "Use Claude to evaluate whether each signal is real" | LLM calls per signal are expensive and introduce latency. Per PROJECT.md: LLM calls should be reserved for expensive operations only. The signals are deterministic threshold checks — no LLM needed. | Use structured thresholds. If human review is needed, the Discord message provides the raw data to judge manually. |
| Multi-market portfolio view | "Show my aggregate exposure across all active signals" | No execution, no positions — there is nothing to aggregate. This requires building a portfolio layer before execution exists. | Show per-strategy signal counts in the accuracy report. |

---

## Strategy-Specific Parameters

### Longshot Bias Detector

**What it detects:** Markets where the favored outcome (high yes_price) is likely underpriced due to retail over-weighting of the longshot side.

**Academic basis:** Snowberg & Wolfers (2010, NBER w15923) document systematic favorite-longshot bias in betting markets. A 2025 Kalshi study (UCD Economics WP2025_19) confirms: sub-10¢ contracts lose 60%+ value; above 50¢ earns +1.9% after fees. Multiple community backtests report 58-62% win rate with 2-3% expected edge for systematic favorites strategies.

**Key parameters:**

| Parameter | Recommended Default | Rationale |
|-----------|---------------------|-----------|
| `longshot_min_yes_price` | 0.75 (75%) | Below 75% the favorite isn't dominant enough; the "edge" is contested |
| `longshot_max_yes_price` | 0.95 (95%) | Above 95% the spread is tiny and fees eliminate the edge |
| `longshot_min_liquidity` | 1000 (USDC) | Low-liquidity markets have unreliable prices |
| `longshot_min_volume` | 5000 (USDC) | Minimum traded volume for the market to be worth signaling |
| `longshot_signal_cooldown_hours` | 24 | Don't re-fire if a signal was already issued for this market in the last 24h |

**Detection logic:**
```
if 0.75 <= market.yes_price <= 0.95
   and market.liquidity >= min_liquidity
   and market.volume >= min_volume
   and not recently_signaled(market.id, cooldown_hours=24):
   fire_signal(market, strategy="longshot_bias", signal_price=market.yes_price)
```

**What "correct" means:** The yes outcome resolves. `outcome_prices = ["1.0", "0.0"]` after resolution.

**Confidence note:** The 75-95% range is derived from first principles (academic bias range) and community convention, not from a controlled Polymarket-specific experiment. LOW confidence on exact thresholds — treat as starting point, adjust based on accumulated results.

---

### Time Decay Detector

**What it detects:** Near-expiry markets where the "no" outcome is mispriced because retail bettors ignore low-excitement positions as expiry approaches.

**Academic/practical basis:** Analogous to options theta decay — time value accelerates toward expiry. The datawallet article documents a concrete example: Fed rate decision market with 3 days to expiry yielding ~5.2% on a clear-outcome "no" position. No prediction market-specific academic paper was found for the exact threshold; this is inferred from options theta literature + community practice.

**Key parameters:**

| Parameter | Recommended Default | Rationale |
|-----------|---------------------|-----------|
| `time_decay_max_hours_to_expiry` | 72 (3 days) | Decay becomes meaningful within 72h; signals beyond that are premature |
| `time_decay_min_yes_price` | 0.80 (80%) | The event must be clearly headed to "no" resolution — high yes_price means "no" is near-certain |
| `time_decay_max_yes_price` | 0.97 (97%) | Cap to avoid markets already at near-certainty where there's no room to move |
| `time_decay_min_liquidity` | 500 (USDC) | Lower than longshot threshold — near-expiry markets have naturally declining liquidity |
| `time_decay_signal_cooldown_hours` | 12 | Re-check more frequently near expiry since the window closes fast |

**Detection logic:**
```
hours_to_expiry = (market.end_date - now()).total_hours()
if 0 < hours_to_expiry <= 72
   and 0.80 <= market.yes_price <= 0.97
   and market.liquidity >= min_liquidity
   and not recently_signaled(market.id, cooldown_hours=12):
   fire_signal(market, strategy="time_decay", signal_price=market.no_price, hours_to_expiry=hours_to_expiry)
```

**What "correct" means:** The "no" outcome resolves (yes did not happen). `outcome_prices = ["0.0", "1.0"]` after resolution. Or equivalently: yes resolves to 0.

**Confidence note:** The 72-hour window and 80% threshold are MEDIUM confidence — consistent with options theta literature and community practice but not validated against Polymarket data specifically. The 12h cooldown is LOW confidence — adjust based on observed signal churn in live operation.

---

### Signal Storage Schema

**Core table: `signals`**

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID (PK) | Primary key |
| `market_id` | VARCHAR | Polymarket market ID (foreign key to markets table if it exists) |
| `market_question` | TEXT | Cached at signal time — market may close before we need to display |
| `strategy` | VARCHAR | `"longshot_bias"` or `"time_decay"` — enum-validated |
| `signal_price` | FLOAT | yes_price at signal fire time (for longshot_bias) or no_price (for time_decay) |
| `signal_direction` | VARCHAR | `"yes"` or `"no"` — which side the signal recommends |
| `hours_to_expiry` | FLOAT | Hours from signal_fired_at to market end_date — enriches reporting |
| `liquidity_at_signal` | FLOAT | Market liquidity when signal fired — quality indicator |
| `status` | VARCHAR | `"active"` / `"expired"` / `"resolved_correct"` / `"resolved_incorrect"` / `"void"` |
| `fired_at` | TIMESTAMP | When signal was generated |
| `resolved_at` | TIMESTAMP | When resolution was detected (nullable until resolved) |
| `resolution_outcome` | VARCHAR | `"yes"` or `"no"` — which side actually won (nullable until resolved) |
| `correct` | BOOLEAN | Whether signal_direction matches resolution_outcome (nullable until resolved) |

**Resolution detection approach:** Poll Gamma API for markets with active signals. When `market.resolved == True`, read `outcome_prices`: if first value is `"1.0"`, yes won; if `"0.0"`, no won. Compute `correct = (signal_direction == resolution_outcome)`. Update `status`, `resolved_at`, `resolution_outcome`, `correct`.

---

### Performance Reporting

**Minimum viable report:**
```
Strategy: longshot_bias
  Total signals: 47
  Resolved: 31
  Correct: 21 (67.7% accuracy)
  Pending: 16

Strategy: time_decay
  Total signals: 23
  Resolved: 14
  Correct: 10 (71.4% accuracy)
  Pending: 9
```

**Key metrics per strategy:**
- Total signals fired
- Resolution rate (resolved / total) — shows how mature the dataset is
- Accuracy rate (correct / resolved) — primary quality indicator
- Mean hours-to-expiry at signal time — shows if time_decay is firing too early or late

**Minimum sample threshold:** Do not display accuracy rate until at least 10 resolved signals per strategy. Too few samples produce misleading percentages.

**Confidence intervals:** Not required for v1. Add once sample sizes exceed ~50 per strategy.

---

### Discord Alert Format

Each signal alert should include enough data to act on without clicking through.

**Fields to include:**
- Market question (truncated to ~100 chars)
- Strategy name (human-readable: "Longshot Bias" / "Time Decay")
- Signal recommendation: "BUY YES" or "BUY NO"
- Current price at signal time
- Hours to expiry (critical for time decay signals)
- Market URL (Polymarket link using market ID)
- Liquidity at signal time (quality indicator)

**Fields to omit:**
- Signal ID (internal tracking detail, not useful to human reader)
- All historical accuracy stats in the alert itself (clutters the alert; belongs in a separate report command)

---

## Feature Dependencies

```
Signal storage (DB table)
    └──required by──> Longshot bias detector (needs to store signals)
    └──required by──> Time decay detector (needs to store signals)
    └──required by──> Resolution tracking (reads from signals table)
    └──required by──> Performance reporting (aggregates signals table)

Market model (existing: closed, resolved, end_date, outcome_prices)
    └──required by──> Time decay detector (needs end_date for hours-to-expiry)
    └──required by──> Resolution tracking (needs resolved + outcome_prices)

Polling loop (continuous market refresh)
    └──required by──> Longshot bias detector (needs current prices)
    └──required by──> Time decay detector (needs current prices + end_date)
    └──required by──> Resolution tracking (detects when resolved flips to True)

Discord notifier (existing pattern: BaseNotifier)
    └──required by──> Signal alert (implements notify() with signal payload)

Longshot bias detector
    └──enhances──> Performance reporting (provides data)

Time decay detector
    └──enhances──> Performance reporting (provides data)

Resolution tracking
    └──required by──> Performance reporting (provides correct/incorrect outcomes)
```

### Dependency Notes

- **Signal storage requires the DB layer:** The DB layer (PostgreSQL, SQLAlchemy, Alembic) is listed as a pending requirement in PROJECT.md. Signal storage cannot exist without it. The signals table is a new addition to the planned schema.
- **Time decay detector requires end_date parsing:** The existing `Market.end_date` is stored as an ISO string (`Optional[str]`). The detector will need to parse it to a datetime for arithmetic.
- **Resolution tracking shares the polling loop:** Resolution can be checked in the same polling loop that fetches prices. No separate loop needed. When `market.resolved` transitions from `False` to `True`, trigger resolution recording.
- **Performance reporting is read-only:** It queries the signals table and does not depend on any live API data. It can run as a CLI command or periodic cron separately from the main polling loop.

---

## MVP Definition

### Launch With (v1 — this milestone)

Minimum viable signal system that captures live data and validates the concept.

- [ ] Signal storage table (PostgreSQL, SQLAlchemy model, Alembic migration)
- [ ] Longshot bias detector (configurable 75-95% yes_price window, liquidity + volume filters)
- [ ] Time decay detector (configurable hours-to-expiry window, yes_price filter)
- [ ] Signal dedup / cooldown per market per strategy
- [ ] Discord alert on new signal (question, strategy, recommendation, price, hours-to-expiry, link)
- [ ] Resolution detection in polling loop (detect when `resolved=True`, determine winner from outcome_prices)
- [ ] Resolution recording (update signal record with outcome + correct bool)
- [ ] Performance report (CLI command: accuracy rate per strategy, total/resolved/correct counts)

### Add After Validation (v1.x)

Add after 30+ resolved signals per strategy (enough data to evaluate).

- [ ] Minimum sample threshold gate — suppress accuracy % until 10+ resolved signals
- [ ] Per-strategy accuracy trend (last-N window, not just all-time)
- [ ] Signal status transitions (active → expired if market closed without resolution)
- [ ] Liquidity and volume reported in Discord message

### Future Consideration (v2+)

Defer until the two core strategies show measurable edge.

- [ ] Additional strategies (whale copy trading, calibration vs Metaculus)
- [ ] Confidence intervals on accuracy rate
- [ ] Alert fatigue management (rate limiting Discord messages if many signals fire simultaneously)
- [ ] Strategy parameter auto-tuning based on accuracy feedback

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Signal DB table | HIGH | MEDIUM | P1 |
| Longshot bias detector | HIGH | LOW | P1 |
| Time decay detector | HIGH | LOW | P1 |
| Signal dedup / cooldown | HIGH | LOW | P1 |
| Discord alert | HIGH | LOW | P1 |
| Resolution detection + recording | HIGH | MEDIUM | P1 |
| Performance report (CLI) | MEDIUM | LOW | P1 |
| Liquidity / volume filter | HIGH | LOW | P1 — bakes into detector, not a separate feature |
| Per-strategy accuracy trend | MEDIUM | MEDIUM | P2 |
| Signal status state machine | LOW | LOW | P2 |
| Confidence intervals | LOW | MEDIUM | P3 |

---

## Competitor Feature Analysis

No direct competitors were found that expose their full feature set. The closest reference tools are:

| Feature | prediction-market-backtesting (evan-kolberg/GitHub) | volfefe (razrfly/GitHub) | Our Approach |
|---------|------|------|------|
| Signal strategy type | Backtesting engine (offline) | Smart money detection | Live signal generation, forward-only |
| Resolution tracking | Manual / offline | Not documented | Automated via API polling |
| Accuracy reporting | Backtest metrics | Not documented | Per-strategy live accuracy from resolved signals |
| Alert delivery | None | None | Discord webhook |
| Longshot bias detection | Supported via custom strategies | Not documented | Built-in with configurable thresholds |
| Time decay detection | Not documented | Not documented | Built-in with hours-to-expiry parameter |

---

## Sources

- Snowberg & Wolfers (2010), "Explaining the Favorite-Longshot Bias: Is it Risk-Love or Misperceptions?" NBER WP w15923 — [link](https://www.nber.org/system/files/working_papers/w15923/w15923.pdf) (HIGH confidence — peer-reviewed)
- UCD Economics WP2025_19, "Makers and Takers: The Economics of the Kalshi Prediction Market" — [link](https://www.ucd.ie/economics/t4media/WP2025_19.pdf) (HIGH confidence — working paper, quantified thresholds)
- QuantPedia, "Systematic Edges in Prediction Markets" — [link](https://quantpedia.com/systematic-edges-in-prediction-markets/) (MEDIUM confidence — practitioner analysis)
- DataWallet, "Top 10 Polymarket Trading Strategies" — [link](https://www.datawallet.com/crypto/top-polymarket-trading-strategies) (MEDIUM confidence — community analysis with concrete examples)
- GitHub: evan-kolberg/prediction-market-backtesting — [link](https://github.com/evan-kolberg/prediction-market-backtesting) (MEDIUM confidence — open source reference)
- Polymarket Developer Docs — [link](https://docs.polymarket.com) (HIGH confidence — authoritative for API field definitions)
- Polymarket GitHub: agents/polymarket/gamma.py — [link](https://github.com/Polymarket/agents/blob/main/agents/polymarket/gamma.py) (HIGH confidence — first-party field reference)

---

*Feature research for: Polymarket prediction market signal detection (longshot bias + time decay)*
*Researched: 2026-02-22*
