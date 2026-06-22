# `dooleys-market-data` — Skill Specification

**Created:** 2026-06-07
**Status:** Proposed (Phase 0)
**Recommended canonical destination:** lives as a skill in `manhay212/dooleys-ai-skills` → `dooleys-market-data/`
**Companion docs:** `MARKET_DATA_ARCHITECTURE.md`, `MARKET_DATA_IMPLEMENTATION_PLAN.md`

> This is the engine that backfills, updates, and (most importantly) **summarizes** market data for the agent. It is a code skill following the existing `dooleys-twitter-x-reader` conventions (Python, `.env` creds, JSON output, `last_run`-style tracking via the `ingest_runs` table).

---

## 1. Design Principles

1. **Engine, not catalog.** The skill contains *no tickers and no personal config*. It reads `catalog.yaml`/`sources.yaml` from `MARKET_DATA_DIR` (outside this repo). Keeps the repo public-ready and reusable.
2. **Return summaries, never raw dumps.** Every agent-facing `query` returns compact, computed output (latest, %Δ, percentile, z-score) — never thousands of rows. This is the hard rule that keeps the agent inside its context budget.
3. **Modular adapters.** One module per source under `sources/`. Adding a provider = new module + `sources.yaml` entry. No core changes.
4. **Idempotent & resumable.** All writes are UPSERTs keyed on `(series_id, date)`. Backfill can be re-run safely and resumes from `last_updated`.
5. **Graceful degradation.** One source failing logs an error and continues; `doctor` reports health. The system never hard-fails on a single bad series.
6. **Declarative is truth.** The DB is rebuildable from `catalog.yaml` + sources at any time.

---

## 2. Folder Structure (in `dooleys-ai-skills`)

```
dooleys-market-data/
├── SKILL.md                     # agent instructions (frontmatter + body) — draft in §3
├── README.md                    # human setup guide (env keys, how to run)
├── market_data.py               # CLI entrypoint (argparse: backfill/update/query/...)
├── db.py                        # schema init, UPSERT helpers, query primitives
├── catalog.py                   # load/validate catalog.yaml + sources.yaml, reconcile to `series`
├── summarize.py                 # the compact-summary computations (stats, percentile, z-score, ratio)
├── sources/
│   ├── __init__.py              # adapter registry + base interface
│   ├── fred.py
│   ├── stooq.py
│   ├── eia.py
│   ├── coingecko.py
│   └── treasury.py
├── requirements.txt             # requests, pandas, pyyaml, pyarrow  (yfinance optional)
└── .gitignore                   # excludes any local test DB / output files
```

`schema.sql`, `catalog.yaml`, `sources.yaml` are **not** in the skill repo — they live in `~/.hermes-backup-repo/market-data/` (or `$MARKET_DATA_DIR`). The skill ships sensible defaults it can write out via `market_data.py init` if the dir is empty.

---

## 3. SKILL.md (Draft)

