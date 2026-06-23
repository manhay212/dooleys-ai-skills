---
name: dooleys-polymarket-reader
description: Read macro/investment-relevant signals from Polymarket (the prediction market) via its public, keyless Gamma + CLOB read APIs. Use this skill to scan curated macro categories (Fed/rates, inflation, elections, geopolitics, commodities, crypto) for SIGNIFICANT markets — flagged by extreme consensus, fast repricing (big 1d/1w odds moves), conviction volume, and high-stakes toss-ups — returned as a ranked, de-noised JSON feed; OR to keyword-search Polymarket ad-hoc; OR to deep-dive one event/market (full odds + optional price-history curve). The skill scopes + scores + ranks; the agent interprets investment implications. No API key required (Polymarket reading is public; the POLYMARKET_* trading keys are NOT used).
version: 1.0.0
category: dooleys
---

# Polymarket Reader Skill

Reads **prediction-market signals** from [Polymarket](https://polymarket.com) — the largest
real-money prediction market — via its public, **keyless** Gamma and CLOB read APIs. Because
participants wager real money, Polymarket odds are a high-information early signal for macro events
that traditional media lags on. The Trump-2024 win was priced in by Polymarket weeks before polls
caught up; Hormuz-closure probabilities tracked oil futures more tightly than news headlines.

This is a pure **API-flavor** skill (no browser, no session, no login) with three entry scripts
sharing `polymarket_client.py` (HTTP transport) and `polymarket_common.py` (pure signal/scoring
logic, fully unit-tested):

| Script | Role | Typical caller |
|--------|------|----------------|
| `polymarket_reader.py` | Scan macro category tags → ranked, de-noised significant-market feed | Agent / cron briefing |
| `polymarket_search.py` | Ad-hoc keyword search — "what does the market say about X?" | Agent answering a specific question |
| `polymarket_event.py` | Deep-dive one event by URL / slug / id; optional odds time-series | Agent research, charting |

## When to Use This Skill

Use **`polymarket_reader.py`** (macro scan) when:
- You want a curated feed of the most significant prediction-market signals across macro themes
  (monetary policy, elections, geopolitics, assets/commodities/crypto)
- You are running a daily briefing or monitoring for anything that has repriced materially

Use **`polymarket_search.py`** (ad-hoc search) when:
- A user asks "what does Polymarket say about [topic]?" and no pre-configured category covers it
- You want a quick probability snapshot for a specific question

Use **`polymarket_event.py`** (drill-down) when:
- You already have an event URL, slug, or id (e.g. from the reader/search output)
- You need the full market breakdown, description, or historical odds curve (`--history`)

**When NOT to use the reader directly:** Polymarket hosts thousands of markets including pop-culture
bets, tweet-count wagers, sports predictions, and other "for fun" markets that are noise for macro
analysis. The reader's de-noise pipeline removes these by default using a tag denylist. If you want
to see those markets anyway, use `--all` to include filtered-out events, `--no-exclude` to disable
the tag denylist, `--tags` to target any raw tag, or `polymarket_search.py` with a specific query.

## Authentication Model

**None required.** Polymarket's Gamma event API and CLOB price-history API are public and
unauthenticated. No API key, no OAuth, no browser session needed.

The `POLYMARKET_API_KEY`, `POLYMARKET_SECRET`, and `POLYMARKET_PASSPHRASE` environment variables
exist in the credentials template for a **future trading/v2 integration** and are **NOT read or
used by this skill**. Do not set or reference them for reading. This skill will work with no
environment variables at all.

## The Signal Engine

Each market within an event is evaluated for four binary **flags** and a continuous
**significance_score** (0–1). The event's `event_significance` is the max significance_score across
its markets.

### Flags (all four must be interpreted together)

| Flag | Condition | Threshold |
|------|-----------|-----------|
| `extreme_consensus` | Leading-outcome implied probability ≥ threshold | `extreme_p` = **0.85** |
| `big_move` | \|1-week price change\| ≥ threshold OR \|1-day price change\| ≥ threshold | `move_1w` = **0.10**, `move_1d` = **0.05** |
| `high_conviction` | 24h volume ≥ threshold | `conviction_vol` = **50,000** |
| `high_stakes_tossup` | Probability in [tossup_lo, tossup_hi] AND `high_conviction` | `tossup_lo` = **0.40**, `tossup_hi` = **0.60** |

### Significance Score

A weighted composite score (0–1) combining four normalized dimensions:

| Dimension | Weight | Normalization |
|-----------|--------|---------------|
| `conviction` | **0.35** | log10(vol24h) / log10(conviction_ref=10,000,000), capped at 1 |
| `extremeness` | **0.25** | abs(implied_prob − 0.5) / 0.5 |
| `momentum` | **0.30** | abs(move_1w) / momentum_ref=0.25, capped at 1 |
| `tossup` | **0.10** | 1.0 if high_stakes_tossup else 0.0 |

### De-Noise Pipeline

The reader passes each enriched event through the following gates **in order** (watchlisted events
bypass all gates and are always kept):

1. **Macro-noise tag denylist** — events whose `all_tags` intersect the `exclude_tags` list are
   dropped. Default denylist: `["pop-culture", "tweets-markets", "mentions-markets", "sports"]`.
   This removes "Elon tweet-count" markets, celebrity bets, sports wagers, etc. Bypassed by:
   `--no-exclude` flag (disables entirely) or adding an event to `config/watchlist.json`.
2. **Volume floor** — events with `volume_24h` < `min_volume` (default **10,000**) are dropped.
   Override per-run with `--min-volume`.
3. **Assets-only horizon cut** — events in the `assets` bucket (commodities, crypto, ETF) with
   fewer than `min_horizon_days` (**1.0**) to resolution are dropped (short-dated crypto futures
   are noise for macro analysis; other buckets are not cut).
4. **Min-score filter** — events with `event_significance` < `--min-score` (default **0.0**) are
   dropped.
5. **Rank and cap** — watchlisted events are pinned to the top; remaining events are sorted
   descending by `event_significance`; result is capped at `--limit` (default **40**).

## Function 1: polymarket_reader.py — Macro Category Scan

**Purpose:** Scan curated macro-category tag slugs, enrich every event with the signal engine, apply
the de-noise pipeline, and write a ranked JSON feed of the most significant markets.

**Steps:**
1. Resolve category → tag-slug mapping from config (or `--categories`/`--tags` overrides).
2. Fetch events per tag from the Gamma API, deduplicating events that appear in multiple tags.
3. Enrich all events; load `watchlist.json` and inject always-track events (deduplicated).
4. Run de-noise pipeline → rank → cap.
5. Write `output_polymarket_reader.json`.

**Command:**
```bash
python3 polymarket_reader.py                                   # all macro categories, top 40
python3 polymarket_reader.py --categories monetary,geopolitics # specific buckets
python3 polymarket_reader.py --tags fed-rates,bitcoin          # raw tag slugs (bypasses categories)
python3 polymarket_reader.py --min-score 0.5                   # only higher-significance events
python3 polymarket_reader.py --min-volume 100000               # override volume floor
python3 polymarket_reader.py --limit 20 --scan-limit 20        # narrower scan
python3 polymarket_reader.py --all                             # include filtered-out events in output
python3 polymarket_reader.py --no-exclude                      # disable the tag denylist
python3 polymarket_reader.py --watchlist config/watchlist.json # path to custom watchlist
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--categories` | all buckets | Comma-separated bucket names (monetary, elections, geopolitics, assets) |
| `--tags` | — | Comma-separated raw tag slugs; overrides --categories |
| `--min-score` | 0.0 | Minimum event_significance to keep |
| `--min-volume` | config value (10,000) | Override volume floor for this run |
| `--limit` | 40 | Max events in output |
| `--scan-limit` | 40 | Max events fetched per tag from API |
| `--all` | false | Include filtered-out events in output under `filtered_out` key |
| `--no-exclude` | false | Disable the macro-noise tag denylist |
| `--config` | `config/categories.json` | Path to categories/thresholds/weights config |
| `--watchlist` | `config/watchlist.json` | Path to always-track events list |
| `--output` | `output_polymarket_reader.json` | Output file path |

**Exit codes:** `0` success · `1` no categories/tags resolved · `2` fatal error before any result.

## Function 2: polymarket_search.py — Ad-Hoc Keyword Search

**Purpose:** Search Polymarket events by keyword and return the top matches with the same signal
enrichment as the reader. No de-noise pipeline is applied — all results are returned sorted by
`event_significance`.

**Command:**
```bash
python3 polymarket_search.py "taiwan strait"       # positional query
python3 polymarket_search.py --query "fed rate cut" --limit 10
python3 polymarket_search.py "bitcoin 100k" --limit 5
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `query` (positional) | — | Search text |
| `--query` | — | Search text (alternative to positional) |
| `--limit` | 20 | Max events returned |
| `--config` | `config/categories.json` | Path to thresholds/weights config |
| `--output` | `output_polymarket_search.json` | Output file path |

**Exit codes:** `0` success · `1` no query provided or search error.

## Function 3: polymarket_event.py — Single Event Deep-Dive

**Purpose:** Fetch and enrich one specific event by URL, slug, or numeric id. Optionally attach
the full odds time-series (price-history curve) per market via the CLOB API. Useful for detailed
analysis of one event after the reader/search identifies it.

**Command:**
```bash
# By URL
python3 polymarket_event.py "https://polymarket.com/event/fed-decision-in-july"

# By slug
python3 polymarket_event.py fed-decision-in-july

# By numeric id
python3 polymarket_event.py 521043

# With odds history (1-week window, 180-minute fidelity by default)
python3 polymarket_event.py fed-decision-in-july --history

# Custom history window and resolution
python3 polymarket_event.py fed-decision-in-july --history --interval 1m --fidelity 60
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `ref` (positional) | required | Event URL, slug, or numeric id |
| `--history` | false | Attach odds time-series per market |
| `--interval` | `1w` | History window: `1d`, `1w`, `1m`, `max` |
| `--fidelity` | 180 | History resolution in minutes |
| `--config` | `config/categories.json` | Path to thresholds/weights config |
| `--output` | `output_polymarket_event.json` | Output file path |

**Exit codes:** `0` success · `1` event not found or lookup error.

## Output Format

All output files are JSON with a top-level `timestamp` (ISO-8601 UTC).

### polymarket_reader.py → `output_polymarket_reader.json`
```json
{
  "timestamp": "2026-06-24T10:00:00+00:00",
  "params": {
    "categories": ["monetary", "elections", "geopolitics", "assets"],
    "tags": null,
    "min_score": 0.0,
    "min_volume": 10000,
    "limit": 40,
    "exclude_tags": ["pop-culture", "tweets-markets", "mentions-markets", "sports"]
  },
  "buckets_scanned": ["monetary", "elections", "geopolitics", "assets"],
  "counts": {
    "events_scanned": 337,
    "events_kept": 40,
    "filtered_out": 297
  },
  "events": [ ... ],
  "filtered_out": [],
  "errors": {}
}
```

### polymarket_search.py → `output_polymarket_search.json`
```json
{
  "timestamp": "2026-06-24T10:00:00+00:00",
  "query": "taiwan",
  "count": 3,
  "events": [ ... ],
  "errors": {}
}
```

### polymarket_event.py → `output_polymarket_event.json`
```json
{
  "timestamp": "2026-06-24T10:00:00+00:00",
  "requested_ref": "fed-decision-in-july",
  "event": { ... },
  "errors": {}
}
```

### Event record shape (appears in `events[]` and `event` fields)
```json
{
  "id": "521043",
  "title": "Fed cuts rates in July?",
  "slug": "fed-decision-in-july",
  "url": "https://polymarket.com/event/fed-decision-in-july",
  "end_date": "2026-07-30T21:00:00Z",
  "buckets": ["monetary"],
  "tags": ["fed-rates"],
  "all_tags": ["economy", "fed-rates", "inflation", "macro-indicators"],
  "volume_24h": 250000.0,
  "watchlisted": false,
  "event_significance": 0.7823,
  "description": "Will the Federal Reserve cut rates at its July 2026 meeting? ...",
  "markets": [
    {
      "question": "Will the Fed cut rates in July 2026?",
      "consensus_outcome": "Yes",
      "implied_prob": 0.72,
      "extremeness": 0.44,
      "move_1d": 0.03,
      "move_1w": 0.12,
      "volume_24h": 250000.0,
      "volume_total": 5200000.0,
      "liquidity": 180000.0,
      "days_to_resolve": 36.4,
      "flags": {
        "extreme_consensus": false,
        "big_move": true,
        "high_conviction": true,
        "high_stakes_tossup": false
      },
      "significance_score": 0.7823,
      "price_history": [
        {"t": 1750000000, "p": 0.61},
        {"t": 1750086400, "p": 0.65}
      ]
    }
  ]
}
```

**Field notes:**
- `all_tags` — the native Polymarket tag slugs on the event (used by the denylist filter). Always
  present; inspect this field to understand why an event was or wasn't filtered.
- `buckets` — macro category bucket(s) this event was found under (e.g. `monetary`, `geopolitics`).
  Empty for search/event results.
- `tags` — the raw tag slugs used to fetch this event (subset of `all_tags`). Empty for search/event.
- `watchlisted` — `true` for events from `watchlist.json`; these bypass all de-noise gates.
- `event_significance` — max `significance_score` across the event's markets (0–1).
- `implied_prob` — the leading outcome's current implied probability (0–1).
- `extremeness` — `abs(implied_prob − 0.5) / 0.5`; 0 = pure tossup, 1 = certainty.
- `price_history` — list of `{t: unix_timestamp, p: probability}` points; only present when
  `polymarket_event.py` is run with `--history`.
- `description` — event description text; only present in `polymarket_event.py` output.
- `filtered_out` — only populated in the reader when `--all` is passed; otherwise an empty list.

## Configuration

### config/categories.json — buckets, thresholds, weights, exclude_tags

All defaults are built into `polymarket_common.py`; the config file is **optional** — copy the
example and edit to customise:

```bash
cp config/categories.example.json config/categories.json
```

```json
{
  "buckets": {
    "monetary":    ["economy", "fed-rates", "interest-rates", "inflation", "recession", "gdp", "macro-indicators"],
    "elections":   ["elections", "politics", "us-politics", "federal-government"],
    "geopolitics": ["geopolitics", "international-affairs", "war", "middle-east"],
    "assets":      ["commodities", "crypto", "bitcoin", "ethereum", "etf"]
  },
  "horizon_cut_buckets": ["assets"],
  "exclude_tags": ["pop-culture", "tweets-markets", "mentions-markets", "sports"],
  "thresholds": {
    "extreme_p": 0.85, "move_1w": 0.10, "move_1d": 0.05,
    "conviction_vol": 50000, "tossup_lo": 0.40, "tossup_hi": 0.60,
    "min_volume": 10000, "min_horizon_days": 1.0,
    "momentum_ref": 0.25, "conviction_ref": 10000000
  },
  "weights": { "conviction": 0.35, "extremeness": 0.25, "momentum": 0.30, "tossup": 0.10 }
}
```

The `exclude_tags` list is the **macro-noise denylist**: events whose Polymarket native tags include
any of these strings are dropped from the reader's output. Add more tags to tighten the filter;
pass `--no-exclude` to temporarily disable it.

### config/watchlist.json — always-track events

Events in this file bypass all de-noise gates (volume, denylist, horizon, score) and are pinned to
the top of the reader output. Each entry is a URL, slug, or numeric id:

```bash
cp config/watchlist.example.json config/watchlist.json
```

```json
{
  "events": [
    "fed-decision-in-july",
    "https://polymarket.com/event/how-many-fed-rate-cuts-in-2026"
  ]
}
```

## Error Handling

- **Per-tag isolation (reader):** if one tag slug fails (API error / rate limit), it is recorded
  under `errors["tag:<slug>"]` and the scan continues with remaining tags.
- **Per-watchlist isolation (reader):** if a watchlist slug cannot be fetched, it is recorded under
  `errors["watchlist:<slug>"]` and the run continues.
- **Per-market history isolation (event):** if price history for one market fails, `price_history`
  is set to `[]` on that market and the error is recorded under `errors["history:<question>"]`;
  other markets still get their history.
- **Event not found (event script):** prints to stderr and exits 1.
- **Fatal scan error (reader):** prints to stderr and exits 2.

## API Notes

**Endpoints used (all GET, no authentication):**

| Endpoint | Purpose |
|----------|---------|
| `GET https://gamma-api.polymarket.com/events?tag_slug=<slug>&limit=<n>&active=true&order=volume24hr` | Fetch events by tag (reader) |
| `GET https://gamma-api.polymarket.com/public-search?q=<query>&limit_per_type=<n>` | Keyword search (search script) |
| `GET https://gamma-api.polymarket.com/events?slug=<slug>` | Fetch event by slug (event/watchlist) |
| `GET https://gamma-api.polymarket.com/events/<id>` | Fetch event by numeric id (event script) |
| `GET https://clob.polymarket.com/prices-history?market=<token_id>&interval=<1w>&fidelity=<180>` | Price-history curve (event --history) |

**Implementation notes:**
- The Gamma API sometimes returns array fields (`outcomePrices`, `clobTokenIds`) as **JSON-encoded
  strings** rather than actual arrays. `polymarket_common.coerce_list()` handles both forms
  transparently; if parsing breaks after an API change, check these fields first.
- If event lookups start returning empty results, verify that `slug` / `id` fields haven't changed
  in the Gamma response shape (`data[]` vs. top-level list vs. direct object).
- The `prices-history` endpoint returns `{history: [{t, p}]}` where `t` is a Unix timestamp and
  `p` is the probability (0–1 decimal, not percentage).
