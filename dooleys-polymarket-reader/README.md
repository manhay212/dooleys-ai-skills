# dooleys-polymarket-reader

Read **prediction-market signals** from [Polymarket](https://polymarket.com) via its public,
**keyless** Gamma + CLOB read APIs. Three functions:

- **`polymarket_reader.py`** — scan curated macro categories (Fed/rates, inflation, elections,
  geopolitics, commodities, crypto) and return a ranked, de-noised feed of the most significant
  markets.
- **`polymarket_search.py`** — ad-hoc keyword search: "what does the market say about X?"
- **`polymarket_event.py`** — deep-dive one event by URL, slug, or id; optionally attach the
  full odds time-series per market.

Output is event-grouped JSON with per-market signal flags, significance scores, and (optionally)
historical price curves. See `SKILL.md` for the full agent-facing contract including the signal
engine details, de-noise pipeline, and all flags.

## Why keyless?

Polymarket's Gamma event API and CLOB price-history endpoint are public and unauthenticated —
no API key, no OAuth, no browser session. The `POLYMARKET_API_KEY/SECRET/PASSPHRASE` entries in
the credentials template are reserved for a **future trading integration** and are **not read by
this skill**.

## Install

`requests` is the only runtime dependency and is available on the host system-wide. A virtual
environment is optional:

```bash
cd dooleys-polymarket-reader
python3 -m venv .venv && . .venv/bin/activate   # optional
pip install -r requirements.txt                  # only needed if requests is missing
```

No environment variables or credentials files are required.

## Configure (optional)

Config files are **optional** — sensible defaults are built into the code. Copy the examples only
if you want to customise categories, thresholds, or always-track events:

```bash
# Customise macro categories, signal thresholds, noise-exclusion tag list:
cp config/categories.example.json config/categories.json

# Add events you always want tracked (bypass all de-noise filters):
cp config/watchlist.example.json config/watchlist.json
```

## Use

```bash
# Scan all macro categories — top 40 significant events (de-noised, ranked)
python3 polymarket_reader.py
#   -> output_polymarket_reader.json

# Specific buckets or raw tags
python3 polymarket_reader.py --categories monetary,geopolitics
python3 polymarket_reader.py --tags fed-rates,bitcoin

# Include events that were filtered out (useful for debugging the de-noise pipeline)
python3 polymarket_reader.py --all

# Disable the macro-noise tag denylist (shows pop-culture / sports / tweet-count markets)
python3 polymarket_reader.py --no-exclude

# Ad-hoc keyword search
python3 polymarket_search.py "taiwan strait"
python3 polymarket_search.py --query "fed rate cut" --limit 10
#   -> output_polymarket_search.json

# Deep-dive one event by URL, slug, or id
python3 polymarket_event.py fed-decision-in-july
python3 polymarket_event.py "https://polymarket.com/event/fed-decision-in-july"
python3 polymarket_event.py 521043

# With odds history (default 1-week window, 180-minute fidelity)
python3 polymarket_event.py fed-decision-in-july --history
python3 polymarket_event.py fed-decision-in-july --history --interval 1m --fidelity 60
#   -> output_polymarket_event.json
```

Sample reader output (truncated):
```
Wrote .../output_polymarket_reader.json: 40 events kept (scanned 337, filtered 297).
```

Sample search output:
```
Wrote .../output_polymarket_search.json: 3 events for 'taiwan'.
```

Sample event output:
```
Wrote .../output_polymarket_event.json: 'Fed cuts rates in July?' (2 markets).
```

## Testing walkthrough

### 1. Unit tests (offline, fast — pure logic in `polymarket_common.py`)

```bash
python3 tests/test_polymarket_common.py    # built-in runner, no pytest needed
# or: python3 -m pytest tests/            # also works if pytest is installed
```

Expect `28/28 passed`. Covers: `coerce_list`, `to_float`, `implied_probability`, `days_until`,
`parse_event_ref`, `compute_flags`, `significance_score`, `compute_market_signals`, `enrich_event`,
`passes_denoise` (all gates + watchlist bypass), `rank_and_cap`, `load_config`, `resolve_slugs`,
`now_iso`.

### 2. Live smoke tests (hit the real public API)

**Reader:**
```bash
python3 polymarket_reader.py --limit 5
python3 -c "
import json; d = json.load(open('output_polymarket_reader.json'))
print('kept:', d['counts']['events_kept'], 'scanned:', d['counts']['events_scanned'])
print('first event:', d['events'][0]['title'])
print('exclude_tags in params:', d['params']['exclude_tags'])
print('all_tags on first:', d['events'][0]['all_tags'])
"
```
Expect: several events kept, `exclude_tags` present in params (confirming de-noise is active),
and `all_tags` populated on each event.

**Search:**
```bash
python3 polymarket_search.py "federal reserve" --limit 5
python3 -c "import json; d=json.load(open('output_polymarket_search.json')); print(d['query'], d['count'], 'events')"
```
Expect: query echoed, count > 0.

**Event (use a slug from reader output):**
```bash
# Grab a slug from the reader output:
SLUG=$(python3 -c "import json; print(json.load(open('output_polymarket_reader.json'))['events'][0]['slug'])")
python3 polymarket_event.py "$SLUG" --history
python3 -c "
import json; d = json.load(open('output_polymarket_event.json'))
e = d['event']
print('title:', e['title'], '| markets:', len(e['markets']))
print('description present:', bool(e.get('description')))
print('history points on market 0:', len(e['markets'][0].get('price_history', [])))
"
```
Expect: title printed, description present, history points > 0.

### 3. Failure paths

```bash
# Missing query → exit 1
python3 polymarket_search.py; echo "exit=$?"
# Expected: "No query provided." and exit=1

# Bad event ref → exit 1
python3 polymarket_event.py "this-slug-does-not-exist-xyz"; echo "exit=$?"
# Expected: "Event not found ..." and exit=1

# Bad categories → exit 1
python3 polymarket_reader.py --categories "nonexistent_bucket"; echo "exit=$?"
# Expected: "No categories/tags resolved." and exit=1
```

### 4. Keyless check

Confirm no credentials are read or required:
```bash
python3 -c "
import os
for k in ('POLYMARKET_API_KEY','POLYMARKET_SECRET','POLYMARKET_PASSPHRASE'):
    print(k, '=', os.environ.get(k, '(not set)'))
"
# Then run the reader anyway — it works regardless:
python3 polymarket_reader.py --limit 2
```
Expect: all keys are `(not set)` and the reader still succeeds.

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | Agent-facing instructions + output contract + signal engine reference |
| `polymarket_reader.py` | Entry point: scan macro categories → ranked de-noised feed |
| `polymarket_search.py` | Entry point: ad-hoc keyword search |
| `polymarket_event.py` | Entry point: deep-dive one event; optional odds history |
| `polymarket_client.py` | HTTP transport (Gamma + CLOB read APIs; the only networked module) |
| `polymarket_common.py` | Pure, unit-tested logic (parsing, signals, scoring, de-noise, ranking) |
| `tests/test_polymarket_common.py` | Offline unit tests (28 tests; built-in runner) |
| `config/categories.example.json` | Template: buckets, thresholds, weights, exclude_tags |
| `config/watchlist.example.json` | Template: always-track events list |
| `requirements.txt` | `requests` (only runtime dependency) |

Generated `output_*.json` and the real `config/categories.json` / `config/watchlist.json` are
git-ignored.
