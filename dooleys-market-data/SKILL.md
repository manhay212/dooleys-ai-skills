---
name: dooleys-market-data
description: Query, backfill, and update the local market-data SQLite store (prices, macro indicators, rates, Fed liquidity, crypto, FX, energy). Use this skill whenever investment/market analysis needs current OR historical numbers — index/commodity/crypto prices, yields, Fed liquidity (WALCL/RRP/TGA/SRF), M2, CPI, oil & products, VIX/MOVE, cross-asset ratios & spreads, percentile/z-score context, or distance-to-trigger versus KOL thresholds. Returns compact computed summaries, never raw row dumps. Run `daily` once a day to refresh everything and write UPDATE_LOG.md.
version: 1.4.0
category: dooleys
required_environment_variables:
  - MARKET_DATA_DIR
  - FRED_API_KEY
  - EIA_API_KEY
  - COINGECKO_API_KEY
  - EODHD_API_KEY      # OPTIONAL — unset by default; setting it activates the dormant eodhd source
  - TWELVEDATA_API_KEY # OPTIONAL — unset by default; only used if referenced in a catalog chain
---

# Market Data Skill

Local, queryable market-data store for grounded investment analysis. The agent must use
this skill for NUMBERS (prices, yields, macro series, ratios, historical context) instead
of recalling them from training or guessing from a web page. Use web search for NARRATIVE
(news, geopolitics, regulation), not for figures this DB can provide.

## When to Use

- Any market/investment question needing a current or historical figure
- "How far is X from its range / a turning point / a KOL trigger level?"
- Cross-asset ratios (copper/gold) and rate spreads (2Y–EFFR, 10Y–2Y)
- Percentile / z-score / distance-to-trigger context
- Before any investment analysis or briefing: run `query dashboard` to ground yourself

## Prerequisites

- Python 3.8+ ; `pip install -r requirements.txt`
- `MARKET_DATA_DIR` points at the data dir (default `~/.hermes-backup-repo/market-data`)
- API keys in `~/.hermes/.env`: `FRED_API_KEY`, `EIA_API_KEY` (required), `COINGECKO_API_KEY` (optional)
- `EODHD_API_KEY` / `TWELVEDATA_API_KEY` are **optional and dormant** — the engine skips any source whose key is unset (see "Source failover & provenance" below). Nothing breaks without them.

> Run everything with the host's venv python, e.g.
> `~/.hermes/hermes-agent/venv/bin/python3 market_data.py …` (it has pandas/pyarrow/yfinance).

## Instructions for AI Agent

### DAILY MAINTENANCE — one command (this is what the cron should call)

```
python3 market_data.py daily
```

`daily` is the single, robust entry point: it updates every active series (with
per-series error + timeout isolation), writes a clean `UPDATE_LOG.md`, exports a Parquet
snapshot, and prints a JSON summary with a top-level `timestamp`. It never fails
all-or-nothing — one bad source is recorded and the rest still update. Use `--strict` to
exit non-zero when something genuinely needs attention. Do **not** wrap it in fragile
`set -e` shell that parses sub-step output; let `daily` do the work and read its JSON.

The JSON summary looks like:
```json
{"timestamp":"…","run_summary":{"updated":4,"current":55,"errors":0},
 "health":{"total_active":59,"ok":59,"late":0,"broken":0,"no_data":0,"needs_attention":0},
 "needs_attention":[], "update_log":"…/UPDATE_LOG.md", "export_error":null}
```
If `needs_attention` is non-empty, those series have a *failing fetch* (adapter/source
problem) — surface them and fall back to web search for those items only.

### READ operations (use these constantly during analysis)

**Latest values:**
```
python3 market_data.py query latest --tickers SPX,GC=F,DGS10,BTC
```

**Full statistical context (the workhorse):**
```
python3 market_data.py query stats --ticker MOVE --windows 1d,1w,1m,3m,1y,5y
```
→ latest; %Δ per window; 52w hi/lo + distance; full-history min/max; percentile; z-score;
  rolling 20d vol; nearest trigger + distance-to-trigger.

**Cross-asset ratio (a / b):**
```
python3 market_data.py query ratio --num HG=F --den GC=F --windows 1m,1y,5y
```

**Rate spread (a − b) — e.g. Hayes' 2Y vs Fed Funds "demanding hikes" signal:**
```
python3 market_data.py query spread --a DGS2 --b EFFR --windows 1m,1y
```
→ current spread, %ile, z-score, level changes. (>0.5 on DGS2−EFFR = market pricing hikes.)

**Dashboard (for a briefing — stats for whole groups in one call):**
```
python3 market_data.py query dashboard --group macro-rates,macro-fed-liquidity,equity-index,volatility
```

**Bounded slice (only when a chart-like read is truly needed — hard-capped rows):**
```
python3 market_data.py query series --ticker SPX --since 2007-01-01 --resample monthly
```

### WRITE / MAINTENANCE operations

**Incremental update only:** `python3 market_data.py update --all` (or `--ticker X` / `--asset-class Y`)
**Backfill history (one-time per new series):** `python3 market_data.py backfill --ticker X` / `--all`
**After editing catalog.yaml:** `python3 market_data.py sync-catalog`
**Health check (no writes):** `python3 market_data.py doctor`
**Export snapshot:** `python3 market_data.py export --format parquet`

