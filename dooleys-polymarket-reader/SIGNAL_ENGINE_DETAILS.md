# Signal Engine — Deep Reference

This document explains, end to end, how `dooleys-polymarket-reader` turns raw Polymarket data
into a ranked, de-noised feed of *significant* macro markets. It is the companion to `SKILL.md`:
where `SKILL.md` tells the agent **how to call** the skill, this file explains **what the numbers
mean and why** — with the actual constants, the actual formulas, and hand-computed examples.

All logic described here lives in **`polymarket_common.py`** (pure, unit-tested) and is driven by
**`polymarket_reader.py`**. Nothing here requires an API key.

---

## 1. Mental model

Polymarket is a real-money prediction market. Every market resolves to a payout, so the price of an
outcome **is** the crowd's money-weighted probability of that outcome. The engine's job is to read
those prices across hundreds of markets and answer two questions for an investor-agent:

1. **Is this market saying something *significant*?** — an extreme consensus, a fast repricing, a
   conviction-backed bet, or a high-stakes coin-flip.
2. **Is this market *macro signal* or *noise*?** — a Fed decision is signal; "how many tweets will
   Elon post this week" is noise, even if it has huge volume.

The engine answers #1 with a **significance score** (a 0–1 number) and four **flags**; it answers #2
with a **de-noise pipeline** (category scoping + a tag denylist + volume/horizon floors). It does
**not** make the investment call — it scopes, scores, ranks, and hands a clean feed to the agent,
which does the interpretation.

```
                    ┌─────────────────────────── per market ───────────────────────────┐
Gamma/CLOB API ──▶ parse/normalize ──▶ flags + significance_score ──▶ event aggregate ──▶ de-noise ──▶ rank+cap ──▶ JSON
   (raw fields)     (coerce/to_float)   (compute_flags /              (max over the         (gates in     (watchlist
                                         significance_score)           event's markets)      order)        pinned first)
```

---

## 2. The full data flow

| Stage | Function(s) | Input | Output |
|-------|-------------|-------|--------|
| Fetch | `PolymarketClient.get_events_by_tag` | tag slug | list of raw event dicts |
| Parse | `coerce_list`, `to_float`, `implied_probability`, `days_until` | raw fields | clean numbers |
| Score (market) | `compute_flags`, `significance_score`, `compute_market_signals` | clean numbers | one enriched market record |
| Aggregate (event) | `enrich_event` | raw event + its markets | one enriched event record (with `event_significance`) |
| De-noise | `passes_denoise` | enriched event | keep / drop boolean |
| Rank | `rank_and_cap` | kept events | ordered, capped list |
| Emit | `polymarket_reader.main` | ranked list | `output_polymarket_reader.json` |

The reader runs each tag in the configured buckets, **deduplicates** events that appear under more
than one tag (unioning their `buckets`/`tags`), enriches every event once, then de-noises and ranks.

---

## 3. Stage 1 — What is fetched (the raw material)

`get_events_by_tag(slug)` calls
`GET https://gamma-api.polymarket.com/events?tag_slug=<slug>&active=true&closed=false&order=volume24hr&ascending=false&limit=<n>`.

An **event** is a question family (e.g. "Fed decision in July"); it contains one or more **markets**
(the individual Yes/No or multi-outcome bets). The engine reads these raw fields:

**Event-level**

| Raw field | Type | Used for |
|-----------|------|----------|
| `id` | string/int | dedup key, output `id` |
| `title` | string | display |
| `slug` | string | URL + watchlist matching |
| `endDate` | ISO-8601 string | horizon cut (assets) |
| `volume24hr` | number | volume floor + display |
| `tags` | list of `{slug,label}` dicts | **denylist** (`all_tags`) |
| `markets` | list of market dicts | per-market scoring |

**Market-level** (inside `event["markets"]`)

| Raw field | Type | Notes |
|-----------|------|-------|
| `question` | string | the actual bet |
| `outcomes` | list **or JSON string** | e.g. `["Yes","No"]` |
| `outcomePrices` | list **or JSON string** | e.g. `["0.2465","0.7535"]` — these are the implied probabilities |
| `oneDayPriceChange` | number (signed) | 1-day move of the leading price |
| `oneWeekPriceChange` | number (signed) | 1-week move |
| `volume24hr` | number | conviction |
| `volume` | number | total lifetime volume |
| `liquidity` | number | order-book depth |
| `endDate` | ISO-8601 | days-to-resolve |
| `clobTokenIds` | list **or JSON string** | only used by `polymarket_event.py --history` to fetch the odds curve from CLOB |

