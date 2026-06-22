# dooleys-market-data — design docs (Phase 0)

These are the original **Phase 0** design documents that specced this skill. They are kept for
context and rationale. They describe intent; for *current* behavior always defer to the
skill's `SKILL.md`, `README.md`, and `references/source-notes.md`.

- **MARKET_DATA_ARCHITECTURE.md** — the why: numbers-vs-words split, config-as-source-of-truth,
  context-window (not disk) as the real constraint, sourcing matrix, phasing.
- **MARKET_DATA_SKILL_SPEC.md** — the what: folder layout, SKILL.md draft, adapter interface,
  schema, seed `catalog.yaml`/`sources.yaml`, the `query stats` output contract.
- **MARKET_DATA_IMPLEMENTATION_PLAN.md** — the ordered build/integration checklist.

## What changed since Phase 0 (as built + the 2026-06-22 fix)

- **Sources:** Stooq (specced) was Cloudflare-walled and replaced by **Yahoo (yfinance)** for
  OHLCV. Treasury's `dts_table_1` (specced) was retired; daily TGA now uses
  `operating_cash_balance`.
- **`daily` command** added as the single robust cron entry point (update → `UPDATE_LOG.md` →
  Parquet export → JSON summary), replacing a fragile shell wrapper that had silently broken
  the daily pipeline.
- **Doctor redesigned** to classify by last-fetch-result (ok / late / broken / no_data) instead
  of a fixed staleness threshold, eliminating constant false alarms.
- **`query spread`** added (a − b) for rate spreads like Hayes' 2Y − EFFR.
- **KOL series added** to the catalog: EFFR, SRF (repo), term premium, broad USD, Henry Hub
  natgas, EIA gasoline/distillate stocks + refinery utilization, daily TGA.
- Runs under **pandas 3.x / numpy 2.x**; date filtering made tz/resolution-safe.

See `references/source-notes.md` for the full migration history.
