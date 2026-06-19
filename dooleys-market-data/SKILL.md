---
name: dooleys-market-data
description: Query, backfill, and update the local market-data SQLite store (prices, macro indicators, rates, flows, crypto, FX). Use this skill whenever investment/market analysis needs current OR historical numbers — index/commodity/crypto prices, yields, Fed liquidity (WALCL/RRP/TGA), M2, CPI, oil curve, VIX, cross-asset ratios, percentile/z-score context, or distance-to-trigger versus KOL thresholds. Returns compact computed summaries, never raw row dumps.
version: 1.2.0
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
- Cross-asset ratios (copper/gold, MOVE/VIX), percentile or z-score context
- Adding/refreshing tracked series
- Before any investment analysis: run `query stats` or `query dashboard` to ground yourself

## Prerequisites

- Python 3.8+ ; `pip install -r requirements.txt`
- `MARKET_DATA_DIR` points at the data dir (default `~/.hermes-backup-repo/market-data`)
- Free API keys in `~/.hermes/.env`: FRED_API_KEY, EIA_API_KEY (CoinGecko/Nasdaq optional)

## Instructions for AI Agent

### READ operations (use these constantly during analysis)

**Latest values:**
```
python3 market_data.py query latest --tickers SPX,GC=F,DGS10,BTC
```

**Full statistical context (the workhorse):**
```
python3 market_data.py query stats --ticker MOVE --windows 1d,1w,1m,3m,1y,5y
```

**Cross-asset ratio:**
```
python3 market_data.py query ratio --num HG=F --den GC=F --windows 1m,1y,5y
```

**Dashboard (for weekly briefing):**
```
python3 market_data.py query dashboard --group macro-rates,macro-fed-liquidity,equity-index,volatility
```

### WRITE / MAINTENANCE operations

**Backfill:** `python3 market_data.py backfill --ticker X / --asset-class Y / --all`
**Update:** `python3 market_data.py update --all`
**Sync catalog:** `python3 market_data.py sync-catalog`
**Health:** `python3 market_data.py doctor`
**Export:** `python3 market_data.py export --format parquet`

## Source Notes

See `references/source-notes.md` for per-source reliability ratings, adapter pitfalls, and migration history (Stooq deprecation, FRED URL construction, yfinance tz handling, CoinGecko/EIA/Treasury adapter status).

## Doctor Frequency Awareness

The `doctor` command flags series as "stale" based on the number of days since `last_updated`. This threshold must account for each series' natural release frequency:
- **Daily series** (traded assets, yields): stale if >2 days without update
- **Weekly series** (H.4.1, claims, inventories): stale if >8 days
- **Monthly series** (CPI, PCE, payrolls, M2, UNRATE): stale if >35 days
- A series flagged "stale" that's within its expected frequency window is a FALSE ALARM — it's waiting for the next scheduled release, not broken.

When checking data freshness before producing analysis, filter "stale" warnings by comparing the gap against the series frequency. Monthly series with 30-day gaps are normal.

**Known false-alarm series (doctor flags them stale, but the source hasn't published newer data yet):**
- **FRED FX (USDCNY, USDHKD, USDJPY):** DEXCHUS, DEXHKUS, DEXJPUS have a ~1-week release lag. 8-10 day "stale" flags are false alarms. Verify by curling FRED API directly: `curl "https://api.stlouisfed.org/fred/series/observations?series_id=DEXJPUS&api_key=$FRED_API_KEY&file_type=json&sort_order=desc&limit=3"` — if the API's latest date matches the DB's latest date, the series is current.
- **All monthly series:** CPI, CORECPI, COREPCE, PAYROLLS, UNRATE, FEDFUNDS, M2 — gaps up to 35 days are normal between releases.
- **Weekly series:** NFCI, CLAIMS, RESERVES, WALCL, RRP, TGA — gaps up to 8 days are normal. H.4.1 data (Fed balance sheet) releases every Thursday.

## Troubleshooting Mass Failures

When `doctor` shows many series stale/failed (e.g. 3/51 healthy), follow this diagnostic pattern:

0. **Check day-of-week FIRST.** Saturday/Sunday runs naturally show `no_new_data` for most sources (markets closed). A 23/50 healthy report on Sunday may simply mean the Friday run was fine and crypto updated over the weekend. Don't panic — check the actual latest data dates in the DB before assuming breakage.
1. **Inspect the cron output logs.** The UPDATE_LOG.md only shows the most recent run. The cron output directory (`~/.hermes/cron/output/<job_id>/`) has per-run files. Read the last 5-7 chronologically to spot patterns (e.g., "pandas bug Mon-Thu, fix deployed Thu night, Fri OK, Sat timeout, Sun weekend"). **CRITICAL:** The cron job `last_status: "ok"` is misleading for no_agent scripts — it reflects the scheduler's view, not the script's exit code. The actual output file may show "script failed" or "timed out after 120s". Always read the output file.
2. **Test one series per source** — `update --ticker SPX` (yahoo), `--ticker DGS10` (fred), `--ticker BTC` (coingecko), `--ticker WTI` (eia). This isolates whether failures are source-specific or systemic.
3. **Group by error message.** Common failure classes in order of likelihood:
   - **Dependency version breakage** — pandas/numpy upgrades can break datetime comparisons (e.g. pandas 3.0.3: `Invalid comparison between dtype=datetime64 and Timestamp`). Check `pip show pandas numpy` first.
   - **API parameter changes** — free-tier limits tighten, `days=max` → `days=365`, endpoints move. Test with `curl` before debugging code.
   - **Config propagation gaps** — catalog fields (eia_route, table_kind) must reach the adapter. `_fetch_from_source` handles the mapping; check it before touching adapters.
   - **Intermittent script timeout** — the daily ingest cron (`update-market-data.sh`) has a 120s default. `set -euo pipefail` means one slow API call kills the entire run. If cron output files alternate between full runs and "Script timed out after 120s", the script needs a timeout bump (cronjob update) or per-source timeout handling.
4. **Fix at the right layer.** Datetime bugs belong in `market_data.py` update flow. API parameter changes belong in `sources/<name>.py`. Config mapping gaps belong in `_fetch_from_source`. Timeout issues: bump the cron job timeout via `cronjob action=update` first, then add per-source retry/timeout in the Python code.
5. **After fixing, run `update --all` then `doctor`** to verify. Some "stale" flags are normal for monthly/weekly series — filter by frequency before panicking.

## Source Adapter Status

See `references/source-notes.md` for per-source reliability, gotchas, current status, and migration history. Key status at a glance:

| Source | Status | Series Count |
|--------|--------|-------------|
| FRED | ✅ Working | ~28 daily/weekly/monthly |
| Yahoo | ✅ Working | ~14 equities/ETFs/futures |
| CoinGecko | ✅ Working (free tier, 365d limit) | 4 crypto |
| EIA | ✅ Working (route mapping fixed) | 4 energy |
| Treasury | ❌ Paused (API restructured) | 1 (TGA_DAILY) |

## Hard Rules

- NEVER paste raw multi-year row output into your analysis. Use `stats`/`ratio`/`dashboard`.
- ALWAYS prefer the DB over recalled or web-scraped numbers for anything it tracks.
- If `doctor` shows a series stale/failed, say so and fall back to web search for that item.
- Cite the DB value + date and the percentile/z-score when making a turning-point claim.
- Run `query dashboard` before producing any investment analysis or briefing.
- Before changing adapter code, check `references/source-notes.md` — it documents known pitfalls and fixes applied.