> **Gotcha #1:** Gamma frequently returns `outcomes`, `outcomePrices`, and `clobTokenIds` as
> **JSON-encoded strings** (`'["Yes","No"]'`) rather than real arrays. `coerce_list` transparently
> handles both. If parsing ever breaks after an API change, look here first.

---

## 4. Stage 2 — Parsing and normalization

These four pure helpers turn messy raw fields into clean numbers. All are defensive: malformed input
yields a safe default rather than an exception (per-item error isolation is a repo non-negotiable).

### `coerce_list(value) → list`
Accepts a real list (passthrough), a JSON-encoded string (parsed), or `None`/garbage (→ `[]`).

### `to_float(value, default=None) → float | default`
`float()` with a try/except. `to_float("0.735") == 0.735`; `to_float(None)` → `None`;
`to_float("nope", default=0.0) == 0.0`. The market-signal code calls it with `default=0.0` so a
missing price-change or volume becomes `0.0`, never an error.

### `implied_probability(outcomes, prices) → (max_price, label)`
Pairs each price with its outcome label, drops unparseable prices, and returns the **highest** price
and the outcome it belongs to. This is the "leading outcome" — the crowd's favorite.

```python
implied_probability(["Yes","No"], ["0.735","0.265"])  → (0.735, "Yes")
implied_probability([], [])                            → (0.0, "")
```

> **Gotcha #2 (binary vs. multi-outcome):** For a binary Yes/No market the leading price is **always
> ≥ 0.5** (the two prices sum to ~1). For a **multi-outcome** market (e.g. an election with 5
> candidates) the leading outcome can be **below 0.5** — e.g. prices `0.40 / 0.35 / 0.25` give
> `implied_prob = 0.40`. This matters for `extremeness` (see §5.2) and for reading the field.

### `days_until(end_date, now) → float | None`
Parses the ISO date (treating naive datetimes as UTC) and returns fractional days to resolution.
`None` for missing/unparseable dates. Used by the assets horizon cut.

```python
days_until("2026-06-29T00:00:00Z", datetime(2026,6,24,…))  → ~5.0
```

---

## 5. Stage 3 — Per-market signals

`compute_market_signals(market, now)` is the heart of the engine. It produces one enriched record
per market. Two outputs matter: the **flags** (binary, human-readable) and the **significance_score**
(continuous, used for ranking).

First it derives the clean inputs:

```python
prob, label  = implied_probability(outcomes, prices)   # leading prob + its label
extremeness  = abs(prob - 0.5) / 0.5                    # 0 = tossup, 1 = certainty
move_1d      = abs(to_float(oneDayPriceChange, 0.0))    # magnitude only
move_1w      = abs(to_float(oneWeekPriceChange, 0.0))   # magnitude only
vol24h       = to_float(volume24hr, 0.0)
```

> **Gotcha #3:** `move_1d`/`move_1w` are stored as **absolute values** — the engine cares that the
> market repriced *fast*, not which direction. The raw signed direction is not preserved in the
> output; if the agent needs direction it should pull the odds curve via `polymarket_event.py
> --history`.

### 5.1 Flags — `compute_flags(prob, move_1d, move_1w, vol24h, thresholds)`

Four independent booleans. They are descriptive labels, not a score; the agent reads them together.

| Flag | Exact condition | Default threshold | What it means |
|------|-----------------|-------------------|---------------|
| `extreme_consensus` | `prob >= extreme_p` | **0.85** | The crowd is near-certain. The interesting case is when this disagrees with media/your priors. |
| `big_move` | `move_1w >= move_1w_thr` **OR** `move_1d >= move_1d_thr` | **0.10** (1w) / **0.05** (1d) | The market repriced materially — new information arrived. The earliest signal type. |
| `high_conviction` | `vol24h >= conviction_vol` | **50,000** | Real money is flowing today; the price is trustworthy, not thin-market noise. |
| `high_stakes_tossup` | `tossup_lo <= prob <= tossup_hi` **AND** `high_conviction` | **0.40–0.60** + conviction | A genuinely uncertain, money-backed coin-flip — high informational value, watch for a break. |

