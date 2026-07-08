# dooleys-market-data

A local, queryable **market-data engine**: it backfills, updates, and — most importantly —
**summarizes** numerical market data (prices, yields, Fed liquidity, macro series, crypto, FX,
energy) into a local SQLite store so an AI agent can ground investment analysis in real
numbers and historical distributions instead of guessing.

**Numbers vs. words.** This skill is for *numbers* (prices, yields, M2, oil, ratios,
percentiles, z-scores). Use web search for *narrative* (news, geopolitics, regulation). The DB
is ground truth for figures; it never returns raw multi-year row dumps — only compact computed
summaries (latest, %Δ, 52w range, percentile, z-score, distance-to-trigger).

## Engine, not catalog

The skill is a generic engine and ships **no tickers and no personal config**. It reads
`catalog.yaml` + `sources.yaml` from `$MARKET_DATA_DIR` (default
`~/.hermes-backup-repo/market-data`), which is *outside* this repo. The DB is a rebuildable
cache; the catalog is the source of truth.

```
$MARKET_DATA_DIR/
├── config/
│   ├── catalog.yaml      # series registry (your private tickers + trigger levels)
│   └── sources.yaml      # provider adapters: base URLs, auth env-var names, rate limits
├── db/
│   ├── market.db         # SQLite (gitignored — a cache)
│   └── schema.sql        # committed; DB is recreatable from this + catalog
├── exports/              # Parquet snapshots (fast restore)
└── UPDATE_LOG.md         # written by `daily` — human-readable health/progress
```

## Setup

```bash
pip install -r requirements.txt
```

Set these in `~/.hermes/.env` (env vars take priority over any config file):

| Variable | Required | Where to get it |
|----------|----------|-----------------|
| `MARKET_DATA_DIR` | yes | path to the data dir (e.g. `/home/you/.hermes-backup-repo/market-data`) |
| `FRED_API_KEY` | yes | https://fred.stlouisfed.org/docs/api/api_key.html (free) |
| `EIA_API_KEY` | yes | https://www.eia.gov/opendata/register.php (free) |
| `COINGECKO_API_KEY` | optional | CoinGecko demo key (works keyless at lower limits) |
| `EODHD_API_KEY` | optional (dormant) | https://eodhd.com — unset by default; setting it activates the `eodhd` source in any catalog chain that lists it (no code change) |
| `TWELVEDATA_API_KEY` | optional (dormant) | https://twelvedata.com — only used if referenced in a chain |

> Run with the host venv python so pandas/pyarrow/yfinance/curl_cffi are available:
> `~/.hermes/hermes-agent/venv/bin/python3 market_data.py …`

### Source failover (v1.4.0)

A catalog series may list an ordered `sources: [chain]`; the engine tries each *available*
source until one returns data, records which one served it (`UPDATE_LOG.md` → **Served by**
column, `⚠` = fall-back served), and only flags a series when *all* sources fail. The price
primary is `yahoo_direct` (direct Yahoo v8 chart via `curl_cffi` browser impersonation, which
defeats the anti-bot 429s that plain `requests` trips), with `yahoo` (yfinance) and, where
available, `fred` as fallbacks. `eodhd` is shipped **dormant** — see `SKILL.md` for how a single
`EODHD_API_KEY` activates it. Legacy single-source series keep working unchanged.

## Quickstart

```bash
cd dooleys-market-data
python3 market_data.py init            # create db/market.db from schema.sql
python3 market_data.py sync-catalog    # register every series from catalog.yaml
python3 market_data.py backfill --all  # 30y where available, else max (one-time, resumable)
python3 market_data.py daily           # update all + write UPDATE_LOG.md + export snapshot
python3 market_data.py query stats --ticker SPX --windows 1y,5y
```

## The daily routine (what the cron/agent runs)

**Use the single `daily` command.** It is self-contained and robust: update every active
series (with per-series error + timeout isolation), write a clean `UPDATE_LOG.md`, export a
Parquet snapshot, and print a JSON summary. One bad source is recorded and the rest still
update — it never goes all-or-nothing.

```bash
python3 market_data.py daily          # prints JSON summary; writes $MARKET_DATA_DIR/UPDATE_LOG.md
```

### Correct cron wrapper

