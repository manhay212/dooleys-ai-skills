# Source Adapter Reliability & Pitfalls

Last updated: 2026-06-14 (FRED FX release lag finding, cron diagnostic pattern)

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

## Stooq (DEPRECATED — June 2026)

**Reliability:** ☆☆☆☆☆ — Dead. Cloudflare JS challenge walls all programmatic access (curl, Python requests, browsers without JS). Returns HTML challenge page instead of CSV.

**Migration:** All Stooq tickers moved to Yahoo Finance (yfinance). Stooq adapter kept in repo for reference but marked `status: deprecated` in sources.yaml.

## EIA (Energy Information Administration)

**Reliability:** ★★★★☆ — Working as of 2026-06-11. Free key, 60 req/min.

**Gotchas (FIXED 2026-06-11):**
- **Route mapping:** Catalog stores `eia_route` (e.g. `petroleum/pri/spt`, `petroleum/stoc/wstk`). This is NOT in the DB — it's in catalog.yaml only. `_fetch_from_source` looks up the catalog by ticker to find `eia_route` and maps it to `adapter_cfg["route"]` for the EIA adapter.
- **Frequency parameter:** The adapter hardcodes `frequency=daily` by default but reads `cfg.get("frequency")` if available. Weekly series (CRUDE_STOCKS, SPR) must have `frequency: weekly` in catalog.yaml or the API returns 400. The `_fetch_from_source` propagates `frequency` from `series_info` to `adapter_cfg` top-level.
- **Data lag:** EIA data has 2-3 day publication delay. BRENT/WTI showing 3-day staleness is normal.

**Working tickers:** WTI, BRENT, CRUDE_STOCKS, SPR — all 4 working

## CoinGecko

**Reliability:** ★★★★☆ — Working as of 2026-06-11. Free/demo key, 30 req/min with key, 10 without.

**Gotchas (FIXED 2026-06-11):**
- **Free tier limit:** `days=max` → `days=365`. Free tier only allows 365 days of history. The adapter now uses `days=365` in `_fetch_ohlcv`.
- **table_kind propagation:** The adapter reads `cfg.get("table_kind")` at the top level. `_fetch_from_source` now propagates `table_kind` from `series_info` to `adapter_cfg` top-level (along with `frequency` and `unit`). Before this fix, all crypto series defaulted to `ohlcv` regardless of catalog setting.
- **Rate limiting:** The adapter rate-limits at 10/min (free) or 30/min (with key). `update --all` may hit this when backfilling multiple crypto series in sequence — retry individual tickers if needed.

**Working tickers:** BTC, ETH (ohlcv), USDT_SUPPLY, USDC_SUPPLY (observations) — all 4 working

## US Treasury FiscalData

**Reliability:** ★☆☆☆☆ — BROKEN as of 2026-06-11. TGA_DAILY paused in catalog.

**What happened:** The `/v1/accounting/dts/dts_table_1` endpoint returns 404. Treasury restructured their API — all `dts_table_N` endpoints are gone. The replacement endpoint `/v1/accounting/dts/deposits_withdrawals_operating_cash` works (HTTP 200) but has a different schema:
- Old schema: `close_today_bal` (closing balance, millions USD)
- New schema: `transaction_today_amt` (daily transaction amount)
- New endpoint requires summing transactions to compute closing balance — needs a baseline.

**Status:** TGA_DAILY marked `status: paused` in catalog.yaml with notes explaining the issue. Weekly TGA data still available via FRED (`TGA` series, ticker `WTREGEN`). Adapter rewrite needed before re-enabling.

**Working tickers:** None — TGA_DAILY paused