```markdown
---
name: dooleys-market-data
description: Query, backfill, and update the local market-data SQLite store (prices, macro indicators, rates, flows, crypto, FX). Use this skill whenever investment/market analysis needs current OR historical numbers — index/commodity/crypto prices, yields, Fed liquidity (WALCL/RRP/TGA), M2, CPI, oil curve, VIX, cross-asset ratios, percentile/z-score context, or distance-to-trigger versus KOL thresholds. Returns compact computed summaries, never raw row dumps.
version: 1.0.0
category: dooleys
required_environment_variables:
  - MARKET_DATA_DIR
  - FRED_API_KEY
  - EIA_API_KEY
  - COINGECKO_API_KEY
  - NASDAQ_DATA_LINK_API_KEY
---

# Market Data Skill

Local, queryable market-data store for grounded investment analysis. The agent must use
this skill for NUMBERS (prices, yields, macro series, ratios, historical context) instead
of recalling them from training or guessing from a web page. Use web search for NARRATIVE
(news, geopolitics, regulation), not for figures this DB can provide.

## When to Use

- Any market/investment question needing a current or historical figure
- "How far is X from its range / a turning point / a KOL trigger level?"
- Cross-asset ratios (copper/gold, MOVE→VIX), percentile or z-score context
- Adding/refreshing tracked series

## Prerequisites

- Python 3.8+ ; `pip install -r requirements.txt`
- `MARKET_DATA_DIR` points at the data dir (default `~/.hermes-backup-repo/market-data`)
- Free API keys in `~/.hermes/.env`: FRED_API_KEY, EIA_API_KEY (CoinGecko/Nasdaq optional)

## Instructions for AI Agent

### READ operations (use these constantly during analysis)

**Latest values:**
    python3 market_data.py query latest --tickers SPX,GC=F,DGS10,BTC
→ JSON: ticker, name, latest date, latest value/close, day change.

**Full statistical context for a series (the workhorse):**
    python3 market_data.py query stats --ticker MOVE --windows 1d,1w,1m,3m,1y,5y
→ JSON: latest; %Δ per window; 52w high/low and distance to each; min/max over full
  history; percentile rank of latest vs full history; z-score; rolling 20d volatility;
  nearest trigger level and distance-to-trigger (from catalog trigger_levels).

**Cross-asset ratio:**
    python3 market_data.py query ratio --num HG=F --den GC=F --windows 1m,1y,5y
→ JSON: current ratio, percentile vs history, z-score, trend.

**Bounded slice (only when a chart-like read is truly needed):**
    python3 market_data.py query series --ticker SPX --since 2007-01-01 --resample monthly
→ JSON: downsampled, hard-capped rows. NEVER returns full daily history.

**Dashboard (for the weekly briefing):**
    python3 market_data.py query dashboard --group macro,rates,crypto,commodities
→ JSON: stats summary for every active series in the named groups, including
  distance-to-trigger flags. Designed to fit the briefing in one call.

**Events timeline:**
    python3 market_data.py query-events --since 2026-01-01 --category cpi,fomc

### WRITE / MAINTENANCE operations

**Backfill (one-time per series; default 30y, falls back to max available):**
    python3 market_data.py backfill --asset-class rates        # or --ticker X / --all
**Daily incremental update (called by cron):**
    python3 market_data.py update --all
**After editing catalog.yaml:**
    python3 market_data.py sync-catalog          # add new series, mark removed
**Log a macro event:**
    python3 market_data.py add-event --date 2026-06-12 --category cpi --title "May CPI" --value 3.1 --consensus 3.2
**Health / coverage:**
    python3 market_data.py doctor                # gaps, stale series, failures
    python3 market_data.py status --ticker GC=F
**Backup snapshot:**
    python3 market_data.py export --format parquet

## Hard Rules

- NEVER paste raw multi-year row output into your analysis. Use `stats`/`ratio`/`dashboard`.
- ALWAYS prefer the DB over recalled or web-scraped numbers for anything it tracks.
- If `doctor` shows a series stale/failed, say so and fall back to web search for that item.
- Cite the DB value + date and the percentile/z-score when making a turning-point claim.
```

---

## 4. Source Adapter Interface

Every adapter implements one function so the core stays source-agnostic:

```python
# sources/__init__.py
from importlib import import_module

def get_adapter(name):
    return import_module(f"sources.{name}")

# Each adapter module exposes:
def fetch(source_symbol: str, start: str | None, end: str | None, cfg: dict) -> "pd.DataFrame":
    """
    Returns a DataFrame indexed by date (UTC, daily) with either:
      - ['open','high','low','close','adj_close','volume']  (table_kind = ohlcv), or
      - ['value']                                            (table_kind = observations)
    Must handle: missing key, 'max available' (start=None), rate limits (sleep+retry),
    and return an EMPTY frame (not raise) on a soft failure so the core can log + continue.
    """
```

Adapter notes:
- **fred.py** — `GET /fred/series/observations?series_id=...&api_key=...&file_type=json`; `value` column; respect ~120 req/min; treat `.` as NaN.
- **stooq.py** — `GET https://stooq.com/q/d/l/?s={symbol}&i=d` returns CSV with OHLCV; no key; map to `ohlcv`; use Close as `adj_close` proxy if no adj provided (note in DATA_DICTIONARY).
- **eia.py** — `GET /v2/{route}/data/?api_key=...&frequency=weekly&data[]=value&facets...`; weekly cadence.
- **coingecko.py** — `/coins/{id}/market_chart?vs_currency=usd&days=max&interval=daily`; for supply use `/coins/markets`; free-tier `days=max` may cap → fall back to exchange klines (documented in adapter).
- **treasury.py** — `GET /v1/accounting/dts/dts_table_1?filter=...&fields=...&page[size]=...`; paginated; no key.

Adding a source later (e.g., Polymarket, a Centaline scraper) = drop in `sources/polymarket.py` + a `sources.yaml` entry. Nothing else changes.

---

## 5. `schema.sql` (Draft)