Note `high_stakes_tossup` **requires** conviction — a 50/50 price on a market nobody is trading is
not interesting, so the volume gate is built into the flag itself.

### 5.2 Significance score — `significance_score(...)`

A single 0–1 number used for ranking. It is a **weighted sum of four normalized terms**, then clamped
to `[0,1]` and rounded to 4 decimals:

```python
conviction_norm = min(1.0, log10(max(vol24h, 1)) / log10(conviction_ref))   # conviction_ref = 10,000,000
momentum_norm   = min(1.0, abs(move_1w) / momentum_ref)                      # momentum_ref   = 0.25
extremeness_n   = max(0.0, min(1.0, extremeness))                            # already 0..1
tossup_term     = 1.0 if high_stakes_tossup else 0.0

score = w_conviction  * conviction_norm     # 0.35
      + w_extremeness * extremeness_n       # 0.25
      + w_momentum    * momentum_norm       # 0.30
      + w_tossup      * tossup_term         # 0.10
```

The four **weights sum to 1.0** (a unit test enforces this), so a market that maxed every dimension
would score exactly 1.0.

**Why these normalizations:**

- **Conviction is logarithmic.** Volume spans many orders of magnitude, so raw dollars would let one
  whale market dominate. `log10(vol)/log10(10M)` maps \$10k→0.57, \$1M→0.86, \$10M→1.0 (capped). A
  market needs ~\$10M/day to max the conviction term; anything past that is clipped.
- **Momentum is linear up to a reference move.** A 0.25 (25-point) weekly swing is treated as "as
  fast as it gets" → 1.0; a 0.10 move (the `big_move` line) is 0.40; anything ≥0.25 is clipped.
- **Extremeness is already 0–1** by construction (`abs(prob-0.5)/0.5`).
- **Tossup is a flat 0.10 bonus** — a small nudge so a conviction-backed coin-flip out-ranks an
  otherwise-identical sleepy market, without overwhelming the other signals.

#### Reference tables (so you can read a score by eye)

`conviction_norm = log10(vol)/7` (since `log10(10,000,000)=7`):

| vol24h | conviction_norm |
|--------|-----------------|
| 10,000 | 0.571 |
| 50,000 | 0.671 |
| 100,000 | 0.714 |
| 1,000,000 | 0.857 |
| 10,000,000+ | 1.000 (capped) |

`momentum_norm = |move_1w| / 0.25`:

| move_1w | momentum_norm |
|---------|---------------|
| 0.05 | 0.20 |
| 0.10 | 0.40 |
| 0.219 | 0.876 |
| 0.25+ | 1.000 (capped) |

`extremeness = |prob − 0.5| / 0.5`:

| implied_prob | extremeness |
|--------------|-------------|
| 0.50 | 0.00 |
| 0.60 | 0.20 |
| 0.75 | 0.50 |
| 0.85 | 0.70 |
| 0.97 | 0.94 |
| 1.00 | 1.00 |

### 5.3 Worked example A — a repricing Fed market

Raw market:

```json
{
  "outcomes": "[\"Yes\", \"No\"]",
  "outcomePrices": "[\"0.2465\", \"0.7535\"]",
  "oneDayPriceChange": 0.001,
  "oneWeekPriceChange": 0.219,
  "volume24hr": 1149937,
  "volume": 5000000,
  "endDate": "2026-07-29T00:00:00Z"
}
```

Parsed: `prob = 0.7535` (label `"No"`), `extremeness = |0.7535−0.5|/0.5 = 0.507`,
`move_1d = 0.001`, `move_1w = 0.219`, `vol24h = 1,149,937`.

Flags:
- `extreme_consensus` = `0.7535 ≥ 0.85` → **false**
- `big_move` = `0.219 ≥ 0.10` → **true**
- `high_conviction` = `1,149,937 ≥ 50,000` → **true**
- `high_stakes_tossup` = `0.40 ≤ 0.7535 ≤ 0.60`? → **false**

Score terms:
- `conviction_norm = log10(1,149,937)/7 = 6.0607/7 = 0.8658`
- `momentum_norm   = 0.219/0.25 = 0.876`
- `extremeness_n   = 0.507`
- `tossup_term     = 0`

