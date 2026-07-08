# Source Adapter Reliability & Pitfalls

Last updated: 2026-07-09 (v1.4.0: per-series source failover chain + provenance; `yahoo_direct`
adapter via curl_cffi; dormant `eodhd` adapter)

## 2026-07-09 — v1.4.0: source failover + yahoo_direct + dormant eodhd

- **Per-series source failover.** Catalog `source:` can now be an ordered `sources: [chain]`
  (each ref `{source, symbol, kind?}`). `_fetch_with_failover` tries each *available* source
  until one returns non-empty data, records `served_by` in `ingest_runs`, and only flags
  `needs_attention` when all fail. Legacy single-source entries still work (one-element chain).
  The chain is re-read from `catalog.yaml` by ticker at fetch time (`_resolve_chain`) — the DB
  `series` row only stores the primary (chain[0]).
- **Credential gating (`_source_available`).** A source with a set `auth_env` is skipped unless
  that env var is non-empty. This is what keeps `eodhd` dormant until `EODHD_API_KEY` exists —
  verified: with the key set the engine calls eodhd and falls through on failure; unset, it logs
  "Skipping unavailable source 'eodhd'" and never calls it.
- **Shape normalization (`_normalize_kind`).** A fallback that returns a different `table_kind`
  than the series is coerced (obs `value` → ohlcv `close`/`adj_close`, and vice-versa).
- **Provenance rendering.** `UPDATE_LOG.md` gained a **Served by** column; `⚠` = a fall-back
  served (primary degrading). `served_by` persists through `no_new_data` days too (the source
  is reached and returns the existing bar, filtered as "not newer" but still recorded).
- **`_migrate` in db.get_connection** adds `ingest_runs.served_by` idempotently to an existing
  DB (ALTER TABLE guarded by PRAGMA), so no full re-backfill is needed. schema.sql is also the
  schema of record (host-side, hermes-backup).

## yahoo_direct (v8 chart via curl_cffi) — the new price primary

**Reliability:** ★★★★☆ — direct hit to `query{1,2}.finance.yahoo.com/v8/finance/chart/{sym}`.
The v8 chart endpoint is **crumbless** (no cookie/crumb needed, unlike v7 download).

