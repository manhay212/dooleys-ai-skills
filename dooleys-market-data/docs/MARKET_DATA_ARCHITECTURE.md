# Market Data Layer — Architecture & Design

**Created:** 2026-06-07
**Status:** Proposed (Phase 0)
**Author:** Drafted for Man Hay Hong / Hermes ecosystem
**Recommended canonical destination:** `~/.hermes-backup-repo/docs/my-agentic-setup/MARKET_DATA_ARCHITECTURE.md`
**Companion docs:** `MARKET_DATA_IMPLEMENTATION_PLAN.md`, `MARKET_DATA_SKILL_SPEC.md`

> This is a design document only. It does not modify the live system. Execution steps live in the implementation plan.

---

## 1. Purpose & Goal

The Hermes investment specialist runs on an LLM with a stale knowledge cutoff (~Q2 2025). It can reason, but it cannot *see where the world is today*. Its only live signal is a Twitter digest — too narrow to establish correlations or detect regime shifts.

This initiative gives the agent **structured, historical, queryable visibility into market data** so it can do the one thing it currently cannot: **identify potential turning points in trends, assess how close/far we are from one, and cite the data that supports the read** — in service of mid-to-long-term investing (not intraday, swing, or social-media hype).

This requires a *quantitative history*, not a point-in-time web lookup. You cannot judge "how far is the current reading from a turning point" without a distribution to compare against.

---

## 2. The Core Decision: Numbers vs. Words

The single most important architectural choice. Two kinds of information serve investing, and they need **different tools**:

| Type | Examples | Right tool | Why |
|------|----------|-----------|-----|
| **Quantitative / time-series** | Prices, yields, M2, Fed balance sheet, oil curve, ratios, flows | **SQLite (`market-data/`)** | Needs history, math, distributions, determinism |
| **Qualitative / event-driven** | News, geopolitics, wars, central-bank speeches, regulation, KOL views | **Web-search + `docs/` + `wiki/` + Twitter** | Unstructured, narrative; a price DB is the wrong shape |

**Storing news in a database is an anti-pattern.** The existing three-layer knowledge system (memory / docs / wiki) plus on-demand web search already handles words well. What is missing is the *numbers* layer.

### The bridge: an `events` table
A small structured table logs *dated macro events* (CPI = 3.1%, FOMC cut 25bp, rate decision) so the agent can **align "what happened" with price moves on a timeline**. The narrative still lives in `docs/`/`wiki/`; only the structured fact + a pointer is stored. `docs/` is words; `market-data/` is numbers; `events` is the join key between them.

---

## 3. Should We Store Price Data in SQLite? (Your Question, Answered)

**Yes — for numbers. Decisively.**

### Pros (why it's worth it)
- **Distributions & percentiles.** "MOVE is 145" is noise. "MOVE is at the 96th percentile of its 30-year range, z-score +2.1" is signal. Only a local history makes this possible.
- **Cross-asset math.** Copper/gold ratio, MOVE→VIX spread, GLD-shares/gold-price ratio, BTC vs net-liquidity — these are computed, not searched.
- **Determinism, no hallucinated figures.** An LLM reading a web page misreads and invents numbers. A DB is ground truth. This alone justifies the build.
- **Offline, instant, no query-time rate limits.** Analysis runs locally over a single file.
- **Reproducibility.** The same query yields the same signal every time — essential for tracking a thesis over months.
- **Cheap, portable, migration-safe.** One file; already inside the backup/restore discipline.

### Cons (and how each is managed)
- **Storage growth** → negligible (see §4). Not a real concern.
- **Ingestion correctness / data revisions** → macro series get revised; use latest-revision now, ALFRED vintages in Phase 2. Use **adjusted close** for splits/dividends.
- **Maintenance over years** → modular per-source adapters + `doctor` command + graceful degradation so one broken source can't sink the system.
- **Coverage gaps** → "backfill as far back as available" fallback when 30y isn't there.
- **It's numbers-only** → by design. Words go elsewhere (§2).

### The decisive framing
The DB earns its place precisely where web search fails: **historical context and computation.** Where web search already wins — fresh narrative — we keep using it. Hybrid, not either/or.

---