## Doctor / freshness semantics (read this before trusting "stale")

`doctor` (and `daily`) classify each active series using the **last fetch result**, not a
naive days-since-data threshold:

- **ok** — the last fetch reached the source and stored everything available. The series is
  as current as the source allows, *even if the latest data point is days/weeks old* (FRED
  dates monthly series at the period start and publishes with a lag; weekends/holidays mean
  daily series legitimately don't move). This is the common case.
- **late** — fetches are succeeding but the latest data point is older than a generous,
  frequency-aware bound. A soft "the feed may be lagging or frozen — verify" watch, **not**
  a failure. Known-laggy feeds (FX, WM2NS, term premium) carry a `staleness_grace_days`
  override in the catalog so they don't flag.
- **broken / no_data** — the fetch itself errored, or there's no data at all. **This is the
  only thing that needs a fix.** `needs_attention` counts exactly these.

So "M2 last data 52 days ago" is normal (ok), not stale. Only `broken` is actionable.

## Catalog & sources

Series live in `$MARKET_DATA_DIR/config/catalog.yaml` (the user's private catalog — NOT in
this repo). Add a ticker = append to catalog → `sync-catalog` → `backfill --ticker X`. No
code change. Optional per-series field `staleness_grace_days` widens the "late" bound.

| Source | Status | Coverage |
|--------|--------|----------|
| `yahoo_direct` | ✅ primary for prices | direct Yahoo v8 chart via curl_cffi browser impersonation (defeats anti-bot 429s); equity indices (incl. ex-US), single names, ETFs, futures, DXY, MOVE |
| `yahoo` (yfinance) | ✅ fallback | same data, independent code path — kept as a second Yahoo attempt in chains |
| FRED | ✅ working | yields, Fed liquidity (WALCL/RRP/TGA/RESERVES/SRF), M2, CPI/PCE/jobs, OAS, VIX/OVX, FX + a free fallback for US indices/Nikkei |
| EIA | ✅ working | WTI/Brent spot, crude/gasoline/distillate stocks, SPR, refinery utilization |
| CoinGecko | ✅ working (free tier, 365d) | BTC, ETH, USDT/USDC supply |
| Treasury FiscalData | ✅ working | daily TGA closing balance (`operating_cash_balance` endpoint) |
| `eodhd` | 💤 dormant | licensed global EOD (indices/single-names/FX). Ships wired but SKIPPED until `EODHD_API_KEY` is set |
| Stooq | ❌ deprecated | still Cloudflare-JS-walled (re-verified 2026-07); do not use |

See `references/source-notes.md` for per-source pitfalls and migration history.

## Source failover & provenance (v1.4.0)

A series can list an **ordered chain of sources**, tried until one returns data:

```yaml
- ticker: SPX
  name: S&P 500
  table_kind: ohlcv
  sources:
    - {source: yahoo_direct, symbol: "^GSPC"}
    - {source: yahoo,        symbol: "^GSPC"}
    - {source: fred,         symbol: SP500, kind: observations}  # close-only backstop
```

- The legacy single-source form (`source:` + `source_symbol:`) still works unchanged — it is
  treated as a one-element chain. Migrate a series to a chain only when you want a fallback.
- The engine tries each **available** source in order, stores the **first non-empty** result,
  records **which source served it** (`ingest_runs.served_by`), and only marks a series
  `needs_attention` when **every** source fails. A source is *available* iff its `auth_env`
  key is set (keyless sources like `yahoo_direct`/`fred`/`treasury` are always available).
- `UPDATE_LOG.md` shows a **Served by** column; a `⚠` means a fall-back served (the primary is
  degrading) — an early warning before the series ever flags broken.
- A fallback that yields a different shape (e.g. FRED gives a close-only `value`, series is
  `ohlcv`) is auto-normalized (value → close/adj_close). Declare a ref's native shape with
  `kind:` when it differs from the series' `table_kind`.

### Activating EODHD later (one env var)

`eodhd` ships as a complete but **dormant** adapter. To turn it on when a key is purchased:

1. Put `EODHD_API_KEY=…` in `~/.hermes/.env`. That alone makes every `eodhd` chain ref active.
2. *(Optional, recommended)* In `catalog.yaml`, move the `{source: eodhd, symbol: "<EXCH>"}`
   ref to the **front** of index/single-name chains so it becomes primary (EODHD symbols use
   exchange suffixes: `GSPC.INDX`, `KS11.INDX`, `NVDA.US`, `0700.HK`). Keep `yahoo_direct` as
   the fallback.
3. `sync-catalog` (only if you changed chains) → `backfill --ticker …` for any series whose
   primary changed. **No code change required.**

## Hard Rules

- NEVER paste raw multi-year row output into your analysis. Use `stats`/`ratio`/`spread`/`dashboard`.
- ALWAYS prefer the DB over recalled or web-scraped numbers for anything it tracks.
- Trust the doctor classes: only `broken`/`no_data` series are actually failing — for those,
  say so and fall back to web search for that item. `late` just means verify; `ok` is current.
- Cite the DB value + date and the percentile/z-score when making a turning-point claim.
- Run `query dashboard` before producing any investment analysis or briefing.
- Before changing adapter code, check `references/source-notes.md` — it documents known pitfalls.