```sql
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS series (
    series_id       INTEGER PRIMARY KEY,
    ticker          TEXT UNIQUE NOT NULL,        -- internal canonical id, e.g. 'GC=F','DGS10','BTC'
    name            TEXT NOT NULL,
    asset_class     TEXT NOT NULL,               -- macro-rates, equity-index, crypto, ...
    subclass        TEXT,
    source          TEXT NOT NULL,               -- fred|stooq|eia|coingecko|treasury|...
    source_symbol   TEXT NOT NULL,               -- native code at the source
    unit            TEXT,                        -- percent, USD, index, bbl, oz, ratio
    frequency       TEXT,                        -- daily|weekly|monthly
    table_kind      TEXT NOT NULL,               -- 'ohlcv' | 'observations'
    first_available DATE,
    last_updated    DATE,
    status          TEXT DEFAULT 'active',       -- active|paused|deprecated
    trigger_levels  TEXT,                        -- JSON: {"caution":120,"danger":140}
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_series_class ON series(asset_class);

CREATE TABLE IF NOT EXISTS ohlcv (
    series_id  INTEGER NOT NULL REFERENCES series(series_id),
    date       DATE NOT NULL,
    open       REAL, high REAL, low REAL, close REAL, adj_close REAL, volume REAL,
    PRIMARY KEY (series_id, date)
);

CREATE TABLE IF NOT EXISTS observations (
    series_id  INTEGER NOT NULL REFERENCES series(series_id),
    date       DATE NOT NULL,
    value      REAL,
    PRIMARY KEY (series_id, date)
);

CREATE TABLE IF NOT EXISTS events (
    event_id   INTEGER PRIMARY KEY,
    date       DATE NOT NULL,
    category   TEXT NOT NULL,                    -- cpi|nfp|fomc|rate-decision|geopolitical|regulation|...
    title      TEXT NOT NULL,
    value      REAL, prior REAL, consensus REAL, surprise REAL,
    source_url TEXT,
    doc_ref    TEXT,                             -- pointer into docs/ or wiki/
    notes      TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);

CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id     INTEGER PRIMARY KEY,
    series_id  INTEGER REFERENCES series(series_id),
    ts         TEXT NOT NULL,
    rows_added INTEGER, from_date DATE, to_date DATE,
    status     TEXT, error TEXT
);
```

---

## 6. `sources.yaml` (Draft)

```yaml
sources:
  fred:
    base_url: https://api.stlouisfed.org/fred
    auth_env: FRED_API_KEY
    rate_limit_per_min: 120
  stooq:
    base_url: https://stooq.com/q/d/l/
    auth_env: null
    rate_limit_per_min: 60
  eia:
    base_url: https://api.eia.gov/v2
    auth_env: EIA_API_KEY
    rate_limit_per_min: 60
  coingecko:
    base_url: https://api.coingecko.com/api/v3
    auth_env: COINGECKO_API_KEY      # optional demo key; works keyless with lower limits
    rate_limit_per_min: 30
  treasury:
    base_url: https://api.fiscaldata.treasury.gov/services/api/fiscal_service
    auth_env: null
    rate_limit_per_min: 60

defaults:
  backfill_years: 30
  on_short_history: max_available     # if 30y not available, take as far back as possible
```

---

## 7. `catalog.yaml` (Seed Excerpt — derived from the KOL KEY_INDICATORS files)

> Illustrative and immediately useful. The skill should verify exact source symbols at build
> time (symbols occasionally change). Trigger levels are taken from the KOL dashboards.