## 4. Sizing on the Laptop (400 GB free / 16 GB RAM / 4 cores)

**Storage is a non-issue.** The math:

- 30y daily ≈ ~7,560 rows/series. OHLCV row ≈ ~90 bytes → **~680 KB/series**; single-value macro series ≈ ~265 KB.
- **500 series** (every index, commodity, FX, major ETF, crypto, *and* every KOL macro indicator) ≈ **~340 MB raw, ~700 MB with indexes.**
- **2,000 series** (extravagant) ≈ **~2–3 GB.** Daily updates add ~tens of MB/year.

On 400 GB free that is a rounding error. SQLite is disk-based and streams; loading a full 30y series into pandas is a few hundred KB. 16 GB / 4 cores is overkill.

### The real constraints (which are NOT disk)
1. **Context window, not storage.** The agent must never read a 7,560-row series into context (tool output caps ≈ 50 KB / 2,000 lines; file read ≈ 100 KB). → The skill returns **computed summaries**, never raw dumps. This is the true scalability discipline. (See §6.)
2. **API rate limits during the one-time 30y backfill** → backfill is resumable, batched, UPSERT-idempotent.
3. **Git ↔ binary-DB bloat** → never commit a growing `.db` daily. → "config is source of truth, DB is a cache" (§5).

---

## 5. Directory Layout — `market-data/`

Placed at the same level as `docs/`, as requested:

```
~/.hermes-backup-repo/market-data/
├── README.md                    # human + LLM dashboard for the data layer
├── DATA_DICTIONARY.md           # every table, series, unit, source, gotcha
├── config/                      # ← modular control plane (git-tracked = source of truth)
│   ├── sources.yaml             # provider adapters: base URLs, auth env-var names, rate limits
│   └── catalog.yaml             # series registry — per asset class; add/remove tickers HERE
├── db/
│   ├── market.db                # SQLite (ohlcv + observations + events)   ← .gitignored
│   └── schema.sql               # committed; the DB is recreatable from this + catalog
├── exports/
│   └── market_snapshot.parquet  # periodic compact snapshot (fast restore; avoids re-backfill)
└── logs/
    └── ingest_log.jsonl         # per-series last run / status            ← .gitignored
```

### Governing principle: **the data is a cache; the config is the source of truth**
`catalog.yaml` + `sources.yaml` fully specify the DB, so it is always rebuildable. This resolves the git-binary problem cleanly:

- **Git-track:** config, schema, data dictionary, README (tiny text, diffs beautifully).
- **Git-ignore:** `market.db`, logs.
- **Back up the data** via a periodic **Parquet snapshot** → restore imports it in seconds; if it's missing, re-run backfill from config. Honors "zero data loss" without bloating the repo.

### Separation of concerns: engine vs. catalog
- The **skill** (`dooleys-market-data`) is a generic *engine* and lives in the public `dooleys-ai-skills` repo — no personal data.
- **`catalog.yaml`** (your chosen tickers) lives in `market-data/config/`, **not** in the skill repo. This keeps the skill public-ready (your stated principle) and the engine reusable across anyone's catalog.

---

## 6. Schema (long/tidy — adding an asset class needs no schema change)

| Table | Holds | Key columns |
|-------|-------|-------------|
| `series` | The registry (one row per tracked series) | `series_id, ticker, name, asset_class, source, source_symbol, unit, frequency, table_kind, first_available, last_updated, status, trigger_levels (JSON), notes` |
| `ohlcv` | Tradable assets | `series_id, date, open, high, low, close, adj_close, volume` — PK `(series_id, date)` |
| `observations` | Single-value series (macro, rates, flows) | `series_id, date, value` — PK `(series_id, date)` |
| `events` | Structured macro/market events (the bridge) | `date, category, title, value, prior, consensus, surprise, source_url, doc_ref` |
| `ingest_runs` | Operational log | `run_id, series_id, ts, rows_added, from_date, to_date, status, error` |

