# Design: `dooleys-polymarket-reader`

**Date:** 2026-06-24
**Status:** Approved (design); pending implementation plan
**Repo:** `dooleys-ai-skills` (custom skills for the Hermes agent)
**Flavor:** API-based (public HTTP), keyless — closest reference: `dooleys-substack-reader`

---

## 1. Purpose & investment thesis

A **keyless, read-only** skill that turns Polymarket's real-money prediction odds into a clean,
ranked, **de-noised** feed of **macro / investment-relevant signals** for the Hermes agent.

The thesis: because Polymarket is decentralized and carries genuine monetary incentives, when the
odds tilt heavily one way — or reprice fast — that *is* information, often ahead of traditional
media. Canonical example: hours before US media called the 2024 election, Polymarket already had
Trump near-certain. The mechanism is verified in live data today, e.g.:

- "Will the Fed increase rates 25bps in July?" moved **+22 points in a week** (`oneWeekPriceChange: +0.219`).
- "Strait of Hormuz traffic returns to normal by end of June?" sits at **3.5%**, down ~14pts/week.

The skill surfaces those signals (extreme consensus, fast repricing, where conviction money sits,
live high-stakes toss-ups) and leaves the **investment interpretation to the agent**.

### Division of labor (decided: Hybrid)
- **Skill does:** coarse category-scoping (macro tag allowlist) + per-market signal computation +
  a tunable composite **significance score** with sensible default de-noise + ranking. Returns a
  ranked shortlist by default; full set behind `--all`.
- **Agent does:** the final "what does this mean for *my* investments" judgment on clean,
  comparable, pre-scored data.

Rationale: keep judgment out of the skill (that's the agent's job) but don't drown the agent in
the hundreds of low-signal open markets Polymarket always has.

---

## 2. API findings (verified live, 2026-06-24)

- **Gamma API (`https://gamma-api.polymarket.com`) is fully public — no key needed** for reading
  markets, events, odds, and momentum. The user's `POLYMARKET_API_KEY/SECRET/PASSPHRASE` are for
  the **CLOB *trading* API** (placing orders) and authenticated position data — **the reader needs
  none of them.**
- Events carry **inline `tags`**; **`tag_slug` filtering on `/events` works** (verified:
  `economy`, `fed-rates`, `interest-rates`, `inflation`, `recession`, `gdp`, `elections`,
  `politics`, `geopolitics`, `international-affairs`, `commodities`, `crypto`, …).
- Markets carry **inline** `outcomes`, `outcomePrices` (implied probabilities), `lastTradePrice`,
  `oneDayPriceChange`, `oneWeekPriceChange`, `volume24hr`, `volume`, `liquidity`, `endDate`,
  `clobTokenIds` — so all four signals are computable **without extra calls**.
- `GET /events?tag_slug=…&closed=false&active=true&order=volume24hr&ascending=false&limit=N` —
  verified scan query.
- `GET /events?slug=<slug>` — verified single-event lookup (returns a 1-element list).
- `GET /public-search?q=<query>&limit_per_type=N` — verified → `{ "events": [...], "pagination": {...} }`.
- `GET https://clob.polymarket.com/prices-history?market=<tokenId>&interval=<>&fidelity=<>` —
  verified keyless time series → `{ "history": [ {"t": <unix>, "p": <price>}, … ] }`.

**Noise leaks through tags** (the crux): even within `economy`, low-signal markets appear (e.g.
"Largest Company by end of June?", NVIDIA at 97%). Tag filtering alone is insufficient → a
signal-scoring + de-noise layer is required.

---

## 3. Architecture

Mirrors the `dooleys-substack-reader` split (thin HTTP client + pure logic + focused entry scripts).

