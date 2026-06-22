# Market Data Layer — Implementation Plan (Phase 0)

**Created:** 2026-06-07
**Status:** Ready to execute on the Hermes host
**Recommended canonical destination:** `~/.hermes-backup-repo/docs/my-agentic-setup/MARKET_DATA_IMPLEMENTATION_PLAN.md`
**Companion docs:** `MARKET_DATA_ARCHITECTURE.md`, `MARKET_DATA_SKILL_SPEC.md`

> This is the ordered checklist the agent (Chief of Staff) executes on the host. It follows
> existing disciplines: golden naming (folders kebab-case, files UPPER_SNAKE_CASE.md),
> backup-restore symmetry, the Cross-Reference Map, and the custom-skill clone+symlink flow.
> Each step is concrete. Do NOT skip the linkage section (§5) — "changes ripple."

---

## 0. Pre-flight (Governing Principle #2: be informed before acting)

- [ ] Read `MARKET_DATA_ARCHITECTURE.md` and `MARKET_DATA_SKILL_SPEC.md` fully.
- [ ] Read `docs/my-agentic-setup/SYSTEM_ARCHITECTURE.md`, `KNOWLEDGE_LINKAGE_STRATEGY.md`, `SKILLS_MANAGEMENT.md` (touched by this change).
- [ ] Confirm free API keys obtained:
      FRED (https://fred.stlouisfed.org/docs/api/api_key.html),
      EIA (https://www.eia.gov/opendata/register.php),
      CoinGecko demo key (optional), Nasdaq Data Link (optional).
- [ ] Run `backup-to-github.sh` first so there's a clean rollback point.

---

## 1. Scaffold `market-data/`

```bash
mkdir -p ~/.hermes-backup-repo/market-data/{config,db,exports,logs}
cd ~/.hermes-backup-repo/market-data
```

- [ ] Create `config/sources.yaml` (from SKILL_SPEC §6).
- [ ] Create `config/catalog.yaml` (seed from SKILL_SPEC §7; this is the user's private catalog — stays here, NOT in the skill repo).
- [ ] Create `db/schema.sql` (from SKILL_SPEC §5).
- [ ] Create `DATA_DICTIONARY.md` (document every table, unit, source quirk: adjusted-close caveat for Stooq, weekly cadence for H.4.1 series, `.`→NaN for FRED, revision policy = latest-revision).
- [ ] Create `README.md` (LLM+human dashboard of what's tracked).
- [ ] Create `.gitignore`:
      ```
      db/*.db
      db/*.db-wal
      db/*.db-shm
      logs/*.jsonl
      ```
  (Config, schema, dictionary, README, and `exports/` are git-tracked. The live DB is a cache.)

---

## 2. Build & deploy the `dooleys-market-data` skill

Follow `custom-skill-development` SKILL.md (code-skill path).

- [ ] In the `dooleys-ai-skills` repo, create `dooleys-market-data/` with the structure in SKILL_SPEC §2.
- [ ] Implement `market_data.py`, `db.py`, `catalog.py`, `summarize.py`, and `sources/{fred,stooq,eia,coingecko,treasury}.py` to the adapter interface (SKILL_SPEC §4).
- [ ] Write `SKILL.md` (SKILL_SPEC §3) and `README.md` (SKILL_SPEC §9) — keep both consistent on credentials (env vars = Option A primary).
- [ ] `requirements.txt`: `requests pandas pyyaml pyarrow` (yfinance optional fallback).
- [ ] Test locally against 2–3 series per source before committing.
- [ ] Commit & push to GitHub.
- [ ] On host: `cd ~/.hermes/custom-skills && git pull`
- [ ] Symlink: `ln -sfn ~/.hermes/custom-skills/dooleys-market-data ~/.hermes/skills/dooleys/market-data`
- [ ] Add keys to `~/.hermes/.env`:
      ```
      MARKET_DATA_DIR=/home/dooleys/.hermes-backup-repo/market-data
      FRED_API_KEY=<key>
      EIA_API_KEY=<key>
      COINGECKO_API_KEY=<optional>
      NASDAQ_DATA_LINK_API_KEY=<optional>
      ```
- [ ] `/restart` in chat. Verify: `hermes skills list | grep market-data`.

---

## 3. Initialize the DB and run the 30-year backfill

```bash
cd ~/.hermes/custom-skills/dooleys-market-data
python3 market_data.py init            # creates db/market.db from schema.sql; writes default config if absent
python3 market_data.py sync-catalog    # registers every series from catalog.yaml into `series`
python3 market_data.py backfill --all  # 30y where available, else max; resumable, rate-limited
python3 market_data.py doctor          # confirm coverage; note any gaps/failures
python3 market_data.py export --format parquet   # first snapshot → exports/market_snapshot.parquet
```

- [ ] Backfill is a long, resumable job (rate limits). Re-run on failure; UPSERTs make it safe.
- [ ] Review `doctor` output; for any series that failed or has short history, record the reason in `DATA_DICTIONARY.md` (expected for MOVE / HK housing / shipping).
- [ ] Spot-check: `python3 market_data.py query stats --ticker SPX --windows 1y,5y` returns sane numbers.

---

## 4. Wire the cron jobs (mirror existing `cron/jobs.json` patterns)

### 4a. Daily ingest (deterministic, `no_agent` script)

- [ ] Create `~/.hermes/scripts/update-market-data.sh`:
      ```bash
      #!/usr/bin/env bash
      set -euo pipefail
      cd "$HOME/.hermes/custom-skills/dooleys-market-data"
      python3 market_data.py update --all
      python3 market_data.py export --format parquet
      ```
      `chmod +x` it.
- [ ] Add a cron job (via `hermes cron` or by editing `jobs.json`) modeled on `daily-backup`:
      ```json
      {
        "name": "daily-market-data-ingest",
        "script": "update-market-data.sh",
        "no_agent": true,
        "schedule": {"kind": "cron", "expr": "0 6 * * *"},
        "deliver": "local",
        "enabled": true
      }
      ```
      (06:00 HKT = after US close. Runs before the 03:00 daily-backup picks up the new snapshot next cycle.)

### 4b. Weekly turning-point briefing (agent job → WhatsApp)

- [ ] Add a cron job modeled on `Daily Twitter Digest` (same WhatsApp origin), profile `investment`:
      ```json
      {
        "name": "Weekly Market Regime Briefing",
        "profile": "investment",
        "skills": ["dooleys-market-data", "wiki-aware-assistant"],
        "skill": "dooleys-market-data",
        "schedule": {"kind": "cron", "expr": "0 9 * * 1"},
        "deliver": "origin",
        "origin": {"platform": "whatsapp", "chat_id": "212802778194016@lid", "chat_name": "Man Hay Hong"},
        "enabled": true,
        "prompt": "Produce the weekly market regime & turning-point briefing. Steps: (1) Run `python3 market_data.py query dashboard --group macro-rates,macro-fed-liquidity,macro-inflation-growth,macro-credit-stress,equity-index,volatility,precious-metals,industrial-metals,energy,fx,crypto` from ~/.hermes/custom-skills/dooleys-market-data. (2) For each major theme, note latest reading, percentile-vs-history, z-score, and distance-to-trigger. (3) Compute/inspect key ratios: copper/gold (HG=F/GC=F), MOVE vs VIX, BTC vs net-liquidity proxy (WALCL-RRP-TGA). (4) Cross-reference KOL trigger levels and latest views in docs/investment/kol/*/KEY_INDICATORS.md and LATEST_VIEWS.md. (5) Web-search the past week's material macro events (CPI/jobs/FOMC/geopolitics) and log notable ones via `add-event`. (6) Assess where we are in each major cycle (Hayes liquidity, commodity rotation per PRECIOUS_METALS_CRYPTO_ROTATION.md) and how close/far we are from turning points, citing the actual data. (7) End with 'What to watch next'. Keep to ~600 words, WhatsApp *bold* for section headers. This is mid/long-term regime analysis, NOT trade signals."
      }
      ```

- [ ] After editing `jobs.json`, verify with `hermes cron list`.

---

## 5. Knowledge linkage — the Cross-Reference Map (MANDATORY, do not skip)

Per `default/SOUL.md` Cross-Reference Map and Governing Principle #1.

### 5a. `profiles/investment/SOUL.md`
- [ ] Under "Documents & Knowledge Linkage", add a **Market Data Layer** subsection:
  > **Market Data (`market-data/`, queried via `dooleys-market-data` skill) — NUMBERS.**
  > Quantitative time-series (prices, yields, Fed liquidity, M2, oil, VIX, FX, crypto, ratios)
  > live in a local SQLite store. **Before any analysis that involves a figure, query the DB —
  > never recall prices from training or guess from a web page.** Use `query stats`/`ratio`/
  > `dashboard` for compact context (percentile, z-score, distance-to-trigger). Use web search
  > only for narrative (news, geopolitics, regulation). The DB is ground truth for numbers.
- [ ] Update the "Retrieval protocol" to: (1) wiki index, (2) KOL latest views, (3) **market-data DB for current + historical numbers**, (4) web-search for events/news, (5) memory.

### 5b. `default/SOUL.md` (Chief of Staff)
- [ ] In "Knowledge Architecture", add a layer note: *"`market-data/` — structured quantitative time-series (the numbers layer beside docs/'s words). Accessed via the `dooleys-market-data` skill, primarily by the investment agent."*
- [ ] Add rows to the **Cross-Reference Map** table:
  | File | Covers | Update When |
  |------|--------|-------------|
  | `~/.hermes-backup-repo/market-data/config/catalog.yaml` | Tracked series registry | Adding/removing tickers or asset classes |
  | `~/.hermes-backup-repo/market-data/config/sources.yaml` | Data source adapters | Adding/removing a data source |
  | `dooleys-market-data` skill | Market-data engine | Skill behavior/version changes |
- [ ] In "Wiki Awareness", add `market-data` to the investment trigger note.

### 5c. `docs/my-agentic-setup/KNOWLEDGE_LINKAGE_STRATEGY.md`
- [ ] Document `market-data/` as the **numbers** layer next to `docs/` (**words**), with the principle: *"docs/ stores words (narrative, theses, KOL views); market-data/ stores numbers (time-series). The `events` table joins them on a timeline."*
- [ ] Add an **"Adding a new ticker / asset class"** protocol (mirrors the new-specialist checklist): edit `catalog.yaml` → `sync-catalog` → `backfill --ticker X` → update DATA_DICTIONARY → snapshot → backup.

### 5d. `docs/my-agentic-setup/SYSTEM_ARCHITECTURE.md`
- [ ] Add `market-data/` to the directory-structure diagram.
- [ ] Add it to the upgrade-safety boundary as **ZERO RISK** (user-space, external to Hermes-managed dirs; DB is a rebuildable cache).

### 5e. `~/wiki/chief-of-staff/index.md`
- [ ] Add tags `#market-data`, `#investment-prices`, `#market-regime` → mapping to `market-data/` + the `dooleys-market-data` skill + the relevant KOL indicator docs.
- [ ] Log the addition in `~/wiki/chief-of-staff/log.md`.

### 5f. `~/wiki/investment/`
- [ ] Create a `concepts/market-data-dashboard.md` page: the tracked series, what each means, and **links from each KOL indicator to its DB ticker** (e.g., Hayes "MOVE Index" ↔ `MOVE`; make-investment-easy "M1-M2 crude timespread" ↔ energy curve; "copper/gold" ↔ `HG=F/GC=F`).
- [ ] Update `~/wiki/investment/index.md` and `log.md`.

### 5g. `README.md` (backup repo dashboard)
- [ ] Add the market-data layer, the two new crons, and the `dooleys-market-data` skill to the dashboard.

### 5h. `docs/my-agentic-setup/SKILLS_MANAGEMENT.md`
- [ ] Add `dooleys-market-data` to the **Current Custom Skills Inventory** table (version 1.0.0, env vars: MARKET_DATA_DIR, FRED_API_KEY, EIA_API_KEY, + optional).

---

## 6. Backup-restore symmetry (ABSOLUTE REQUIREMENT)

Update BOTH scripts together; verify with `verify-backup-restore-symmetry.sh`.

### `backup-to-github.sh`
- [ ] `market-data/config/`, `db/schema.sql`, `DATA_DICTIONARY.md`, `README.md`, and `exports/market_snapshot.parquet` are inside the git backup repo → committed automatically. Confirm `.gitignore` excludes the live `.db`/logs so the binary never bloats git.
- [ ] Confirm `~/.hermes/custom-skills/` rsync already covers the new skill (it does, per SKILLS_MANAGEMENT.md). Add the `market-data` symlink to the symlink loop if not auto-covered.

### `restore-from-github.sh`
- [ ] After restoring `market-data/`, **rebuild the DB**:
      ```bash
      cd "$HERMES_HOME/custom-skills/dooleys-market-data"
      python3 market_data.py init
      python3 market_data.py sync-catalog
      if [ -f "$MARKET_DATA_DIR/exports/market_snapshot.parquet" ]; then
          python3 market_data.py import --from exports/market_snapshot.parquet   # fast path
      else
          python3 market_data.py backfill --all                                  # fallback: rebuild from sources
      fi
      ```
- [ ] Re-create the `dooleys/market-data` symlink in the restore symlink loop.
- [ ] Run `verify-backup-restore-symmetry.sh`.

---

## 7. `.env.template`
- [ ] Add (redacted) `MARKET_DATA_DIR`, `FRED_API_KEY`, `EIA_API_KEY`, `COINGECKO_API_KEY`, `NASDAQ_DATA_LINK_API_KEY` so a fresh host knows to populate them.

---

## 8. Verification (Governing Principle #3: close clean)

- [ ] `hermes skills list | grep market-data` → present.
- [ ] `python3 market_data.py doctor` → all critical series fresh; gaps documented.
- [ ] `hermes -p investment chat -q "How far is MOVE from its policy-action trigger, and where does that sit vs its 30-year range?"` → agent queries the DB and answers with value + percentile + distance, not a guess.
- [ ] `hermes cron list` → both new jobs scheduled.
- [ ] Cross-Reference Map: every file in §5 updated.
- [ ] `backup-to-github.sh` run; pushed to GitHub; symmetry verified.
- [ ] Memory: store the architectural decision (new market-data layer; numbers-vs-words split; config-as-source-of-truth).
- [ ] `~/wiki/chief-of-staff/log.md` and `~/wiki/investment/log.md` updated.

---

## 9. Operating notes (ongoing)

- **Add a ticker:** edit `catalog.yaml` → `sync-catalog` → `backfill --ticker X` → `export` → backup. No code change.
- **Add a source:** new `sources/<name>.py` adapter + `sources.yaml` entry. No core change.
- **A source breaks:** `doctor` flags it; agent falls back to web search for that series; fix the adapter when convenient. The rest keeps working.
- **Revisions:** latest-revision is stored (overwritten on update). If point-in-time backtesting is wanted later, add ALFRED vintages (Phase 2).
- **Don't dump raw rows into context:** always use `query stats/ratio/dashboard`. This is the rule that keeps the whole thing inside the agent's budget.

---

## 10. Deferred (explicitly NOT in Phase 0)

- Derived-signals module (materialized z-scores, regime classifier, Hayes-style composite net-liquidity index). The `query` layer computes these on the fly for now; the seam is defined so a `derived` table slots in later.
- HK housing (Centaline CCL) + shipping (FBX/Baltic) scraper adapters → Phase 1.
- Trigger-breach "tripwire" daily alert → Phase 1.
- Brokerage/portfolio integration → Phase 2.