```yaml
asset_classes:

  macro-rates:
    description: Treasury yields, curve, policy rates
    series:
      - {ticker: DGS2,  name: US 2Y Yield,  source: fred, source_symbol: DGS2,  table_kind: observations, unit: percent}
      - {ticker: DGS10, name: US 10Y Yield, source: fred, source_symbol: DGS10, table_kind: observations, unit: percent, trigger_levels: {dysfunction_low: 4.5, dysfunction_high: 5.0}}
      - {ticker: DGS30, name: US 30Y Yield, source: fred, source_symbol: DGS30, table_kind: observations, unit: percent, trigger_levels: {psychological: 5.0}}
      - {ticker: DFII10, name: US 10Y Real Yield, source: fred, source_symbol: DFII10, table_kind: observations, unit: percent}
      - {ticker: T10YIE, name: 10Y Breakeven Inflation, source: fred, source_symbol: T10YIE, table_kind: observations, unit: percent}
      - {ticker: T10Y2Y, name: 10Y-2Y Spread, source: fred, source_symbol: T10Y2Y, table_kind: observations, unit: percent}
      - {ticker: SOFR,  name: SOFR, source: fred, source_symbol: SOFR, table_kind: observations, unit: percent}
      - {ticker: FEDFUNDS, name: Fed Funds Rate, source: fred, source_symbol: FEDFUNDS, table_kind: observations, unit: percent}

  macro-fed-liquidity:
    description: Fed balance sheet & money (H.4.1, M2)
    series:
      - {ticker: WALCL, name: Fed Total Assets, source: fred, source_symbol: WALCL, table_kind: observations, unit: usd_millions, frequency: weekly}
      - {ticker: RRP,   name: Overnight Reverse Repo Volume, source: fred, source_symbol: RRPONTSYD, table_kind: observations, unit: usd_billions, trigger_levels: {exhausted: 0}}
      - {ticker: TGA,   name: Treasury General Account, source: fred, source_symbol: WTREGEN, table_kind: observations, unit: usd_billions, frequency: weekly}
      - {ticker: TGA_DAILY, name: TGA Operating Cash (daily), source: treasury, source_symbol: dts/dts_table_1, table_kind: observations, unit: usd_millions}
      - {ticker: RESERVES, name: Bank Reserve Balances, source: fred, source_symbol: WRESBAL, table_kind: observations, unit: usd_billions, frequency: weekly}
      - {ticker: M2,    name: M2 Money Supply, source: fred, source_symbol: M2SL, table_kind: observations, unit: usd_billions, frequency: monthly}
      - {ticker: M2_WEEKLY, name: M2 (weekly NSA), source: fred, source_symbol: WM2NS, table_kind: observations, unit: usd_billions, frequency: weekly}

  macro-inflation-growth:
    series:
      - {ticker: CPI,   name: CPI, source: fred, source_symbol: CPIAUCSL, table_kind: observations, frequency: monthly}
      - {ticker: CORECPI, name: Core CPI, source: fred, source_symbol: CPILFESL, table_kind: observations, frequency: monthly}
      - {ticker: COREPCE, name: Core PCE, source: fred, source_symbol: PCEPILFE, table_kind: observations, frequency: monthly}
      - {ticker: UNRATE, name: Unemployment Rate, source: fred, source_symbol: UNRATE, table_kind: observations, frequency: monthly}
      - {ticker: PAYROLLS, name: Nonfarm Payrolls, source: fred, source_symbol: PAYEMS, table_kind: observations, frequency: monthly}
      - {ticker: CLAIMS, name: Initial Jobless Claims, source: fred, source_symbol: ICSA, table_kind: observations, frequency: weekly}

  macro-credit-stress:
    series:
      - {ticker: HY_OAS, name: US High Yield OAS, source: fred, source_symbol: BAMLH0A0HYM2, table_kind: observations, unit: percent}
      - {ticker: IG_OAS, name: US IG OAS, source: fred, source_symbol: BAMLC0A0CM, table_kind: observations, unit: percent}
      - {ticker: NFCI,   name: Chicago Fed Financial Conditions, source: fred, source_symbol: NFCI, table_kind: observations, frequency: weekly}

  equity-index:
    series:
      - {ticker: SPX, name: S&P 500, source: stooq, source_symbol: ^spx, table_kind: ohlcv}
      - {ticker: NDX, name: Nasdaq 100, source: stooq, source_symbol: ^ndx, table_kind: ohlcv}
      - {ticker: RUT, name: Russell 2000, source: stooq, source_symbol: ^rut, table_kind: ohlcv}
      - {ticker: SOX, name: PHLX Semiconductor, source: stooq, source_symbol: ^sox, table_kind: ohlcv}
      - {ticker: HSI, name: Hang Seng, source: stooq, source_symbol: ^hsi, table_kind: ohlcv}
      - {ticker: N225, name: Nikkei 225, source: stooq, source_symbol: ^nkx, table_kind: ohlcv}

  volatility:
    series:
      - {ticker: VIX,  name: CBOE VIX, source: fred, source_symbol: VIXCLS, table_kind: observations, trigger_levels: {complacent: 13, stress: 25, panic: 35}}
      - {ticker: OVX,  name: CBOE Oil VIX, source: fred, source_symbol: OVXCLS, table_kind: observations}
      - {ticker: MOVE, name: ICE BofA MOVE, source: stooq, source_symbol: ^move, table_kind: ohlcv, trigger_levels: {caution: 120, policy_action: 140, ath: 172}, notes: "best-effort; verify availability"}

  precious-metals:
    series:
      - {ticker: GC=F, name: Gold, source: stooq, source_symbol: gc.f, table_kind: ohlcv}
      - {ticker: SI=F, name: Silver, source: stooq, source_symbol: si.f, table_kind: ohlcv}
      - {ticker: PL=F, name: Platinum, source: stooq, source_symbol: pl.f, table_kind: ohlcv}

  industrial-metals:
    series:
      - {ticker: HG=F, name: Copper, source: stooq, source_symbol: hg.f, table_kind: ohlcv}

  energy:
    series:
      - {ticker: WTI, name: WTI Crude, source: eia, source_symbol: petroleum/pri/spt/data?...RWTC, table_kind: observations, unit: usd_bbl}
      - {ticker: BRENT, name: Brent Crude, source: eia, source_symbol: petroleum/pri/spt/data?...RBRTE, table_kind: observations, unit: usd_bbl}
      - {ticker: CRUDE_STOCKS, name: US Crude Inventory, source: eia, source_symbol: petroleum/stoc/wstk/...WCESTUS1, table_kind: observations, frequency: weekly}
      - {ticker: SPR, name: Strategic Petroleum Reserve, source: eia, source_symbol: petroleum/stoc/wstk/...WCSSTUS1, table_kind: observations, frequency: weekly}

  fx:
    series:
      - {ticker: DXY, name: US Dollar Index, source: stooq, source_symbol: ^dxy, table_kind: ohlcv}
      - {ticker: USDHKD, name: USD/HKD, source: fred, source_symbol: DEXHKUS, table_kind: observations}
      - {ticker: USDJPY, name: USD/JPY, source: fred, source_symbol: DEXJPUS, table_kind: observations}
      - {ticker: USDCNY, name: USD/CNY, source: fred, source_symbol: DEXCHUS, table_kind: observations}

  crypto:
    series:
      - {ticker: BTC, name: Bitcoin, source: coingecko, source_symbol: bitcoin, table_kind: ohlcv, trigger_levels: {bull_invalidation: 60000, breakout: 110000, prior_ath: 126000}}
      - {ticker: ETH, name: Ethereum, source: coingecko, source_symbol: ethereum, table_kind: ohlcv}
      - {ticker: USDT_SUPPLY, name: USDT Circulating Supply, source: coingecko, source_symbol: tether, table_kind: observations}
      - {ticker: USDC_SUPPLY, name: USDC Circulating Supply, source: coingecko, source_symbol: usd-coin, table_kind: observations}

  credit-bonds-proxy:
    series:
      - {ticker: TLT, name: 20Y+ Treasury ETF, source: stooq, source_symbol: tlt.us, table_kind: ohlcv}
      - {ticker: HYG, name: High Yield ETF, source: stooq, source_symbol: hyg.us, table_kind: ohlcv}

  # Phase 1 best-effort (no clean API — scraper/manual adapters):
  housing-hk:
    series:
      - {ticker: CCL, name: Centaline Centa-City Leading Index, source: centaline, source_symbol: ccl, table_kind: observations, frequency: weekly, status: paused, notes: "Phase 1 scraper"}
```