Earlier breakage came from a shell wrapper that ran `update`, then `doctor`, then tried to
re-parse `doctor`'s output in bash under `set -euo pipefail` — a single empty variable killed
the whole run every day (so `UPDATE_LOG.md`, the snapshot, and the GitHub push silently
stopped). **Don't reimplement the routine in fragile bash.** Let `daily` own it. A correct
wrapper is just:

```bash
#!/usr/bin/env bash
set -uo pipefail   # NOTE: no `-e` around the python call; daily handles its own errors
PY="$HOME/.hermes/hermes-agent/venv/bin/python3"
cd "$HOME/.hermes/custom-skills/dooleys-market-data"
MARKET_DATA_SERIES_TIMEOUT=60 "$PY" market_data.py daily || echo "daily exited non-zero"

# optional: commit + push the data repo for visibility
cd "$HOME/.hermes-backup-repo"
git add market-data/UPDATE_LOG.md market-data/exports/ market-data/config/ 2>/dev/null || true
git commit -m "daily-ingest: $(date +%F)" 2>/dev/null || true
git push origin main 2>&1 || echo "WARNING: GitHub push failed"
```

Give the cron job a generous timeout (≥300s); `daily` over ~60 series takes ~50–70s.

## Doctor / freshness semantics

`doctor` (and `daily`) classify each series by its **last fetch result**, not by naive
days-since-data:

- **ok** — last fetch reached the source and stored everything available; as current as the
  source allows (a monthly series dated 50 days ago is normal, not stale).
- **late** — fetches succeed but the latest point is older than a generous, frequency-aware
  bound; a soft "verify, the feed may be lagging" watch. Known-laggy feeds carry a
  `staleness_grace_days` override in the catalog.
- **broken / no_data** — the fetch errored or there's no data. **The only actionable state.**

This replaced the old fixed-threshold logic that flagged ~20 healthy series "stale" every day.

## Adding a series

Append to `$MARKET_DATA_DIR/config/catalog.yaml`, then:
```bash
python3 market_data.py sync-catalog
python3 market_data.py backfill --ticker NEW_TICKER
```
No code change. Optional fields: `trigger_levels: {name: level}`, `staleness_grace_days: N`,
`frequency: daily|weekly|monthly`, `eia_route: …` (EIA only).

## Adding a source

Drop `sources/<name>.py` exposing `fetch(source_symbol, start, end, cfg) -> DataFrame`
(columns `[value]` for observations or `[open,high,low,close,adj_close,volume]` for ohlcv,
indexed by date; return an **empty** frame on soft failure, don't raise), register it in
`sources/__init__.py` and `sources.yaml`. Nothing else changes.

## Testing walkthrough

Offline unit tests (pure logic — no network, no DB files):

```bash
cd dooleys-market-data
python3 -m pytest tests/ -q
```
- `tests/test_health.py` — the freshness classifier (ok/late/broken/no_data) and the
  `UPDATE_LOG.md` rendering, including the false-alarm cases (monthly period-start dating,
  weekend gaps, errored fetches).
- `tests/test_summarize.py` — `stats`, `ratio`, `spread` on synthetic in-memory data.

Live smoke (needs API keys + a backfilled DB; safe to run against a sandbox copy):

```bash
export MARKET_DATA_DIR=/tmp/md-sandbox       # a copy of your data dir
python3 market_data.py update --ticker DGS10        # fred
python3 market_data.py update --ticker SPX          # yahoo
python3 market_data.py update --ticker BTC          # coingecko
python3 market_data.py update --ticker WTI          # eia
python3 market_data.py update --ticker TGA_DAILY    # treasury
python3 market_data.py doctor                       # should show broken=0
python3 market_data.py query spread --a DGS2 --b EFFR
```

Failure paths exit cleanly: no API key → the adapter logs a warning and returns empty
(no crash); an uninitialized DB → a clear "run init/sync-catalog" message, not a stack trace.

## Notes

- Runs under bleeding-edge **pandas 3.x / numpy 2.x**; date filtering is tz/resolution-safe
  (see `_filter_after` in `market_data.py`). Earlier versions crashed certain FRED series with
  `Invalid comparison between datetime64[us, UTC] and Timestamp`.
- Macro series store the **latest revision** (ALFRED vintages are a future phase).
- Tradable assets use **adjusted close** where available.