```
score = 0.35*0.8658 + 0.25*0.507 + 0.30*0.876 + 0.10*0
      = 0.30303    + 0.12675    + 0.26280    + 0
      = 0.6926
```

**Read:** a conviction-backed market (≈\$1.15M/day) that moved 22 points in a week — a clear "new
information arrived" signal at a strong-but-not-certain 75% probability. Score **0.6926** would rank
it near the top of a macro feed.

### 5.4 Worked example B — extreme consensus, quiet

`prob = 0.97`, `move_1w = 0.01`, `move_1d = 0`, `vol24h = 200,000`, not a tossup.

- Flags: `extreme_consensus` true, `big_move` false, `high_conviction` true, `tossup` false.
- `conviction_norm = log10(200,000)/7 = 5.301/7 = 0.757`; `momentum_norm = 0.01/0.25 = 0.04`;
  `extremeness = |0.97−0.5|/0.5 = 0.94`.
- `score = 0.35*0.757 + 0.25*0.94 + 0.30*0.04 + 0 = 0.2651 + 0.2350 + 0.0120 = 0.5121`.

**Read:** the crowd is 97% sure and not changing its mind. Lower score than example A because nothing
is *moving* — but `extreme_consensus=true` is the flag to act on if the consensus contradicts your
view.

### 5.5 Worked example C — high-stakes coin-flip

`prob = 0.50`, `move_1w = 0`, `vol24h = 1,000,000`, `high_stakes_tossup = true`.

- `conviction_norm = log10(1,000,000)/7 = 6/7 = 0.857`; `extremeness = 0`; `momentum_norm = 0`;
  `tossup_term = 1.0`.
- `score = 0.35*0.857 + 0 + 0 + 0.10*1.0 = 0.300 + 0.100 = 0.4000`.

**Read:** a \$1M/day genuine 50/50. The 0.10 tossup bonus lifts it above an equivalent quiet,
lopsided-but-not-extreme market. Watch for the break in either direction.

---

## 6. Stage 4 — Event-level aggregation

`enrich_event(event, now, buckets, tags, ...)` scores every market in the event and rolls them up:

```python
markets          = [compute_market_signals(m, now) for m in event["markets"]]
event_significance = max(m["significance_score"] for m in markets)  # or 0.0 if no markets
native_tags      = sorted({t["slug"] for t in event["tags"]})       # → all_tags
```

Key design choices:

- **`event_significance` is the MAX over the event's markets**, not the average. Rationale: an event
  with one screaming signal among several sleepy sub-markets is still significant — the max surfaces
  it. (If you'd rather rank by the typical market, that's a code change, not a config knob.)
- **`all_tags`** captures the event's *own* Polymarket tags (deduped, sorted). This is what the
  denylist checks — distinct from `tags`, which are the *search slugs the reader used to find* the
  event.
- **`buckets`** records which macro category(ies) the event was found under (an event in both
  `monetary` and `elections` carries both, thanks to reader dedup).
- **`watchlisted`** is set when the event came from `watchlist.json`; it makes the event bypass every
  de-noise gate (§7).

The enriched event record is exactly what lands in the output `events[]` — see §9.

---

## 7. Stage 5 — The de-noise pipeline

`passes_denoise(event_rec, thresholds, min_score, exclude_tags)` returns keep/drop. Gates run **in
this order**; the first failing gate drops the event:

```
0. watchlisted?              → if true, KEEP immediately (bypass everything below)
1. exclude_tags ∩ all_tags?  → if non-empty intersection, DROP   (the macro-noise denylist)
2. volume_24h < min_volume?  → DROP                               (thin-market floor)
3. assets bucket & < min_horizon_days to resolve? → DROP          (short-dated crypto/commodity noise)
4. event_significance < min_score? → DROP                         (caller's significance floor)
   otherwise → KEEP
```

Detail on each gate:

1. **Tag denylist (`exclude_tags`).** Default
   `["pop-culture", "tweets-markets", "mentions-markets", "sports"]`. This is the gate that solved
   the real problem that surfaced in live testing: an "Elon Musk # of tweets" market (tagged
   `pop-culture`/`tweets-markets`) ranked **#1** by raw score before this gate existed — exactly the
   noise the skill is meant to drop. Recon confirmed genuine Fed/election/geopolitics events **never**
   carry these tags, so the cut has no false positives. Disable per-run with `--no-exclude`; tune the
   list via `config/categories.json`.