---

## 8. Example `query stats` Output (the contract the agent relies on)

```json
{
  "ticker": "MOVE",
  "name": "ICE BofA MOVE",
  "as_of": "2026-06-06",
  "latest": 142.3,
  "unit": "index",
  "changes": {"1d": "+3.1%", "1w": "+8.0%", "1m": "+19.4%", "3m": "+22.1%", "1y": "+11.0%", "5y": "+85%"},
  "range_52w": {"high": 151.2, "low": 78.4, "pct_from_high": "-5.9%", "pct_from_low": "+81.5%"},
  "history": {"min": 36.6, "max": 264.6, "percentile_of_latest": 0.93, "zscore": 2.05},
  "rolling_vol_20d": 6.8,
  "nearest_trigger": {"name": "policy_action", "level": 140, "distance": "+1.6% above"},
  "interpretation_hint": "latest is in the top decile vs 30y history; above the 140 'policy_action' trigger"
}
```

The agent reads *this* — a few hundred bytes — not 7,560 rows. That is what keeps the whole system inside the context budget while still enabling rigorous turning-point reasoning.

---

## 9. README.md (outline for the skill repo)

- What it does (one paragraph) + the numbers-vs-words rule
- Setup: `pip install -r requirements.txt`; set `MARKET_DATA_DIR`; **Option A** env keys (primary), **Option B** none/keyless degraded mode
- Where to get free keys: FRED (fred.stlouisfed.org → API key), EIA (eia.gov/opendata), CoinGecko demo key (optional)
- Quickstart: `init` → `backfill --all` → `update --all` → `query stats --ticker SPX`
- No Hermes internals, no personal catalog (public-ready, per repo convention)