**The key finding (live-verified 2026-07):** plain `requests` gets **HTTP 429** from Yahoo on
datacenter IPs even on the first call — Yahoo fingerprints the Python TLS handshake. `curl_cffi`
with `impersonate="chrome"` returns **200** from the same IP. So `yahoo_direct` uses `curl_cffi`
when available (it's a yfinance dependency; also pinned in requirements.txt) and falls back to
`requests` with a rotating UA. Also rotates query1↔query2 and retries with exp backoff + jitter.

**Why keep both `yahoo_direct` AND `yahoo` (yfinance)?** Two independent code paths to the same
data = genuine redundancy in a chain; they fail differently (verified: from a blocked IP the
yfinance path succeeded where a naive direct call 429'd, and vice-versa is possible).

**Symbols:** standard Yahoo (`^GSPC`, `^KS11`, `000001.SS`, `^GDAXI`, `GC=F`, `DX-Y.NYB`, `MSTR`).

## eodhd (dormant until key) — the licensed escape hatch

**Reliability:** licensed EOD, global (indices/single-names/FX/crypto). **Dormant by default:**
`auth_env: EODHD_API_KEY`; with no key `_source_available` skips it and `fetch()` returns empty.
Ships complete so activation is *set the env var* (+ optional chain reorder). Symbols use the
exchange-suffix form: `GSPC.INDX`, `KS11.INDX`, `NVDA.US`, `0700.HK`.

## 2026-06-22 overhaul — what changed and why

- **Daily pipeline was dead since June 14.** The *cron wrapper* (`update-market-data.sh`,
  in the hermes setup — not this skill) ran `update`, then `doctor`, then re-parsed doctor's
  output in bash under `set -euo pipefail`; the doctor stdout was never captured, so an empty
  var hit `json.load` and `set -e` killed the run right after "Doctor check — OK". Result:
  `UPDATE_LOG.md`, the Parquet export, and the GitHub push silently stopped (frozen at
  June 14) while `update` kept partially advancing the DB. **Fix:** a single robust
  `market_data.py daily` command now owns update + log + export in Python; the wrapper is a
  trivial 2-liner (see README). Don't reintroduce fragile bash.
- **Silent pandas-3.x crash.** Under pandas 3.0.3 the old incremental filter
  `df[parsed > pd.Timestamp(last, tz="UTC")]` raised `Invalid comparison between
  datetime64[us, UTC] and Timestamp` for several FRED series (M2, COREPCE, FEDFUNDS,
  PAYROLLS, UNRATE, M2_WEEKLY) — they had been erroring on *every* update for weeks, frozen
  at old dates, and the old doctor mislabeled them as generic "stale". **Fix:** `_filter_after`
  collapses both sides to tz-naive normalized calendar dates before comparing.
- **Doctor redesign.** Freshness is now classified by the *last fetch result* (ok / late /
  broken / no_data) plus a generous frequency-aware date bound, not a fixed day threshold.
  This killed ~20 daily false alarms. `update` now logs `no_new_data` runs so the health
  check can tell "current with source" from "broken". See SKILL.md for the semantics.

## FRED (Federal Reserve Economic Data)

**Reliability:** ★★★★★ — The workhorse. 30+ years of daily/weekly/monthly data, clean JSON API, 120 req/min.

**Gotchas:**
- Base URL is `https://api.stlouisfed.org` (NOT `...org/fred`). Adapter appends `/fred/series/observations`. Double-prefix produces 404.
- Missing values = `"."` (literal dot) → treat as NaN
- Weekly H.4.1 series (WALCL, RRP, TGA, RESERVES) published Thursday, available Friday
- Monthly series (CPI, PAYROLLS, UNRATE, M2, COREPCE) release on BLS/BEA schedule — doctor should NOT flag these as "stale" within their expected frequency window. e.g. 41-day old CPI data is normal between monthly releases.
- FEDFUNDS is monthly (not daily) — set `frequency: monthly` in catalog or doctor will flag falsely.
- ALFRED vintages not used (Phase 2) — latest revision only
- **pandas 3.0.3 sensitivity:** The adapter returns UTC-localized dates. Ensure `_fetch_from_source` comparison uses `pd.Timestamp(last_date_obj, tz="UTC")` not naive timestamps.
- **FX series release lag (2026-06-14):** DEXJPUS, DEXCHUS, DEXHKUS have a ~1-week publication delay. As of any given day, the latest available observation from FRED may be 8-10 days old. When `doctor` flags these as "stale," verify by curling the FRED API directly — if the API's latest date matches the DB's latest date, the series is current and the stale flag is a false alarm.

**Working tickers:** DGS2, DGS10, DGS30, DFII10, T10YIE, T10Y2Y, SOFR, FEDFUNDS, WALCL, RRP, TGA, RESERVES, M2, M2_WEEKLY, CPI, CORECPI, COREPCE, UNRATE, PAYROLLS, CLAIMS, HY_OAS, IG_OAS, NFCI, VIX, OVX, USDHKD, USDJPY, USDCNY

**Added 2026-06-22 (KOL indicators):**
- `EFFR` (Effective Fed Funds, daily) — enables Hayes' 2Y−EFFR "demanding hikes" spread (`query spread --a DGS2 --b EFFR`; >0.5 = trapped).
- `SRF` (`WORAL`, Repo/Standing Repo Facility Wednesday level, weekly) — Hayes' "stealth printing" tell; any balance > 0.
- `TERM_PREMIUM` (`THREEFYTP10`, Kim-Wright 10Y term premium) — ~1wk lag → `staleness_grace_days: 14`.
- `DXY_BROAD` (`DTWEXBGS`, broad trade-weighted USD) — ~1wk lag → grace 14.
- `NATGAS` (`DHHNGSP`, Henry Hub spot, daily) — FRED mirror of EIA; ~3-5d lag.
- FX series `USDHKD/USDJPY/USDCNY` carry `staleness_grace_days: 14` (FRED FX publishes weekly with lag).

## Yahoo Finance (yfinance)

**Reliability:** ★★★★☆ — Replaced Stooq (JS-walled June 2026). 30+ years of OHLCV for equities/ETFs/futures. No API key required.

**Gotchas:**
- Returns tz-aware DatetimeIndex. Use `tz_convert("UTC")` not `tz_localize` on already-aware indices.
- Set `df.index.name = "date"` so the core engine recognizes it.
- Ticker symbols differ from Stooq: `^GSPC` (not `^spx`), `^NDX` (not `^ndx`), `DX-Y.NYB` (not `^dxy`), `GC=F` (not `gc.f`)
- Futures symbols: `GC=F`, `SI=F`, `PL=F`, `HG=F`
- ETF symbols: `TLT`, `HYG` (no `.us` suffix)
- MOVE index: `^MOVE` — best effort, may not be available
- **pandas 3.0.3 sensitivity:** Same datetime comparison issue as FRED. Both adapters return UTC-localized dates.

**Working tickers:** SPX, NDX, RUT, SOX, HSI, N225, GC=F, SI=F, PL=F, HG=F, DXY, TLT, HYG, MOVE

## Stooq (DEPRECATED — June 2026; re-verified dead 2026-07-09)

**Reliability:** ☆☆☆☆☆ — Dead. Cloudflare JS challenge walls all programmatic access (curl, Python requests, browsers without JS). Returns HTML challenge page instead of CSV. Re-tested 2026-07-09: `stooq.com/q/d/l/?s=^spx&i=d` still returns a `<noscript>` challenge page (HTTP 200, no CSV). Not revived for the failover chains.

**Migration:** All Stooq tickers moved to Yahoo Finance (yfinance). Stooq adapter kept in repo for reference but marked `status: deprecated` in sources.yaml.

## EIA (Energy Information Administration)

**Reliability:** ★★★★☆ — Working as of 2026-06-11. Free key, 60 req/min.

**Gotchas (FIXED 2026-06-11):**
- **Route mapping:** Catalog stores `eia_route` (e.g. `petroleum/pri/spt`, `petroleum/stoc/wstk`). This is NOT in the DB — it's in catalog.yaml only. `_fetch_from_source` looks up the catalog by ticker to find `eia_route` and maps it to `adapter_cfg["route"]` for the EIA adapter.
- **Frequency parameter:** The adapter hardcodes `frequency=daily` by default but reads `cfg.get("frequency")` if available. Weekly series (CRUDE_STOCKS, SPR) must have `frequency: weekly` in catalog.yaml or the API returns 400. The `_fetch_from_source` propagates `frequency` from `series_info` to `adapter_cfg` top-level.
- **Data lag:** EIA data has 2-3 day publication delay. BRENT/WTI showing 3-day staleness is normal.

**Working tickers:** WTI, BRENT, CRUDE_STOCKS, SPR, plus (added 2026-06-22) GASOLINE_STOCKS
(`WGTSTUS1`), DISTILLATE_STOCKS (`WDISTUS1`), REFINERY_UTIL (`WPULEUS3`, route
`petroleum/pnp/wiup`) — make-investment-easy weekly product data. EIA data has a 2-3 day
publication lag; doctor treats that as `ok`, not stale.

**curl tip:** EIA URLs use `[` `]` (e.g. `data[0]`, `facets[series][]`). When testing with
`curl`, pass `-g` or curl's URL globbing mangles them. The Python adapter uses `requests`
with a params dict and is unaffected.

## CoinGecko

**Reliability:** ★★★★☆ — Working as of 2026-06-11. Free/demo key, 30 req/min with key, 10 without.

**Gotchas (FIXED 2026-06-11):**
- **Free tier limit:** `days=max` → `days=365`. Free tier only allows 365 days of history. The adapter now uses `days=365` in `_fetch_ohlcv`.
- **table_kind propagation:** The adapter reads `cfg.get("table_kind")` at the top level. `_fetch_from_source` now propagates `table_kind` from `series_info` to `adapter_cfg` top-level (along with `frequency` and `unit`). Before this fix, all crypto series defaulted to `ohlcv` regardless of catalog setting.
- **Rate limiting:** The adapter rate-limits at 10/min (free) or 30/min (with key). `update --all` may hit this when backfilling multiple crypto series in sequence — retry individual tickers if needed.

**Working tickers:** BTC, ETH (ohlcv), USDT_SUPPLY, USDC_SUPPLY (observations) — all 4 working

## US Treasury FiscalData

**Reliability:** ★★★★☆ — FIXED & WORKING as of 2026-06-22. TGA_DAILY un-paused.

**History:** The old `/v1/accounting/dts/dts_table_1` endpoint was retired (404). The adapter
was rewritten to use `/v1/accounting/dts/operating_cash_balance`, filtering to
`account_type = "Treasury General Account (TGA) Closing Balance"`.

**Gotcha (new schema):** the closing balance is carried in the `open_today_bal` field
(millions USD); the legacy `close_today_bal` field is `null`. The adapter reads
`open_today_bal` and falls back to `close_today_bal`. Verified: 2026-06-17 closing = $956,502M
= prior day's opening, so the field mapping is internally consistent. `source_symbol` in the
catalog is `operating_cash_balance` (documentation only — the endpoint/filter are fixed).

**Why it matters:** daily TGA + RRP gives Hayes' net-dollar-liquidity Δ. Weekly TGA also lives
on FRED (`TGA`/`WTREGEN`) as a cross-check.

**Working tickers:** TGA_DAILY (daily TGA closing balance, ~2022→present)