2. **Volume floor (`min_volume`, default 10,000).** A price set by ~no money is not information.
   Override per-run with `--min-volume`.
3. **Assets horizon cut (`min_horizon_days`, default 1.0).** Applies **only** to events in the
   `assets` bucket (`HORIZON_CUT_BUCKETS = {"assets"}`). A "BTC up or down in the next 5 minutes"
   market is macro noise; a same-day Fed market is not — so the cut is scoped to assets only.
4. **Min-score (`min_score`, default 0.0 = off).** The caller's hard significance floor; the reader
   sets it from `--min-score`.

> **Important — the search and event scripts do NOT de-noise.** `polymarket_search.py` and
> `polymarket_event.py` return everything (sorted by significance), because if you searched for a
> specific thing you want to see it even if it's low-volume or tagged "for fun." De-noise is a
> *reader*-only concern.

---

## 8. Stage 6 — Rank and cap

`rank_and_cap(event_recs, limit)`:

```python
pinned = [e for e in recs if e["watchlisted"]]          # kept in input order
rest   = sorted(others, key=event_significance, desc)   # highest score first
return pinned + rest[: max(0, limit - len(pinned))]      # watchlist first, then top scorers, capped
```

- **Watchlisted events are pinned to the top** regardless of score (you asked to always see them).
- Everything else is sorted **descending by `event_significance`**.
- The list is capped at `--limit` (default **40**). Watchlist entries count against the cap.

---

## 9. What the agent reads — output fields and how to interpret them

The reader writes `output_polymarket_reader.json`. Top level:

```json
{
  "timestamp": "2026-06-24T10:00:00+00:00",
  "params":  { "categories": [...], "min_score": 0.0, "min_volume": 10000, "limit": 40,
               "exclude_tags": ["pop-culture","tweets-markets","mentions-markets","sports"] },
  "buckets_scanned": ["monetary","elections","geopolitics","assets"],
  "counts":  { "events_scanned": 337, "events_kept": 40, "filtered_out": 297 },
  "events":  [ <enriched event>, ... ],   // ranked, capped
  "filtered_out": [],                       // populated only with --all
  "errors":  {}                             // per-tag / per-watchlist failures, isolated
}
```