- **Adding an asset class** = a new `asset_class` value in `catalog.yaml`. No DDL.
- **Adding a ticker** = append to `catalog.yaml`, run `sync-catalog`, then `backfill --ticker X`.
- **Removing a ticker** = set `status: deprecated` (keeps history) or remove + optional purge.
- `trigger_levels` stores the KOL thresholds (e.g., MOVE `{caution:120, danger:140}`, 10Y `{dysfunction:5.0}`, BTC `{invalidation:60000}`) so the agent can compute **distance-to-trigger**.

**The agent never reads raw tables.** It calls the skill's `query` interface, which returns compact computed summaries (latest, %Δ over 1d/1w/1m/3m/1y/5y, 52-week hi/lo, percentile-vs-history, z-score, ratios). Raw rows stay on disk.

Full DDL: see `MARKET_DATA_SKILL_SPEC.md`.

---

## 7. Data Sourcing Matrix (Free + Free-Key)

Your choice: free sources + free API keys. Coverage map and honest gaps:

| Domain | Source | Auth | Notes |
|--------|--------|------|-------|
| Rates, curve, Fed (H.4.1: WALCL/RRP/TGA/reserves), M2, monetary base, CPI/PCE, breakevens, real yields, jobs, GDP, IP, HY/IG OAS, VIX, FX, financial-conditions | **FRED** | Free key | The workhorse. 30y+, clean JSON API, hundreds of series |
| TGA daily, total debt, auctions, customs/tariff receipts | **US Treasury FiscalData** | None | Daily Treasury Statement etc. |
| WTI/Brent spot, crude/gasoline/distillate inventories, refinery utilization, SPR | **EIA API v2** | Free key | Weekly petroleum status |
| Equity indices, ETFs, commodities, FX (OHLCV, ~30y) | **Stooq** | None | Reliable CSV download; use adjusted close |
| BTC/ETH/majors, total mcap, stablecoin supply (USDT/USDC) | **CoinGecko** | Free/demo key | For long daily history, fall back to exchange klines (Binance/Coinbase) |
| Political odds (midterms, Fed, etc.) | **Polymarket API** | None | Optional |
| **MOVE index** | Yahoo `^MOVE` / proxy | — | ⚠️ Best-effort; flag if unavailable |
| **HK housing (Centaline CCL, RVD)** | Scrape / manual | — | ⚠️ No clean API; weekly/monthly manual or scraping adapter |
| **Shipping (Freightos FBX, Baltic Dry, VLCC)** | Partial | — | ⚠️ Mostly paywalled; best-effort/proxy |
| **Options / dealer-gamma / CME basis** | — | — | ❌ Not free as time-series → web-search/manual; consistent with free-tier choice |
| **Central-bank gold flows (Goldhub)** | — | — | ❌ No free API → treat as qualitative/event, web-search |
| News, geopolitics, wars, regulation | Web-search + free tools | — | Liveuamap, ADS-B Exchange, MarineTraffic, Sentinel Hub, Trading Economics (see `docs/investment/macro/FREE_DATA_TOOLS.md`) + Twitter ingestion |

### The KOL files are your seed catalog
`docs/investment/kol/arthur-hayes/KEY_INDICATORS.md` and `.../make-investment-easy/KEY_INDICATORS.md` already enumerate the series, their sources, **and trigger levels**. Phase 0 seeds `catalog.yaml` from them and stores the trigger levels on each series. You already did the taxonomy work; this wires it to live data.

### Longevity choice
Prefer **stable, documented HTTP CSV/JSON endpoints** (FRED, Stooq, EIA, Treasury, CoinGecko) over fragile scraping libraries. `yfinance` is a *fallback only*. Per-source adapters mean one breaking source degrades gracefully instead of breaking the system.

---

## 8. Automation (mirrors existing cron patterns)

| Job | Type | When | What |
|-----|------|------|------|
| **Daily ingest** | `no_agent` script | ~06:00 HKT | `market_data.py update --all` + Parquet export. Deterministic, cheap. Failures logged. |
| **Weekly turning-point briefing** | Agent (investment profile) → WhatsApp | Mon 09:00 HKT | Query DB dashboard (latest + stats + ratios + percentile + distance-to-trigger), cross-reference KOL `KEY_INDICATORS`/`LATEST_VIEWS`, web-search the week's events, assess cycle position & proximity to turning points **with data cited**, end with "what to watch." |

