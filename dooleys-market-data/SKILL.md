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
Returns JSON: ticker, name, latest date, latest value/close, day change.

**Full statistical context for a series (the workhorse):**
```
python3 market_data.py query stats --ticker MOVE --windows 1d,1w,1m,3m,1y,5y
```
Returns JSON: latest; %Δ per window; 52w high/low and distance to each; min/max over full
history; percentile rank of latest vs full history; z-score; rolling 20d volatility;
nearest trigger level and distance-to-trigger (from catalog trigger_levels).

**Cross-asset ratio:**
```
python3 market_data.py query ratio --num HG=F --den GC=F --windows 1m,1y,5y
```
Returns JSON: current ratio, percentile vs history, z-score, trend.

**Bounded slice (only when a chart-like read is truly needed):**
```
python3 market_data.py query series --ticker SPX --since 2007-01-01 --resample monthly
```
Returns JSON: downsampled, hard-capped rows. NEVER returns full daily history.

**Dashboard (for the weekly briefing):**
```
python3 market_data.py query dashboard --group macro-rates,macro-fed-liquidity,macro-inflation-growth,macro-credit-stress,equity-index,volatility,precious-metals,industrial-metals,energy,fx,crypto
```
Returns JSON: stats summary for every active series in the named groups, including
distance-to-trigger flags. Designed to fit the briefing in one call.

**Events timeline:**
```
python3 market_data.py query-events --since 2026-01-01 --category cpi,fomc
```

### WRITE / MAINTENANCE operations

**Backfill (one-time per series; default 30y, falls back to max available):**
```
python3 market_data.py backfill --asset-class rates        # or --ticker X / --all
```
**Daily incremental update (called by cron):**
```
python3 market_data.py update --all
```
**After editing catalog.yaml:**
```
python3 market_data.py sync-catalog          # add new series, mark removed
```
**Log a macro event:**
```
python3 market_data.py add-event --date 2026-06-12 --category cpi --title "May CPI" --value 3.1 --consensus 3.2
```
**Health / coverage:**
```
python3 market_data.py doctor                # gaps, stale series, failures
python3 market_data.py status --ticker GC=F
```
**Backup snapshot:**
```
python3 market_data.py export --format parquet
```

## Hard Rules

- NEVER paste raw multi-year row output into your analysis. Use `stats`/`ratio`/`dashboard`.
- ALWAYS prefer the DB over recalled or web-scraped numbers for anything it tracks.
- If `doctor` shows a series stale/failed, say so and fall back to web search for that item.
- Cite the DB value + date and the percentile/z-score when making a turning-point claim.
- Run `query dashboard` before producing any investment analysis or briefing.