```
dooleys-polymarket-reader/
  SKILL.md                    # agent instructions (frontmatter: name, description, version,
                              #   category: dooleys; no required_environment_variables)
  README.md                   # human setup + testing walkthrough
  requirements.txt            # requests ; pytest (tests)
  .gitignore
  config/
    categories.example.json   # bucket → tag-slug map + thresholds + score weights
    watchlist.example.json     # optional: events/markets to ALWAYS include (by slug/url)
  polymarket_client.py        # HTTP transport (Gamma + CLOB-read), retry/backoff, NO auth
  polymarket_common.py        # PURE logic: signals, flags, scoring, de-noise, url/slug parsing
  polymarket_reader.py        # ENTRY: scan macro categories → ranked shortlist (default)
  polymarket_search.py        # ENTRY: ad-hoc keyword search
  polymarket_event.py         # ENTRY: deep-dive one event/market by url|slug (+ optional history)
  tests/
    test_polymarket_common.py # offline unit tests on fixtures (TDD)
```

Conventions (from repo CLAUDE.md): `SKILL.md`/`README.md` at skill root; env-first/file-fallback
(here: **no creds**); never commit secrets/output/config; self-contained, no cross-skill imports;
JSON output to `output_{function}.json` with top-level `timestamp`; per-item error isolation.

---

## 4. The signal engine (`polymarket_common.py` — pure, unit-tested)

### 4.1 Per-market computed fields
From inline Gamma market fields:

| Field | Definition |
|-------|-----------|
| `implied_prob` | max of `outcomePrices` (the consensus probability) |
| `consensus_outcome` | the outcome label at that price (e.g. "Yes"/"No"/candidate) |
| `extremeness` | `abs(implied_prob - 0.5) / 0.5` → 0..1 |
| `move_1d` | `abs(oneDayPriceChange)` in points (None-safe → 0.0) |
| `move_1w` | `abs(oneWeekPriceChange)` in points (None-safe → 0.0) |
| `volume_24h` | `volume24hr` |
| `volume_total` | `volume` |
| `liquidity` | `liquidity` |
| `days_to_resolve` | `(endDate - now)` in days (None if no endDate) |

All parsing is None/format-tolerant (`outcomePrices`/`clobTokenIds` arrive as JSON strings in some
payloads and as arrays in others — handle both).

### 4.2 Flags (the four chosen signal patterns; thresholds tunable via config)
- `extreme_consensus` — `implied_prob >= EXTREME_P` (default 0.85)
- `big_move` — `move_1w >= MOVE_1W` (default 0.10) **or** `move_1d >= MOVE_1D` (default 0.05)
- `high_conviction` — `volume_24h >= CONVICTION_VOL` (default 50_000)
- `high_stakes_tossup` — `TOSSUP_LO <= implied_prob <= TOSSUP_HI` (default 0.40–0.60) **and**
  `high_conviction`

### 4.3 `significance_score` (0..1)
Weighted blend (weights in config, defaults below; normalized so score ∈ [0,1]):

```
score = W_conviction * conviction_norm    # log10(volume_24h) scaled to 0..1 vs a reference cap
      + W_extremeness * extremeness        # 0..1
      + W_momentum    * momentum_norm      # min(1, move_1w / MOMENTUM_REF)  (MOMENTUM_REF=0.25)
      + W_tossup      * tossup_term         # 1.0 if high_stakes_tossup else 0
```
Default weights: `conviction 0.35, extremeness 0.25, momentum 0.30, tossup 0.10` (sum 1.0).
Ranking is by `significance_score` desc.

### 4.4 De-noise pipeline (default; every step tunable / `--all` bypasses the cut)
1. **Category allowlist** — only markets reached via the configured tag slugs (coarse).
2. **Volume floor** — drop `volume_24h < MIN_VOLUME` (default 10_000) — kills thin/noisy odds.
3. **Bucket-specific horizon cut** — drop `days_to_resolve < MIN_HORIZON_DAYS` (default 1.0)
   **only** for markets whose matched bucket is `assets` (crypto/commodities). Kills "BTC next
   5 min" intraday noise *without* dropping a same-day Fed decision (which is in `monetary`).
4. **Rank** by `significance_score` desc; **cap** to top `--limit` (default 40).
`filtered_out_count` is always reported; `--all` returns the full pre-cut set (still scored/ranked).