The briefing is the **investment agent reasoning over the DB** — there is no pre-built signals module yet (consistent with your "data foundation only" choice). The DB makes the reasoning *grounded and quantitative* instead of vibes.

---

## 9. Knowledge Linkage (the "changes ripple" discipline)

`market-data/` becomes a new structured layer the agent must know about. Precise edits are specified in the implementation plan; in summary:

- **`profiles/investment/SOUL.md`** — new retrieval protocol: *before any analysis, query the market-data DB for current + historical context (don't recall/guess prices); use web only for narrative.*
- **`default/SOUL.md`** — add the data layer to Knowledge Architecture, add rows to the Cross-Reference Map, add to the investment Wiki-Awareness trigger.
- **`KNOWLEDGE_LINKAGE_STRATEGY.md`** — document `market-data/` as the "numbers" layer beside `docs/` ("words"), plus the add/remove-ticker protocol (analogous to the new-specialist checklist).
- **`SYSTEM_ARCHITECTURE.md`** — add to directory structure + upgrade-safety boundary (user-space, zero-risk).
- **`~/wiki/chief-of-staff/index.md`** — `#market-data` tags → location + skill.
- **`~/wiki/investment/`** — a dashboard page mapping KOL indicators ↔ DB tickers.
- **`README.md`, `SKILLS_MANAGEMENT.md`** — register the new layer, crons, and `dooleys-market-data` skill.
- **`backup-to-github.sh` / `restore-from-github.sh`** — symmetric snapshot handling + new skill symlink.
- **`.env.template`** — `FRED_API_KEY`, `EIA_API_KEY` (+ optional `COINGECKO_API_KEY`, `NASDAQ_DATA_LINK_API_KEY`).

---

## 10. What Was Missing From the Original Framing (Value-Add)

1. **Numbers-vs-words split** — the core insight; storing news in a price DB is wrong.
2. **Git/binary-DB bloat** — solved by config-as-source-of-truth + snapshot; never commit the `.db`.
3. **The real limit is the context window, not the disk** — the skill must return summaries, not dumps. This reframes "scalability."
4. **Data revisions** — macro series get revised (CPI, GDP, payrolls, even TGA). Latest-revision now; ALFRED vintages = Phase 2.
5. **Adjusted close** for splits/dividends on tradable assets.
6. **Backfill resumability/idempotency** under rate limits.
7. **Trigger-level wiring** — connect KOL thresholds to live data for distance-to-trigger.
8. **Timezone/calendar handling** — HK-based user, US close, crypto 24/7, weekly/monthly macro cadences.
9. **Source-failure resilience for the long haul** — stable endpoints, modular adapters, `doctor`.
10. **The analysis layer is where the real value lives** — deferred per your choice, but the seam is defined so Phase 2 (z-scores, regime classifier, Hayes-style composite net-liquidity index) slots in without rework.

---

## 11. Phasing

| Phase | Scope |
|-------|-------|
| **Phase 0 (this plan)** | Scaffold `market-data/`; build `dooleys-market-data` (FRED, Stooq, EIA, CoinGecko, Treasury adapters); seed `catalog.yaml` from KOL indicators + asset classes; run 30y backfill; wire daily-ingest + weekly-briefing crons; do all linkage; add keys. |
| **Phase 1** | `events` population discipline; HK-housing (Centaline CCL) + shipping best-effort adapters; trigger-breach "tripwire" alert cron (only pings when a threshold is crossed). |
| **Phase 2** | Derived-signals module (materialized z-scores, ratio percentiles, regime flags, composite net-liquidity index); ALFRED vintages for point-in-time backtesting; brokerage/portfolio integration. |

---

## 12. Success Criteria (Phase 0)

- The investment agent, asked "how close are we to a turning point in X," **queries the DB**, returns a percentile/z-score/distance-to-trigger with the actual numbers, and cross-references the relevant KOL framework — instead of guessing or only web-searching.
- A new ticker is added by editing `catalog.yaml` + one backfill command — no code change.
- The DB survives host migration via snapshot restore (or full rebuild from config) with zero manual data re-entry.
- The weekly briefing lands in WhatsApp, grounded in real data, every Monday.