`counts` is the at-a-glance health check: `events_scanned` is everything fetched+enriched,
`events_kept` is what survived de-noise and the cap, `filtered_out` is the difference (a big number
here is normal and *good* — it's the noise being removed).

### Enriched event record — field-by-field

| Field | Meaning | How the agent should read it |
|-------|---------|------------------------------|
| `id` / `slug` / `url` | Polymarket identifiers | feed `slug`/`url` into `polymarket_event.py` to drill down |
| `title` | event question family | headline |
| `end_date` | resolution date | how soon the question settles |
| `buckets` | macro category(ies) found under | which theme (monetary/elections/geopolitics/assets) |
| `tags` | search slugs used to fetch it | provenance; usually ignore |
| `all_tags` | the event's own Polymarket tags | **why it was/wasn't denylisted**; inspect when debugging the filter |
| `volume_24h` | event 24h volume | money flowing today |
| `watchlisted` | from `watchlist.json`? | if true it bypassed all gates and is pinned |
| `event_significance` | **max** market significance (0–1) | the rank key; see bands below |
| `markets[]` | per-market signal records | the detail |

### Per-market record — field-by-field

| Field | Meaning | Investment read |
|-------|---------|-----------------|
| `question` | the specific bet | what is being priced |
| `consensus_outcome` | label of the leading price | what the crowd expects |
| `implied_prob` | leading outcome probability (0–1) | the crowd's money-weighted odds |
| `extremeness` | `\|prob−0.5\|/0.5` | 0 = pure tossup, 1 = certainty |
| `move_1d` / `move_1w` | **absolute** odds change | how fast it repriced (new info) |
| `volume_24h` | 24h volume | conviction / trustworthiness of the price |
| `volume_total` | lifetime volume | overall market size |
| `liquidity` | order-book depth | how much you could trade without moving it |
| `days_to_resolve` | days to settlement | event horizon |
| `flags` | the four booleans (§5.1) | the human-readable "why this is notable" |
| `significance_score` | the 0–1 composite | this market's standalone rank value |
| `price_history` | `[{t,p}]` curve | **only with `polymarket_event.py --history`**; gives direction/shape |

### Reading `significance_score` / `event_significance` by band

These are heuristics for the agent, not hard rules (the score is relative within a feed):

| Band | Typical interpretation |
|------|------------------------|
| **≥ 0.70** | Strong signal — high conviction and/or fast repricing and/or near-certainty. Lead with these. |
| **0.50–0.70** | Worth a look — one or two dimensions firing (e.g. consensus *or* a move). |
| **0.35–0.50** | Marginal — usually low volume or a quiet, middling price. Context-dependent. |
| **< 0.35** | Background — rarely actionable on its own. |

> Always cross-read the **flags** with the score. A 0.51 with `extreme_consensus=true` (example B)
> means "97% consensus, just quiet" — potentially very actionable if it contradicts your prior — even
> though the score is middling. The score ranks; the flags explain.

---

## 10. Every tunable variable in one place

All defaults live in `polymarket_common.py` (`DEFAULT_THRESHOLDS`, `DEFAULT_WEIGHTS`,
`DEFAULT_BUCKETS`, `HORIZON_CUT_BUCKETS`, `DEFAULT_EXCLUDE_TAGS`) and can be overridden by
`config/categories.json` (thresholds/weights are merged key-by-key; buckets/exclude_tags replace
wholesale). A few also have per-run CLI flags.

### Thresholds (`thresholds`)

| Key | Default | Controls | Raise it to… | Lower it to… |
|-----|---------|----------|--------------|--------------|
| `extreme_p` | 0.85 | `extreme_consensus` flag cutoff | demand stronger consensus | flag more markets as "consensus" |
| `move_1w` | 0.10 | `big_move` (weekly) | only flag bigger weekly swings | flag smaller moves |
| `move_1d` | 0.05 | `big_move` (daily) | only flag bigger daily swings | flag smaller moves |
| `conviction_vol` | 50,000 | `high_conviction` + tossup gate | require more daily money | accept thinner markets |
| `tossup_lo` / `tossup_hi` | 0.40 / 0.60 | `high_stakes_tossup` band | narrow the "coin-flip" window | widen it |
| `min_volume` | 10,000 | **de-noise volume floor** | drop more thin markets | keep more (CLI: `--min-volume`) |
| `min_horizon_days` | 1.0 | **assets horizon cut** | drop more short-dated asset markets | keep shorter-dated ones |
| `momentum_ref` | 0.25 | momentum normalization denominator | make momentum score harder to max | make moves count for more |
| `conviction_ref` | 10,000,000 | conviction normalization denominator | make volume score harder to max | make volume count for more |

> Note `momentum_ref` and `conviction_ref` only affect the **score** (ranking), while `move_1w`/
> `move_1d`/`conviction_vol` only affect the **flags** (labels). They are intentionally separate so
> you can tune "what gets labeled" independently of "what ranks high."

### Weights (`weights`) — must sum to ~1.0

| Key | Default | Effect of increasing |
|-----|---------|----------------------|
| `conviction` | 0.35 | favor high-volume markets in ranking |
| `extremeness` | 0.25 | favor lopsided (near-certain) markets |
| `momentum` | 0.30 | favor fast-repricing markets |
| `tossup` | 0.10 | reward conviction-backed coin-flips more |

### Category buckets (`buckets`) and `horizon_cut_buckets`

`buckets` maps a macro category name → the Polymarket tag slugs that define it. Defaults:

```
monetary    → economy, fed-rates, interest-rates, inflation, recession, gdp, macro-indicators
elections   → elections, politics, us-politics, federal-government
geopolitics → geopolitics, international-affairs, war, middle-east
assets      → commodities, crypto, bitcoin, ethereum, etf
```

`resolve_slugs` picks what to scan: `--tags` (raw slugs, label `custom`) overrides `--categories`
(named buckets) overrides "all buckets." `horizon_cut_buckets` (default `["assets"]`) is the set of
buckets the §7 horizon cut applies to.

### Denylist (`exclude_tags`)

Default `["pop-culture", "tweets-markets", "mentions-markets", "sports"]`. An event is dropped if
**any** of its `all_tags` is in this list (unless watchlisted or `--no-exclude`). Add tags to tighten.

---

## 11. End-to-end example: one event through the whole pipeline

Suppose the `monetary` scan fetches this event (abbreviated):

```json
{
  "id": "521043", "title": "Fed decision in July?", "slug": "fed-decision-in-july",
  "endDate": "2026-07-30T21:00:00Z", "volume24hr": 1149937,
  "tags": [{"slug":"economy"},{"slug":"fed-rates"},{"slug":"inflation"}],
  "markets": [
    { "question":"Will the Fed cut rates in July 2026?",
      "outcomes":"[\"Yes\",\"No\"]", "outcomePrices":"[\"0.2465\",\"0.7535\"]",
      "oneDayPriceChange":0.001, "oneWeekPriceChange":0.219,
      "volume24hr":1149937, "volume":5000000, "liquidity":180000,
      "endDate":"2026-07-30T21:00:00Z" }
  ]
}
```

1. **Enrich the market** (= worked example A): `implied_prob 0.7535`, `consensus_outcome "No"`,
   `extremeness 0.507`, `move_1w 0.219`, flags `big_move`+`high_conviction`, `significance_score
   0.6926`.
2. **Aggregate the event:** `event_significance = max([0.6926]) = 0.6926`;
   `all_tags = ["economy","fed-rates","inflation"]`.
3. **De-noise:** not watchlisted → check denylist: `{"economy","fed-rates","inflation"} ∩
   {"pop-culture","tweets-markets","mentions-markets","sports"} = ∅` → pass; `volume_24h 1.15M ≥
   10,000` → pass; not an `assets` event → horizon cut skipped; `0.6926 ≥ min_score 0.0` → pass →
   **KEEP**.
4. **Rank:** sorted by `0.6926` among its peers; lands high in `events[]`.
5. **Agent reads:** "Fed-cut-in-July market: crowd 75% on *No cut*, but it moved **+22pts in a week**
   on \$1.15M/day — a fast, conviction-backed repricing toward 'no cut.' Worth checking what news
   drove it" → then optionally `polymarket_event.py fed-decision-in-july --history` to see the curve
   and direction.

---

## 12. Edge cases and gotchas (consolidated)

- **JSON-string array fields** — `outcomes`/`outcomePrices`/`clobTokenIds` may be strings;
  `coerce_list` handles both. (Gotcha #1.)
- **Multi-outcome leading prob can be < 0.5** — `implied_prob` is the *max* price, not "Yes."
  (Gotcha #2.)
- **Moves are absolute** — direction is dropped from the score/output; use `--history` for direction.
  (Gotcha #3.)
- **`event_significance` is a MAX, not an average** — one hot sub-market lifts the whole event.
- **Empty markets** → `event_significance = 0.0` (won't rank, but a watchlisted empty event still
  passes de-noise).
- **Missing/garbage numbers** → coerced to `0.0`; missing dates → `days_to_resolve = None` and the
  horizon cut is skipped for that event.
- **Search/event scripts skip de-noise** — only the reader filters; the other two return everything.
- **Watchlist bypasses everything** — including the denylist and volume floor; a noisy slug you
  explicitly watchlist will appear and be pinned.
- **Per-item isolation** — a failing tag/watchlist fetch is recorded under `errors` and the run
  continues; it never aborts the whole scan (a fatal pre-result error exits `2`).

---

## 13. Quick tuning recipes

| Goal | Change |
|------|--------|
| Only the strongest signals in the feed | `--min-score 0.6` (or raise per-run) |
| Include "for fun" markets this once | `--no-exclude` |
| See what got filtered and why | `--all`, then inspect `filtered_out[].all_tags` |
| Tighten the noise filter permanently | add tags to `exclude_tags` in `config/categories.json` |
| Make ranking favor *moves* over *volume* | bump `weights.momentum`, drop `weights.conviction` (keep sum ≈ 1.0) |
| Treat smaller markets as tradable | lower `thresholds.min_volume` (CLI `--min-volume`) |
| Always surface a specific market | add its slug/url to `config/watchlist.json` |
| Add a new macro theme | add a bucket → tag-slug list in `config/categories.json` |

---

*Engine source: `polymarket_common.py`. Driver: `polymarket_reader.py`. Unit tests covering every
formula and gate above: `tests/test_polymarket_common.py` (`python3 tests/test_polymarket_common.py`).*