### 4.5 URL / slug parsing
`parse_event_ref(s)` accepts: a Polymarket URL (`polymarket.com/event/<slug>` or
`/market/<slug>`), a bare slug, or a numeric event id → returns `{kind: 'slug'|'id', value}`.

---

## 5. Category buckets (default scope: all four IN)

Config `categories.json` maps bucket name → list of tag slugs (code ships these defaults; config
overrides). `--categories a,b` selects buckets by name; `--tags x,y` overrides with raw slugs.

| Bucket | Default tag slugs |
|--------|-------------------|
| `monetary` (Monetary & macro) | `economy`, `fed-rates`, `interest-rates`, `inflation`, `recession`, `gdp`, `macro-indicators` |
| `elections` (Elections & policy) | `elections`, `politics`, `us-politics`, `federal-government` |
| `geopolitics` (Geopolitics & conflict) | `geopolitics`, `international-affairs`, `war`, `middle-east` |
| `assets` (Commodities, crypto & assets) | `commodities`, `crypto`, `bitcoin`, `ethereum`, `etf` |

Notes:
- Slugs that 404/return empty are skipped (recorded in `errors`, run continues) — the allowlist is
  intentionally generous; missing slugs are harmless.
- The `assets` bucket is the only one subject to the short-horizon cut (§4.4 step 3).
- Events can match multiple buckets/tags; dedupe by event `id`, keep the union of matched
  `buckets`/`tags` on the record.

---

## 6. Entry points

### 6.1 `polymarket_reader.py` — scan macro categories (the default / cron entry)
**Flow:**
1. Resolve buckets → tag slugs (`--categories` / `--tags` / config default).
2. For each slug: `GET /events?tag_slug=<slug>&closed=false&active=true&order=volume24hr&ascending=false&limit=<scan_limit>`.
3. Dedupe events by `id`; union matched buckets/tags.
4. For each event's markets: compute signals + flags + score (§4).
5. De-noise + rank + cap (§4.4).
6. Merge `watchlist.json` events (if present): always included, `watchlisted: true`.
7. Write `output_polymarket_reader.json` (§7). Per-tag failure → `errors`, continue.

**Flags:** `--categories`, `--tags`, `--min-score`, `--min-volume`, `--limit` (output cap),
`--scan-limit` (events fetched per tag), `--all`, `--output`.
**Exit codes:** `0` ok · `1` no categories/tags resolved · `2` fatal before any tag ran.

### 6.2 `polymarket_search.py` — ad-hoc keyword search
**Flow:** `GET /public-search?q=<query>&limit_per_type=<n>` → take `events` → compute the same
signal block → rank by score → write `output_polymarket_search.json`. **No** category restriction
(search is intentionally cross-cutting). Query from positional arg or `--query`.
**Flags:** positional `query`, `--limit`, `--output`. **Exit:** `0` ok · `1` no query.

### 6.3 `polymarket_event.py` — deep-dive one event/market
**Flow:** `parse_event_ref` → `GET /events?slug=<slug>` (or `/events/<id>`) → full detail: all
markets, outcomes, prices, signals, description, end date, volumes. `--history`: for each market's
primary `clobTokenIds[0]`, `GET clob/prices-history?market=<tokenId>&interval=<>&fidelity=<>` →
odds time series (the curve behind the consensus). Write `output_polymarket_event.json`.
**Flags:** positional `ref` (url|slug|id), `--history`, `--interval` (default `1w`),
`--fidelity` (default 180), `--output`. **Exit:** `0` ok · `1` ref not resolvable.

---

## 7. Output format (event-grouped, JSON, top-level `timestamp`)

Unit = **event** (multi-outcome events like "How many Fed cuts in 2026" group naturally). Each
event carries `event_significance` (max of its markets' `significance_score`) used for ranking.

```json
{
  "timestamp": "2026-06-24T...Z",
  "params": { "categories": ["monetary","elections","geopolitics","assets"],
              "min_score": 0.0, "min_volume": 10000, "limit": 40 },
  "buckets_scanned": ["monetary","elections","geopolitics","assets"],
  "counts": { "events_scanned": 180, "events_kept": 38, "filtered_out": 142 },
  "events": [
    {
      "id": "...", "title": "Fed decision in July?",
      "slug": "fed-decision-in-july",
      "url": "https://polymarket.com/event/fed-decision-in-july",
      "end_date": "2026-07-29T...Z",
      "buckets": ["monetary"], "tags": ["fed-rates","economy"],
      "volume_24h": 1149937, "watchlisted": false,
      "event_significance": 0.81,
      "markets": [
        {
          "question": "Will there be no change in Fed interest rates ...?",
          "consensus_outcome": "Yes", "implied_prob": 0.735,
          "extremeness": 0.47, "move_1d": 0.01, "move_1w": 0.20,
          "volume_24h": 1149937, "volume_total": ..., "liquidity": ...,
          "days_to_resolve": 35.1,
          "flags": { "extreme_consensus": false, "big_move": true,
                     "high_conviction": true, "high_stakes_tossup": false },
          "significance_score": 0.81
        }
      ]
    }
  ],
  "filtered_out": [],          // populated only with --all
  "errors": { "tag:rate-hikes": "HTTP 404" }
}
```

`search` output: same event shape, no `buckets_scanned`/`counts.filtered_out`, adds `query`.
`event` output: single `event` object (not a list); with `--history`, each market gets a
`price_history: [ {"t","p"}, … ]` array.

---

## 8. Auth, config, hygiene

- **Keyless.** No `config/credentials.json`; **no required env vars**. SKILL.md documents that
  `POLYMARKET_API_KEY/SECRET/PASSPHRASE` exist but are **unused by the reader** (trading/positions
  — a documented v2 idea).
- `config/categories.json` (gitignored; ship `.example`) — bucket→slug map + thresholds + weights.
  Code holds the same values as built-in defaults; the file overrides without code edits.
- `config/watchlist.json` (gitignored; ship `.example`) — optional always-track list.
- **`.gitignore`:** `config/*.json` (except `*.example`), `output_*.json`, `__pycache__/`.
- **Security — `tmp.env`:** the repo currently **tracks** `tmp.env` containing the user's live
  keys. It will **not** be committed; add to `.gitignore` and `git rm --cached tmp.env` so it stops
  being tracked. The reader only needs it to *demonstrate the keys are not required*, then it goes.

---

## 9. Testing strategy

- **Unit (TDD, offline)** — `tests/test_polymarket_common.py` on fixture market/event dicts:
  signal math (incl. None-safe price-change & JSON-string `outcomePrices`), each flag threshold,
  scoring monotonicity, de-noise pipeline (volume floor, assets-only horizon cut, cap), `parse_event_ref`.
- **Failure path** — no network / unknown tag → clean exit + `errors` populated, no crash.
- **Live smoke** — run all three scripts against real public data: `reader` returns ranked macro
  events and pushes "Largest Company"-style foregone markets below the cut; `search "taiwan"`
  returns the China×Taiwan event; `event <slug> --history` returns the odds curve. Confirm the
  reader runs with the `POLYMARKET_*` vars **absent** (proves keyless).
- Clean up generated `output_*.json` / `config/*.json` before commit.

---

## 10. Out of scope (v1) / future

- Trading / order placement (CLOB write) — needs the L2 keys; not a reader concern.
- "Smart money" position/whale tracking (Data API `/holders`, `/trades`, `/positions`) — deferred
  v2 idea; still keyless for the public ones.
- Custom relevance ML / sentiment — the score is transparent heuristics by design.
- Cross-run history/state (trend memory) — each run is stateless; the agent or a cron can persist.

---

## 11. Open implementation notes

- Confirm exact field name casing on `oneDayPriceChange`/`oneWeekPriceChange` per market vs event
  (seen on markets; verify None-handling). Confirm `volume24hr` presence at market level (seen) vs
  only event level — fall back to event-level when a market lacks it.
- `outcomePrices`/`clobTokenIds` may be JSON-encoded strings — parse defensively in the client or a
  `_coerce` helper in common.
- `scan_limit` per tag should be modest (e.g. 40) to stay unobtrusive; total events deduped before
  scoring.
