# dooleys-polymarket-reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a keyless, read-only Polymarket reader skill that surfaces macro/investment-relevant prediction-market signals (extreme consensus, fast repricing, conviction volume, high-stakes toss-ups) as a ranked, de-noised JSON feed.

**Architecture:** Thin HTTP transport (`polymarket_client.py`, Gamma + CLOB-read, no auth) + pure signal/scoring logic (`polymarket_common.py`, unit-tested) + three focused entry scripts (`polymarket_reader.py` scan, `polymarket_search.py` ad-hoc, `polymarket_event.py` drill-down). Mirrors the existing `dooleys-substack-reader` split.

**Tech Stack:** Python 3.8+ (host 3.12), `requests`, `pytest`. No SDK, no auth.

## Global Constraints

- **Keyless.** No `config/credentials.json`; no required env vars. `POLYMARKET_*` keys are unused by the reader (documented as trading/v2-only).
- **Conventions (repo CLAUDE.md):** `SKILL.md`/`README.md` at skill root; self-contained (no cross-skill imports); JSON output to `output_{function}.json` with top-level `timestamp`; per-item error isolation (one bad tag/market → record under `errors`, keep going).
- **Never commit secrets/output/config:** `.gitignore` excludes `config/*.json` (ship `*.example`), `output_*.json`, `__pycache__/`.
- **Staging:** stage explicit paths only (`git add dooleys-polymarket-reader/ ...`), never `git add -A`; do not touch other skills' folders.
- **Skill folder:** `dooleys-polymarket-reader/` at repo root `/home/dooleys/.hermes/custom-skills/`.
- **Default thresholds (tunable):** extreme_p 0.85, move_1w 0.10, move_1d 0.05, conviction_vol 50_000, tossup 0.40–0.60, min_volume 10_000, min_horizon_days 1.0, momentum_ref 0.25, conviction_ref 10_000_000.
- **Default score weights (sum 1.0):** conviction 0.35, extremeness 0.25, momentum 0.30, tossup 0.10.
- **Default buckets → tag slugs:**
  - `monetary`: economy, fed-rates, interest-rates, inflation, recession, gdp, macro-indicators
  - `elections`: elections, politics, us-politics, federal-government
  - `geopolitics`: geopolitics, international-affairs, war, middle-east
  - `assets`: commodities, crypto, bitcoin, ethereum, etf
- **Horizon-cut buckets:** `{assets}` only.
- **Verified endpoints:** `GET gamma/events?tag_slug=&closed=false&active=true&order=volume24hr&ascending=false&limit=`; `GET gamma/events?slug=`; `GET gamma/events/{id}`; `GET gamma/public-search?q=&limit_per_type=`; `GET clob/prices-history?market=&interval=&fidelity=`.

---

## File Structure

```
dooleys-polymarket-reader/
  SKILL.md  README.md  requirements.txt  .gitignore
  config/
    categories.example.json   watchlist.example.json
  polymarket_client.py        # Task 6
  polymarket_common.py        # Tasks 2-5 (pure, tested)
  polymarket_reader.py        # Task 7
  polymarket_search.py        # Task 8
  polymarket_event.py         # Task 9
  tests/test_polymarket_common.py   # Tasks 2-5
```

---

## Task 1: Scaffold + config + git hygiene

**Files:**
- Create: `dooleys-polymarket-reader/requirements.txt`
- Create: `dooleys-polymarket-reader/.gitignore`
- Create: `dooleys-polymarket-reader/config/categories.example.json`
- Create: `dooleys-polymarket-reader/config/watchlist.example.json`
- Create: `dooleys-polymarket-reader/tests/__init__.py` (empty)
- Modify: repo-root `.gitignore` (create if absent) to exclude `tmp.env`

**Interfaces:**
- Produces: the skill directory skeleton + the `categories.json` schema consumed by Task 5/7.

- [ ] **Step 1: Create the skill folder and files**

`dooleys-polymarket-reader/requirements.txt`:
```
requests>=2.28
pytest>=7.0
```

`dooleys-polymarket-reader/.gitignore`:
```
config/*.json
!config/*.example.json
output_*.json
__pycache__/
*.pyc
.pytest_cache/
```

`dooleys-polymarket-reader/config/categories.example.json`:
```json
{
  "buckets": {
    "monetary": ["economy", "fed-rates", "interest-rates", "inflation", "recession", "gdp", "macro-indicators"],
    "elections": ["elections", "politics", "us-politics", "federal-government"],
    "geopolitics": ["geopolitics", "international-affairs", "war", "middle-east"],
    "assets": ["commodities", "crypto", "bitcoin", "ethereum", "etf"]
  },
  "horizon_cut_buckets": ["assets"],
  "thresholds": {
    "extreme_p": 0.85, "move_1w": 0.10, "move_1d": 0.05,
    "conviction_vol": 50000, "tossup_lo": 0.40, "tossup_hi": 0.60,
    "min_volume": 10000, "min_horizon_days": 1.0,
    "momentum_ref": 0.25, "conviction_ref": 10000000
  },
  "weights": { "conviction": 0.35, "extremeness": 0.25, "momentum": 0.30, "tossup": 0.10 }
}
```

`dooleys-polymarket-reader/config/watchlist.example.json`:
```json
{
  "events": [
    "fed-decision-in-july",
    "https://polymarket.com/event/how-many-fed-rate-cuts-in-2026"
  ]
}
```

`dooleys-polymarket-reader/tests/__init__.py`: (empty file)

- [ ] **Step 2: Stop tracking `tmp.env` and ignore it**

Run:
```bash
cd /home/dooleys/.hermes/custom-skills
grep -qxF 'tmp.env' .gitignore 2>/dev/null || printf 'tmp.env\n' >> .gitignore
git rm --cached tmp.env
```
Expected: `rm 'tmp.env'` (file stays on disk, leaves git tracking). If `.gitignore` did not exist it is created with the single line.

- [ ] **Step 3: Verify tree + that tmp.env is no longer staged**

Run:
```bash
cd /home/dooleys/.hermes/custom-skills
ls dooleys-polymarket-reader dooleys-polymarket-reader/config
git status --short | grep -E 'tmp.env|polymarket'
```
Expected: the four config/req/gitignore files listed; `tmp.env` shows as `D` (deleted from index) + untracked, NOT modified-tracked.

- [ ] **Step 4: Commit**

```bash
cd /home/dooleys/.hermes/custom-skills
git add dooleys-polymarket-reader/.gitignore dooleys-polymarket-reader/requirements.txt dooleys-polymarket-reader/config dooleys-polymarket-reader/tests/__init__.py .gitignore
git rm --cached tmp.env 2>/dev/null; git add .gitignore
git commit -m "feat(polymarket): scaffold skill (config, gitignore, untrack tmp.env)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `polymarket_common.py` — coercion & parsing helpers (TDD)

**Files:**
- Create: `dooleys-polymarket-reader/polymarket_common.py`
- Test: `dooleys-polymarket-reader/tests/test_polymarket_common.py`

**Interfaces:**
- Produces:
  - `coerce_list(value) -> list` — JSON-string-or-list → list.
  - `to_float(value, default=None) -> float | None`
  - `implied_probability(outcomes: list, prices: list) -> tuple[float, str]` — (max prob, its outcome label); `(0.0, "")` if empty.
  - `days_until(end_date: str | None, now: datetime) -> float | None`
  - `parse_event_ref(s: str) -> dict` — `{"kind": "slug"|"id", "value": str}`.
  - `DEFAULT_THRESHOLDS: dict`, `DEFAULT_WEIGHTS: dict`, `DEFAULT_BUCKETS: dict`, `HORIZON_CUT_BUCKETS: set`.

- [ ] **Step 1: Write failing tests**

`dooleys-polymarket-reader/tests/test_polymarket_common.py`:
```python
from datetime import datetime, timezone
import polymarket_common as c


def test_coerce_list_from_json_string():
    assert c.coerce_list('["Yes", "No"]') == ["Yes", "No"]

def test_coerce_list_passthrough_list():
    assert c.coerce_list(["a", "b"]) == ["a", "b"]

def test_coerce_list_none_is_empty():
    assert c.coerce_list(None) == []

def test_to_float_handles_string_and_none():
    assert c.to_float("0.735") == 0.735
    assert c.to_float(None) is None
    assert c.to_float("nope", default=0.0) == 0.0

def test_implied_probability_picks_max():
    prob, label = c.implied_probability(["Yes", "No"], ["0.735", "0.265"])
    assert round(prob, 3) == 0.735 and label == "Yes"

def test_implied_probability_empty():
    assert c.implied_probability([], []) == (0.0, "")

def test_days_until():
    now = datetime(2026, 6, 24, tzinfo=timezone.utc)
    d = c.days_until("2026-06-29T00:00:00Z", now)
    assert 4.9 < d < 5.1
    assert c.days_until(None, now) is None

def test_parse_event_ref_url_slug_id():
    assert c.parse_event_ref("https://polymarket.com/event/fed-decision-in-july") == {"kind": "slug", "value": "fed-decision-in-july"}
    assert c.parse_event_ref("https://polymarket.com/market/some-slug-123") == {"kind": "slug", "value": "some-slug-123"}
    assert c.parse_event_ref("fed-decision-in-july") == {"kind": "slug", "value": "fed-decision-in-july"}
    assert c.parse_event_ref("30615") == {"kind": "id", "value": "30615"}

def test_default_constants_present():
    assert c.DEFAULT_THRESHOLDS["extreme_p"] == 0.85
    assert abs(sum(c.DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9
    assert "assets" in c.HORIZON_CUT_BUCKETS
    assert "fed-rates" in c.DEFAULT_BUCKETS["monetary"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd dooleys-polymarket-reader && python -m pytest tests/test_polymarket_common.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'polymarket_common'`.

- [ ] **Step 3: Write minimal implementation**

`dooleys-polymarket-reader/polymarket_common.py`:
```python
"""Pure logic for the Polymarket reader: parsing, signal computation, scoring,
de-noise, ranking. No network, no I/O — fully unit-testable."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone

DEFAULT_THRESHOLDS = {
    "extreme_p": 0.85, "move_1w": 0.10, "move_1d": 0.05,
    "conviction_vol": 50_000, "tossup_lo": 0.40, "tossup_hi": 0.60,
    "min_volume": 10_000, "min_horizon_days": 1.0,
    "momentum_ref": 0.25, "conviction_ref": 10_000_000,
}
DEFAULT_WEIGHTS = {"conviction": 0.35, "extremeness": 0.25, "momentum": 0.30, "tossup": 0.10}
DEFAULT_BUCKETS = {
    "monetary": ["economy", "fed-rates", "interest-rates", "inflation", "recession", "gdp", "macro-indicators"],
    "elections": ["elections", "politics", "us-politics", "federal-government"],
    "geopolitics": ["geopolitics", "international-affairs", "war", "middle-east"],
    "assets": ["commodities", "crypto", "bitcoin", "ethereum", "etf"],
}
HORIZON_CUT_BUCKETS = {"assets"}

_SLUG_URL_RE = re.compile(r"polymarket\.com/(?:event|market)/([^/?#]+)")


def coerce_list(value) -> list:
    """Gamma sometimes returns array fields (outcomePrices, clobTokenIds) as JSON strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


def to_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def implied_probability(outcomes: list, prices: list):
    """Return (max_price, outcome_label_at_that_price). ('' ,0.0) if empty/unparseable."""
    fps = [to_float(p) for p in prices]
    pairs = [(p, outcomes[i] if i < len(outcomes) else "")
             for i, p in enumerate(fps) if p is not None]
    if not pairs:
        return (0.0, "")
    prob, label = max(pairs, key=lambda x: x[0])
    return (prob, label)


def days_until(end_date, now: datetime):
    if not end_date:
        return None
    try:
        dt = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - now).total_seconds() / 86400.0


def parse_event_ref(s: str) -> dict:
    s = (s or "").strip()
    m = _SLUG_URL_RE.search(s)
    if m:
        return {"kind": "slug", "value": m.group(1)}
    if s.isdigit():
        return {"kind": "id", "value": s}
    return {"kind": "slug", "value": s}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd dooleys-polymarket-reader && python -m pytest tests/test_polymarket_common.py -q`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/dooleys/.hermes/custom-skills
git add dooleys-polymarket-reader/polymarket_common.py dooleys-polymarket-reader/tests/test_polymarket_common.py
git commit -m "feat(polymarket): common parsing/coercion helpers + constants (TDD)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `polymarket_common.py` — per-market signals & score (TDD)

**Files:**
- Modify: `dooleys-polymarket-reader/polymarket_common.py`
- Test: `dooleys-polymarket-reader/tests/test_polymarket_common.py`

**Interfaces:**
- Consumes: `coerce_list`, `to_float`, `implied_probability`, `days_until`, `DEFAULT_THRESHOLDS`, `DEFAULT_WEIGHTS`.
- Produces:
  - `compute_flags(prob, move_1d, move_1w, vol24h, thresholds) -> dict` keys: `extreme_consensus, big_move, high_conviction, high_stakes_tossup` (bools).
  - `significance_score(extremeness, move_1w, vol24h, is_tossup, weights, thresholds) -> float` in [0,1].
  - `compute_market_signals(market: dict, now, thresholds=DEFAULT_THRESHOLDS, weights=DEFAULT_WEIGHTS) -> dict` — enriched market record with keys: `question, consensus_outcome, implied_prob, extremeness, move_1d, move_1w, volume_24h, volume_total, liquidity, days_to_resolve, flags, significance_score`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_polymarket_common.py`:
```python
NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)

FED_MARKET = {
    "question": "Will the Fed increase interest rates by 25 bps after the July 2026 meeting?",
    "outcomes": '["Yes", "No"]', "outcomePrices": '["0.2465", "0.7535"]',
    "oneDayPriceChange": 0.001, "oneWeekPriceChange": 0.219,
    "volume24hr": 1149937.0, "volume": 5_000_000.0, "liquidity": 200000.0,
    "endDate": "2026-07-29T00:00:00Z",
}

def test_flags_big_move_and_conviction():
    f = c.compute_flags(0.7535, 0.001, 0.219, 1149937.0, c.DEFAULT_THRESHOLDS)
    assert f["big_move"] is True            # 1w 0.219 >= 0.10
    assert f["high_conviction"] is True     # vol >= 50k
    assert f["extreme_consensus"] is False  # 0.7535 < 0.85
    assert f["high_stakes_tossup"] is False

def test_flags_extreme_consensus():
    f = c.compute_flags(0.97, 0.0, 0.01, 200000.0, c.DEFAULT_THRESHOLDS)
    assert f["extreme_consensus"] is True

def test_flags_tossup_requires_conviction():
    assert c.compute_flags(0.50, 0.0, 0.0, 1_000_000, c.DEFAULT_THRESHOLDS)["high_stakes_tossup"] is True
    assert c.compute_flags(0.50, 0.0, 0.0, 100, c.DEFAULT_THRESHOLDS)["high_stakes_tossup"] is False

def test_significance_score_in_range_and_momentum_helps():
    low = c.significance_score(0.4, 0.0, 50_000, False, c.DEFAULT_WEIGHTS, c.DEFAULT_THRESHOLDS)
    high = c.significance_score(0.4, 0.25, 50_000, False, c.DEFAULT_WEIGHTS, c.DEFAULT_THRESHOLDS)
    assert 0.0 <= low <= 1.0 and 0.0 <= high <= 1.0
    assert high > low  # more momentum => higher score

def test_compute_market_signals_full():
    rec = c.compute_market_signals(FED_MARKET, NOW)
    assert rec["consensus_outcome"] == "No"
    assert round(rec["implied_prob"], 4) == 0.7535
    assert rec["move_1w"] == 0.219
    assert rec["flags"]["big_move"] is True
    assert 30 < rec["days_to_resolve"] < 40
    assert 0.0 <= rec["significance_score"] <= 1.0

def test_compute_market_signals_none_price_change_safe():
    m = dict(FED_MARKET, oneDayPriceChange=None, oneWeekPriceChange=None)
    rec = c.compute_market_signals(m, NOW)
    assert rec["move_1d"] == 0.0 and rec["move_1w"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd dooleys-polymarket-reader && python -m pytest tests/test_polymarket_common.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'compute_flags'`.

- [ ] **Step 3: Write minimal implementation**

Append to `polymarket_common.py`:
```python
def compute_flags(prob, move_1d, move_1w, vol24h, thresholds) -> dict:
    t = thresholds
    high_conviction = (vol24h or 0) >= t["conviction_vol"]
    return {
        "extreme_consensus": prob >= t["extreme_p"],
        "big_move": (move_1w >= t["move_1w"]) or (move_1d >= t["move_1d"]),
        "high_conviction": high_conviction,
        "high_stakes_tossup": (t["tossup_lo"] <= prob <= t["tossup_hi"]) and high_conviction,
    }


def significance_score(extremeness, move_1w, vol24h, is_tossup, weights, thresholds) -> float:
    t = thresholds
    conviction_norm = min(1.0, math.log10(max(vol24h or 0, 1)) / math.log10(t["conviction_ref"]))
    momentum_norm = min(1.0, (move_1w or 0) / t["momentum_ref"])
    tossup_term = 1.0 if is_tossup else 0.0
    score = (weights["conviction"] * conviction_norm
             + weights["extremeness"] * max(0.0, min(1.0, extremeness))
             + weights["momentum"] * momentum_norm
             + weights["tossup"] * tossup_term)
    return round(min(1.0, max(0.0, score)), 4)


def compute_market_signals(market: dict, now, thresholds=DEFAULT_THRESHOLDS, weights=DEFAULT_WEIGHTS) -> dict:
    outcomes = coerce_list(market.get("outcomes"))
    prices = coerce_list(market.get("outcomePrices"))
    prob, label = implied_probability(outcomes, prices)
    extremeness = abs(prob - 0.5) / 0.5
    move_1d = abs(to_float(market.get("oneDayPriceChange"), 0.0))
    move_1w = abs(to_float(market.get("oneWeekPriceChange"), 0.0))
    vol24h = to_float(market.get("volume24hr"), 0.0) or 0.0
    flags = compute_flags(prob, move_1d, move_1w, vol24h, thresholds)
    return {
        "question": market.get("question"),
        "consensus_outcome": label,
        "implied_prob": round(prob, 4),
        "extremeness": round(extremeness, 4),
        "move_1d": round(move_1d, 4),
        "move_1w": round(move_1w, 4),
        "volume_24h": vol24h,
        "volume_total": to_float(market.get("volume"), 0.0) or 0.0,
        "liquidity": to_float(market.get("liquidity"), 0.0) or 0.0,
        "days_to_resolve": (lambda d: round(d, 2) if d is not None else None)(days_until(market.get("endDate"), now)),
        "flags": flags,
        "significance_score": significance_score(extremeness, move_1w, vol24h, flags["high_stakes_tossup"], weights, thresholds),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd dooleys-polymarket-reader && python -m pytest tests/test_polymarket_common.py -q`
Expected: PASS (all prior + 6 new).

- [ ] **Step 5: Commit**

```bash
cd /home/dooleys/.hermes/custom-skills
git add dooleys-polymarket-reader/polymarket_common.py dooleys-polymarket-reader/tests/test_polymarket_common.py
git commit -m "feat(polymarket): per-market signal flags + significance score (TDD)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `polymarket_common.py` — event enrichment, de-noise, ranking (TDD)

**Files:**
- Modify: `dooleys-polymarket-reader/polymarket_common.py`
- Test: `dooleys-polymarket-reader/tests/test_polymarket_common.py`

**Interfaces:**
- Consumes: `compute_market_signals`, `days_until`, `to_float`, `HORIZON_CUT_BUCKETS`.
- Produces:
  - `enrich_event(event, now, buckets, tags, thresholds=DEFAULT_THRESHOLDS, weights=DEFAULT_WEIGHTS, watchlisted=False) -> dict` — record with keys: `id, title, slug, url, end_date, buckets, tags, volume_24h, watchlisted, event_significance, markets`.
  - `passes_denoise(event_rec, thresholds=DEFAULT_THRESHOLDS, min_score=0.0) -> bool`.
  - `rank_and_cap(event_recs: list, limit: int) -> list` — sorted by `event_significance` desc, watchlisted pinned first, capped to `limit` (watchlisted never dropped).
  - `event_url(slug) -> str`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_polymarket_common.py`:
```python
def _event(id=1, vol=500000, end="2026-08-01T00:00:00Z", buckets=("monetary",),
           pw="0.50", change=0.20):
    return {
        "id": str(id),
        "title": "Sample", "slug": "sample-%s" % id, "endDate": end,
        "volume24hr": vol,
        "markets": [{
            "question": "Q?", "outcomes": '["Yes","No"]',
            "outcomePrices": '["%s","%s"]' % (pw, round(1 - float(pw), 4)),
            "oneDayPriceChange": 0.0, "oneWeekPriceChange": change,
            "volume24hr": vol, "volume": vol * 3, "liquidity": 1000.0,
            "endDate": end,
        }],
    }, buckets

def test_enrich_event_shape_and_significance():
    ev, buckets = _event()
    rec = c.enrich_event(ev, NOW, list(buckets), ["fed-rates"])
    assert rec["slug"] == "sample-1"
    assert rec["url"] == "https://polymarket.com/event/sample-1"
    assert rec["buckets"] == ["monetary"] and rec["tags"] == ["fed-rates"]
    assert rec["event_significance"] == rec["markets"][0]["significance_score"]
    assert rec["watchlisted"] is False

def test_passes_denoise_volume_floor():
    ev, b = _event(vol=5000)  # below 10k floor
    rec = c.enrich_event(ev, NOW, list(b), [])
    assert c.passes_denoise(rec) is False

def test_passes_denoise_assets_horizon_cut():
    ev, _ = _event(end="2026-06-24T06:00:00Z", buckets=("assets",))  # ~0.25 days
    rec = c.enrich_event(ev, NOW, ["assets"], ["crypto"])
    assert c.passes_denoise(rec) is False           # assets + <1 day => cut
    ev2, _ = _event(end="2026-06-24T06:00:00Z", buckets=("monetary",))
    rec2 = c.enrich_event(ev2, NOW, ["monetary"], ["fed-rates"])
    assert c.passes_denoise(rec2) is True           # monetary same-day => kept

def test_passes_denoise_min_score():
    ev, b = _event(vol=500000)
    rec = c.enrich_event(ev, NOW, list(b), [])
    assert c.passes_denoise(rec, min_score=0.99) is False

def test_rank_and_cap_pins_watchlist_and_caps():
    a = c.enrich_event(_event(id=1, vol=20000, change=0.0)[0], NOW, ["monetary"], [])
    b = c.enrich_event(_event(id=2, vol=9_000_000, change=0.25)[0], NOW, ["monetary"], [])
    w = c.enrich_event(_event(id=3, vol=11000, change=0.0)[0], NOW, ["monetary"], [], watchlisted=True)
    ranked = c.rank_and_cap([a, b, w], limit=2)
    assert ranked[0]["watchlisted"] is True          # pinned first
    assert ranked[1]["id"] == "2"                     # then highest score
    assert len(ranked) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd dooleys-polymarket-reader && python -m pytest tests/test_polymarket_common.py -q`
Expected: FAIL — `AttributeError: ... 'enrich_event'`.

- [ ] **Step 3: Write minimal implementation**

Append to `polymarket_common.py`:
```python
def event_url(slug) -> str:
    return f"https://polymarket.com/event/{slug}" if slug else ""


def enrich_event(event, now, buckets, tags, thresholds=DEFAULT_THRESHOLDS,
                 weights=DEFAULT_WEIGHTS, watchlisted=False) -> dict:
    markets = [compute_market_signals(m, now, thresholds, weights)
               for m in (event.get("markets") or [])]
    event_sig = max((m["significance_score"] for m in markets), default=0.0)
    return {
        "id": str(event.get("id", "")),
        "title": event.get("title"),
        "slug": event.get("slug"),
        "url": event_url(event.get("slug")),
        "end_date": event.get("endDate"),
        "buckets": list(buckets),
        "tags": list(tags),
        "volume_24h": to_float(event.get("volume24hr"), 0.0) or 0.0,
        "watchlisted": watchlisted,
        "event_significance": event_sig,
        "markets": markets,
    }


def passes_denoise(event_rec, thresholds=DEFAULT_THRESHOLDS, min_score=0.0) -> bool:
    t = thresholds
    if event_rec.get("watchlisted"):
        return True
    if (event_rec.get("volume_24h") or 0) < t["min_volume"]:
        return False
    if HORIZON_CUT_BUCKETS & set(event_rec.get("buckets", [])):
        days = days_until(event_rec.get("end_date"), datetime.now(timezone.utc))
        if days is not None and days < t["min_horizon_days"]:
            return False
    if event_rec.get("event_significance", 0.0) < min_score:
        return False
    return True


def rank_and_cap(event_recs: list, limit: int) -> list:
    pinned = [e for e in event_recs if e.get("watchlisted")]
    rest = [e for e in event_recs if not e.get("watchlisted")]
    rest.sort(key=lambda e: e.get("event_significance", 0.0), reverse=True)
    return pinned + rest[: max(0, limit - len(pinned))]
```

Note: `passes_denoise` re-derives `days` from `now()` for the horizon check; tests use near-now fixtures so this is stable. The reader passes the already-computed `days_to_resolve` window indirectly via `end_date`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd dooleys-polymarket-reader && python -m pytest tests/test_polymarket_common.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
cd /home/dooleys/.hermes/custom-skills
git add dooleys-polymarket-reader/polymarket_common.py dooleys-polymarket-reader/tests/test_polymarket_common.py
git commit -m "feat(polymarket): event enrichment, de-noise, ranking (TDD)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `polymarket_common.py` — config loading & output assembly (TDD)

**Files:**
- Modify: `dooleys-polymarket-reader/polymarket_common.py`
- Test: `dooleys-polymarket-reader/tests/test_polymarket_common.py`

**Interfaces:**
- Produces:
  - `load_config(path: str | None) -> dict` — returns `{"buckets","horizon_cut_buckets","thresholds","weights"}` merged over defaults; missing file → all defaults.
  - `resolve_slugs(config, categories: list | None, tags: list | None) -> dict[str, list]` — bucket→slugs map to scan. `tags` (raw) → `{"custom": tags}`; `categories` → those buckets; else all config buckets.
  - `now_iso() -> str` (UTC ISO8601, `+00:00`).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_polymarket_common.py`:
```python
def test_load_config_defaults_when_missing(tmp_path):
    cfg = c.load_config(str(tmp_path / "nope.json"))
    assert cfg["thresholds"]["extreme_p"] == 0.85
    assert "monetary" in cfg["buckets"]

def test_load_config_overrides(tmp_path):
    p = tmp_path / "categories.json"
    p.write_text('{"thresholds": {"min_volume": 99}, "buckets": {"x": ["y"]}}')
    cfg = c.load_config(str(p))
    assert cfg["thresholds"]["min_volume"] == 99           # overridden
    assert cfg["thresholds"]["extreme_p"] == 0.85          # default preserved
    assert cfg["buckets"] == {"x": ["y"]}                  # buckets replaced wholesale

def test_resolve_slugs_modes():
    cfg = c.load_config(None)
    assert c.resolve_slugs(cfg, None, None).keys() == cfg["buckets"].keys()
    assert c.resolve_slugs(cfg, ["monetary"], None) == {"monetary": cfg["buckets"]["monetary"]}
    assert c.resolve_slugs(cfg, None, ["taiwan", "war"]) == {"custom": ["taiwan", "war"]}

def test_now_iso_is_utc():
    assert c.now_iso().endswith("+00:00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd dooleys-polymarket-reader && python -m pytest tests/test_polymarket_common.py -q`
Expected: FAIL — `AttributeError: ... 'load_config'`.

- [ ] **Step 3: Write minimal implementation**

Append to `polymarket_common.py`:
```python
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path) -> dict:
    cfg = {
        "buckets": {k: list(v) for k, v in DEFAULT_BUCKETS.items()},
        "horizon_cut_buckets": list(HORIZON_CUT_BUCKETS),
        "thresholds": dict(DEFAULT_THRESHOLDS),
        "weights": dict(DEFAULT_WEIGHTS),
    }
    if not path:
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as fh:
            user = json.load(fh)
    except (FileNotFoundError, ValueError):
        return cfg
    if isinstance(user.get("buckets"), dict):
        cfg["buckets"] = user["buckets"]
    if isinstance(user.get("horizon_cut_buckets"), list):
        cfg["horizon_cut_buckets"] = user["horizon_cut_buckets"]
    for key in ("thresholds", "weights"):
        if isinstance(user.get(key), dict):
            cfg[key] = {**cfg[key], **user[key]}
    return cfg


def resolve_slugs(config, categories, tags) -> dict:
    if tags:
        return {"custom": list(tags)}
    buckets = config["buckets"]
    if categories:
        return {b: buckets[b] for b in categories if b in buckets}
    return dict(buckets)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd dooleys-polymarket-reader && python -m pytest tests/test_polymarket_common.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
cd /home/dooleys/.hermes/custom-skills
git add dooleys-polymarket-reader/polymarket_common.py dooleys-polymarket-reader/tests/test_polymarket_common.py
git commit -m "feat(polymarket): config loading + slug resolution + now_iso (TDD)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `polymarket_client.py` — HTTP transport (Gamma + CLOB read)

**Files:**
- Create: `dooleys-polymarket-reader/polymarket_client.py`

**Interfaces:**
- Produces:
  - `class PolymarketError(RuntimeError)`
  - `class PolymarketClient` with:
    - `get_events_by_tag(tag_slug, limit=40, active=True, closed=False) -> list[dict]`
    - `search_events(query, limit=20) -> list[dict]`
    - `get_event_by_slug(slug) -> dict | None`
    - `get_event_by_id(event_id) -> dict | None`
    - `get_price_history(token_id, interval="1w", fidelity=180) -> list[dict]` (each `{"t","p"}`)

- [ ] **Step 1: Write the module**

`dooleys-polymarket-reader/polymarket_client.py`:
```python
"""Thin HTTP transport for Polymarket's public (keyless) read APIs.

Gamma API (events/markets/search): https://gamma-api.polymarket.com
CLOB read (price history):         https://clob.polymarket.com
No authentication is used or needed for reading. The POLYMARKET_* keys are for
the trading API only and are intentionally not referenced here.
"""
from __future__ import annotations

import time

import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class PolymarketError(RuntimeError):
    """Raised when a Polymarket endpoint cannot be reached or returns non-OK."""


class PolymarketClient:
    def __init__(self, user_agent=DEFAULT_UA, timeout=30.0, max_retries=3, backoff=1.5):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})

    def _get_json(self, url, params=None):
        last_err = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code != 429 and 400 <= resp.status_code < 500:
                    raise PolymarketError(f"GET {url} -> HTTP {resp.status_code}")
                last_err = PolymarketError(f"GET {url} -> HTTP {resp.status_code}")
            except (requests.RequestException, ValueError) as e:
                last_err = PolymarketError(f"GET {url} failed: {type(e).__name__}: {e}")
            if attempt < self.max_retries - 1:
                time.sleep(self.backoff * (attempt + 1))
        raise last_err or PolymarketError(f"GET {url} failed")

    def get_events_by_tag(self, tag_slug, limit=40, active=True, closed=False):
        params = {
            "tag_slug": tag_slug, "limit": limit,
            "active": str(active).lower(), "closed": str(closed).lower(),
            "order": "volume24hr", "ascending": "false",
        }
        data = self._get_json(f"{GAMMA}/events", params=params)
        return data if isinstance(data, list) else (data.get("data") or [])

    def search_events(self, query, limit=20):
        data = self._get_json(f"{GAMMA}/public-search",
                              params={"q": query, "limit_per_type": limit})
        if isinstance(data, dict):
            return data.get("events") or []
        return []

    def get_event_by_slug(self, slug):
        data = self._get_json(f"{GAMMA}/events", params={"slug": slug})
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict) and data.get("data"):
            return data["data"][0]
        return None

    def get_event_by_id(self, event_id):
        try:
            data = self._get_json(f"{GAMMA}/events/{event_id}")
        except PolymarketError:
            return None
        return data if isinstance(data, dict) and data else None

    def get_price_history(self, token_id, interval="1w", fidelity=180):
        data = self._get_json(f"{CLOB}/prices-history",
                              params={"market": token_id, "interval": interval, "fidelity": fidelity})
        if isinstance(data, dict):
            return data.get("history") or []
        return []
```

- [ ] **Step 2: Live smoke-test the client (network)**

Run:
```bash
cd dooleys-polymarket-reader && python -c "
from polymarket_client import PolymarketClient
cl = PolymarketClient()
evs = cl.get_events_by_tag('fed-rates', limit=3)
print('fed-rates events:', len(evs), '| first:', evs[0]['title'] if evs else None)
print('search taiwan:', len(cl.search_events('taiwan', limit=3)), 'events')
ev = cl.get_event_by_slug('fed-decision-in-july')
print('slug lookup:', ev['title'] if ev else None)
import json
tid = json.loads(ev['markets'][0]['clobTokenIds'])[0]
print('history points:', len(cl.get_price_history(tid, interval='1w', fidelity=180)))
"
```
Expected: non-zero events for fed-rates and taiwan, a slug title, and >0 history points. (If Polymarket renamed the demo slug, any current `fed-rates` event slug works.)

- [ ] **Step 3: Commit**

```bash
cd /home/dooleys/.hermes/custom-skills
git add dooleys-polymarket-reader/polymarket_client.py
git commit -m "feat(polymarket): keyless HTTP client (Gamma events/search + CLOB history)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: `polymarket_reader.py` — scan entry script

**Files:**
- Create: `dooleys-polymarket-reader/polymarket_reader.py`

**Interfaces:**
- Consumes: `polymarket_common` (`load_config`, `resolve_slugs`, `enrich_event`, `passes_denoise`, `rank_and_cap`, `now_iso`, `parse_event_ref`), `polymarket_client` (`PolymarketClient`, `PolymarketError`).
- Produces: writes `output_polymarket_reader.json`; exit codes 0/1/2.

- [ ] **Step 1: Write the script**

`dooleys-polymarket-reader/polymarket_reader.py`:
```python
#!/usr/bin/env python3
"""Scan macro/investment-relevant Polymarket categories and emit a ranked,
de-noised JSON feed of significant markets. Keyless."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import polymarket_common as pc
from polymarket_client import PolymarketClient, PolymarketError

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "config", "categories.json")
DEFAULT_WATCHLIST = os.path.join(HERE, "config", "watchlist.json")
DEFAULT_OUTPUT = os.path.join(HERE, "output_polymarket_reader.json")


def _csv(value):
    return [x.strip() for x in value.split(",") if x.strip()] if value else None


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Scan Polymarket macro categories for significant markets.")
    p.add_argument("--categories", type=_csv, help="bucket names, e.g. monetary,geopolitics")
    p.add_argument("--tags", type=_csv, help="raw tag slugs (overrides --categories)")
    p.add_argument("--min-score", type=float, default=0.0)
    p.add_argument("--min-volume", type=float, default=None, help="override config min_volume floor")
    p.add_argument("--limit", type=int, default=40, help="max events in output")
    p.add_argument("--scan-limit", type=int, default=40, help="events fetched per tag")
    p.add_argument("--all", action="store_true", help="include filtered-out events too")
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.add_argument("--watchlist", default=DEFAULT_WATCHLIST)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    return p.parse_args(argv)


def load_watchlist(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return [pc.parse_event_ref(e)["value"] for e in (json.load(fh).get("events") or [])]
    except (FileNotFoundError, ValueError):
        return []


def main(argv=None):
    args = parse_args(argv)
    config = pc.load_config(args.config)
    if args.min_volume is not None:
        config["thresholds"]["min_volume"] = args.min_volume
    th, we = config["thresholds"], config["weights"]
    slugs_by_bucket = pc.resolve_slugs(config, args.categories, args.tags)
    if not slugs_by_bucket:
        print("No categories/tags resolved.", file=sys.stderr)
        return 1

    client = PolymarketClient()
    now = datetime.now(timezone.utc)
    errors = {}
    collected = {}  # event_id -> [raw_event, set(buckets), set(tags)]

    try:
        for bucket, slugs in slugs_by_bucket.items():
            for slug in slugs:
                try:
                    events = client.get_events_by_tag(slug, limit=args.scan_limit)
                except PolymarketError as e:
                    errors[f"tag:{slug}"] = str(e)
                    continue
                for ev in events:
                    eid = str(ev.get("id"))
                    if eid in collected:
                        collected[eid][1].add(bucket)
                        collected[eid][2].add(slug)
                    else:
                        collected[eid] = [ev, {bucket}, {slug}]
    except Exception as e:  # noqa: BLE001 — fatal before any usable result
        print(f"Fatal: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    enriched = [pc.enrich_event(ev, now, sorted(b), sorted(t), th, we)
                for ev, b, t in collected.values()]

    # Watchlist: always-include events by slug (deduped against the scan).
    seen_slugs = {e["slug"] for e in enriched}
    for slug in load_watchlist(args.watchlist):
        if slug in seen_slugs:
            for e in enriched:
                if e["slug"] == slug:
                    e["watchlisted"] = True
            continue
        try:
            ev = client.get_event_by_slug(slug)
        except PolymarketError as e:
            errors[f"watchlist:{slug}"] = str(e)
            continue
        if ev:
            enriched.append(pc.enrich_event(ev, now, ["watchlist"], [], th, we, watchlisted=True))

    kept = [e for e in enriched if pc.passes_denoise(e, th, args.min_score)]
    ranked = pc.rank_and_cap(kept, args.limit)
    kept_ids = {id(e) for e in ranked}
    filtered_out = [e for e in enriched if id(e) not in kept_ids] if args.all else []

    output = {
        "timestamp": pc.now_iso(),
        "params": {
            "categories": args.categories or list(slugs_by_bucket.keys()),
            "tags": args.tags, "min_score": args.min_score,
            "min_volume": th["min_volume"], "limit": args.limit,
        },
        "buckets_scanned": list(slugs_by_bucket.keys()),
        "counts": {
            "events_scanned": len(enriched),
            "events_kept": len(ranked),
            "filtered_out": len(enriched) - len(ranked),
        },
        "events": ranked,
        "filtered_out": filtered_out,
        "errors": errors,
    }
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {args.output}: {len(ranked)} events kept "
          f"(scanned {len(enriched)}, filtered {len(enriched) - len(ranked)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Live smoke (default scan)**

Run:
```bash
cd dooleys-polymarket-reader && python polymarket_reader.py --limit 10 && python -c "
import json
d = json.load(open('output_polymarket_reader.json'))
assert 'timestamp' in d and d['events'], 'empty output'
top = d['events'][0]
print('top:', top['title'], '| sig=%.2f' % top['event_significance'], '| buckets:', top['buckets'])
print('counts:', d['counts'])
"
```
Expected: writes file; top event is a macro market (Fed/geopolitics/election) with a significance score; `counts.filtered_out` > 0.

- [ ] **Step 3: Live smoke (tunable flags + failure isolation)**

Run:
```bash
cd dooleys-polymarket-reader && python polymarket_reader.py --tags nonexistent-tag-xyz,fed-rates --limit 5 && python -c "
import json; d = json.load(open('output_polymarket_reader.json'))
print('errors:', list(d['errors'].keys()))   # may include the bad tag if it errors; empty tag returns [] not an error
print('kept:', d['counts']['events_kept'])
"
```
Expected: runs cleanly (a bad/empty tag yields 0 events, not a crash); fed-rates events present.

- [ ] **Step 4: Verify keyless (no env vars needed)**

Run:
```bash
cd dooleys-polymarket-reader && env -u POLYMARKET_API_KEY -u POLYMARKET_SECRET -u POLYMARKET_PASSPHRASE python polymarket_reader.py --categories monetary --limit 3 >/dev/null && echo "KEYLESS OK"
```
Expected: `KEYLESS OK`.

- [ ] **Step 5: Commit**

```bash
cd /home/dooleys/.hermes/custom-skills
git add dooleys-polymarket-reader/polymarket_reader.py
git commit -m "feat(polymarket): reader scan entry (ranked, de-noised macro feed)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: `polymarket_search.py` — ad-hoc keyword search entry

**Files:**
- Create: `dooleys-polymarket-reader/polymarket_search.py`

**Interfaces:**
- Consumes: `polymarket_common` (`load_config`, `enrich_event`, `now_iso`), `polymarket_client`.
- Produces: writes `output_polymarket_search.json`; exit 0/1.

- [ ] **Step 1: Write the script**

`dooleys-polymarket-reader/polymarket_search.py`:
```python
#!/usr/bin/env python3
"""Ad-hoc Polymarket keyword search: 'what does the market say about <X>?'
Returns matching events with the same signal block as the reader. Keyless."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import polymarket_common as pc
from polymarket_client import PolymarketClient, PolymarketError

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "config", "categories.json")
DEFAULT_OUTPUT = os.path.join(HERE, "output_polymarket_search.json")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Search Polymarket events by keyword.")
    p.add_argument("query", nargs="?", help="search text")
    p.add_argument("--query", dest="query_opt", help="search text (alt to positional)")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    query = args.query or args.query_opt
    if not query:
        print("No query provided.", file=sys.stderr)
        return 1
    config = pc.load_config(args.config)
    th, we = config["thresholds"], config["weights"]
    client = PolymarketClient()
    now = datetime.now(timezone.utc)
    errors = {}
    try:
        events = client.search_events(query, limit=args.limit)
    except PolymarketError as e:
        events, errors["search"] = [], str(e)

    enriched = [pc.enrich_event(ev, now, [], [], th, we) for ev in events]
    enriched.sort(key=lambda e: e.get("event_significance", 0.0), reverse=True)

    output = {
        "timestamp": pc.now_iso(),
        "query": query,
        "count": len(enriched),
        "events": enriched,
        "errors": errors,
    }
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {args.output}: {len(enriched)} events for '{query}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Live smoke**

Run:
```bash
cd dooleys-polymarket-reader && python polymarket_search.py taiwan --limit 5 && python -c "
import json; d = json.load(open('output_polymarket_search.json'))
assert d['query'] == 'taiwan' and 'timestamp' in d
print('count:', d['count'], '| first:', d['events'][0]['title'] if d['events'] else None)
"
```
Expected: returns events mentioning Taiwan (e.g. a China×Taiwan event), each with `event_significance`.

- [ ] **Step 3: Failure path (no query)**

Run: `cd dooleys-polymarket-reader && python polymarket_search.py; echo "exit=$?"`
Expected: `No query provided.` and `exit=1`.

- [ ] **Step 4: Commit**

```bash
cd /home/dooleys/.hermes/custom-skills
git add dooleys-polymarket-reader/polymarket_search.py
git commit -m "feat(polymarket): ad-hoc keyword search entry

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: `polymarket_event.py` — drill-down entry + docs + final smoke + push

**Files:**
- Create: `dooleys-polymarket-reader/polymarket_event.py`
- Create: `dooleys-polymarket-reader/SKILL.md`
- Create: `dooleys-polymarket-reader/README.md`
- Modify: repo-root `README.md` (skills table + structure)
- Modify: repo-root `CLAUDE.md` (skills list)

**Interfaces:**
- Consumes: `polymarket_common` (`parse_event_ref`, `enrich_event`, `coerce_list`, `now_iso`, `load_config`), `polymarket_client`.
- Produces: writes `output_polymarket_event.json`; exit 0/1.

- [ ] **Step 1: Write `polymarket_event.py`**

`dooleys-polymarket-reader/polymarket_event.py`:
```python
#!/usr/bin/env python3
"""Deep-dive a single Polymarket event/market by URL, slug, or id. Optionally
attach the odds time-series (price history) per market. Keyless."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import polymarket_common as pc
from polymarket_client import PolymarketClient, PolymarketError

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "config", "categories.json")
DEFAULT_OUTPUT = os.path.join(HERE, "output_polymarket_event.json")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Deep-dive one Polymarket event by url/slug/id.")
    p.add_argument("ref", help="Polymarket event URL, slug, or numeric id")
    p.add_argument("--history", action="store_true", help="attach price-history per market")
    p.add_argument("--interval", default="1w", help="history window (e.g. 1d,1w,1m,max)")
    p.add_argument("--fidelity", type=int, default=180, help="history resolution (minutes)")
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    config = pc.load_config(args.config)
    th, we = config["thresholds"], config["weights"]
    client = PolymarketClient()
    ref = pc.parse_event_ref(args.ref)
    now = datetime.now(timezone.utc)
    errors = {}

    try:
        raw = (client.get_event_by_id(ref["value"]) if ref["kind"] == "id"
               else client.get_event_by_slug(ref["value"]))
    except PolymarketError as e:
        print(f"Lookup failed: {e}", file=sys.stderr)
        return 1
    if not raw:
        print(f"Event not found for ref: {args.ref}", file=sys.stderr)
        return 1

    record = pc.enrich_event(raw, now, [], [], th, we)
    record["description"] = raw.get("description")

    if args.history:
        raw_markets = raw.get("markets") or []
        for i, mrec in enumerate(record["markets"]):
            token_ids = pc.coerce_list(raw_markets[i].get("clobTokenIds")) if i < len(raw_markets) else []
            if not token_ids:
                mrec["price_history"] = []
                continue
            try:
                mrec["price_history"] = client.get_price_history(
                    token_ids[0], interval=args.interval, fidelity=args.fidelity)
            except PolymarketError as e:
                mrec["price_history"] = []
                errors[f"history:{mrec.get('question')}"] = str(e)

    output = {"timestamp": pc.now_iso(), "requested_ref": args.ref,
              "event": record, "errors": errors}
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {args.output}: '{record['title']}' "
          f"({len(record['markets'])} markets{', with history' if args.history else ''}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Live smoke (event + history)**

Run:
```bash
cd dooleys-polymarket-reader && python polymarket_event.py "https://polymarket.com/event/fed-decision-in-july" --history --interval 1w && python -c "
import json; d = json.load(open('output_polymarket_event.json'))
e = d['event']
print('title:', e['title'], '| markets:', len(e['markets']))
print('first market sig=%.2f, history points:' % e['markets'][0]['significance_score'], len(e['markets'][0].get('price_history', [])))
"
```
Expected: prints the event title, its markets, and >0 history points on the first market. (If that slug 404s, substitute any current slug from `output_polymarket_reader.json`.)

- [ ] **Step 3: Failure path (bad ref)**

Run: `cd dooleys-polymarket-reader && python polymarket_event.py "this-slug-does-not-exist-xyz"; echo "exit=$?"`
Expected: `Event not found ...` and `exit=1`.

- [ ] **Step 4: Run the full unit suite once more**

Run: `cd dooleys-polymarket-reader && python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 5: Write `SKILL.md`**

`dooleys-polymarket-reader/SKILL.md` — frontmatter then body. Use this exact frontmatter:
```yaml
---
name: dooleys-polymarket-reader
description: Read macro/investment-relevant signals from Polymarket (the prediction market) via its public, keyless Gamma + CLOB read APIs. Use this skill to scan curated macro categories (Fed/rates, inflation, elections, geopolitics, commodities, crypto) for SIGNIFICANT markets — flagged by extreme consensus, fast repricing (big 1d/1w odds moves), conviction volume, and high-stakes toss-ups — returned as a ranked, de-noised JSON feed; OR to keyword-search Polymarket ad-hoc; OR to deep-dive one event/market (full odds + optional price-history curve). The skill scopes + scores + ranks; the agent interprets investment implications. No API key required (Polymarket reading is public; the POLYMARKET_* trading keys are NOT used).
version: 1.0.0
category: dooleys
---
```
Body MUST cover (write it out in full prose + tables, following the `dooleys-substack-reader/SKILL.md` structure):
- **What it is / thesis** — real-money odds as an early macro signal (Trump-2024 / Hormuz examples).
- **When to use** — the three entry scripts and when each applies; when NOT to (non-macro fun markets are de-noised out by default; use `--all`/`--tags`/`--query` to override).
- **Auth model** — keyless; `POLYMARKET_*` keys exist but are unused (trading/v2).
- **The signal engine** — the four flags + thresholds + `significance_score` weights, and the de-noise pipeline (category allowlist → volume floor → assets-only horizon cut → rank → cap). State all default values from Global Constraints.
- **The three functions** — for each: purpose, command examples, every flag, exit codes (copy from Tasks 7/8/9).
- **Output format** — the event-grouped JSON shape (timestamp, params, counts, events[].markets[] with signals/flags, errors); search adds `query`; event adds `description` + per-market `price_history`.
- **Configuration** — `config/categories.json` (buckets/thresholds/weights; ship `.example`) and `config/watchlist.json` (always-track slugs).
- **Error handling** — per-tag/per-watchlist/per-history isolation under `errors`; exit codes.
- **API notes** — endpoints used (verbatim from Global Constraints), that array fields may be JSON strings, and to re-verify field names if parsing breaks.

- [ ] **Step 6: Write `README.md`**

`dooleys-polymarket-reader/README.md` — human setup + testing walkthrough (model on `dooleys-substack-reader/README.md`): what the skill does; install (`pip install -r requirements.txt`); `cp config/categories.example.json config/categories.json` (optional — defaults are built in) and `cp config/watchlist.example.json config/watchlist.json` (optional); the three commands with sample output; a **Testing** section listing: `python -m pytest tests/ -q` (unit), the three live smokes from Tasks 7–9, the failure paths, and the keyless check; note `output_*.json` and `config/*.json` are gitignored.

- [ ] **Step 7: Update repo `README.md` and `CLAUDE.md`**

In repo-root `README.md`: add a `dooleys-polymarket-reader` row to the skills table and an entry in the structure section (match existing formatting — read the file first to mirror its table columns).
In repo-root `CLAUDE.md` "Skills here" list: add a bullet:
```markdown
- **dooleys-polymarket-reader** — keyless reader for Polymarket prediction-market signals (API
  flavor). `polymarket_reader.py` (scan macro categories → ranked, de-noised significant markets),
  `polymarket_search.py` (ad-hoc keyword search), `polymarket_event.py` (deep-dive one event +
  optional odds history), sharing `polymarket_client.py` (Gamma + CLOB-read transport) and
  `polymarket_common.py` (pure signal/scoring logic, unit-tested). Macro vs. noise handled by a
  category allowlist + significance score (extreme consensus / big move / conviction / toss-up);
  the agent does the investment interpretation. Keys not required.
```

- [ ] **Step 8: Clean generated artifacts**

Run:
```bash
cd dooleys-polymarket-reader && rm -f output_*.json && rm -rf __pycache__ tests/__pycache__ .pytest_cache
git status --short
```
Expected: only source/docs files staged-or-untracked; no `output_*.json`, no `config/*.json` (only `*.example.json`), no `__pycache__`.

- [ ] **Step 9: Commit & push**

```bash
cd /home/dooleys/.hermes/custom-skills
git add dooleys-polymarket-reader/polymarket_event.py dooleys-polymarket-reader/SKILL.md dooleys-polymarket-reader/README.md README.md CLAUDE.md
git commit -m "feat(polymarket): event drill-down + docs; finalize dooleys-polymarket-reader v1.0.0

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin main
```
Expected: clean push to `main`. Verify `git status` shows no tracked `tmp.env`, no secrets, no `output_*.json`.

---

## Self-Review

**Spec coverage:**
- §1 thesis/division of labor → SKILL.md (Task 9 Step 5), score+de-noise (Tasks 3–4). ✓
- §2 API findings → client (Task 6) uses every verified endpoint. ✓
- §3 architecture/file layout → Tasks 1–9 create exactly the spec's tree. ✓
- §4 signal engine (fields, flags, score, de-noise, parse_event_ref) → Tasks 2–4. ✓
- §5 buckets (all four, assets horizon-cut) → Task 1 config + Task 4 `passes_denoise` + Task 5 `resolve_slugs`. ✓
- §6 three entry points + flags/exit codes → Tasks 7–9. ✓
- §7 event-grouped output → `enrich_event` (Task 4) + each entry script's output dict. ✓
- §8 keyless/config/gitignore/tmp.env → Task 1 + Task 7 Step 4. ✓
- §9 testing (unit/failure/live smoke/keyless) → tests in Tasks 2–5; smokes in 6–9. ✓
- §11 implementation notes (JSON-string arrays, None-safe changes, volume fallbacks) → `coerce_list`/`to_float`/None-safe in Tasks 2–3. ✓

**Placeholder scan:** SKILL.md/README.md content is specified by required-sections + a reference file to mirror (not literal prose) — acceptable for docs tasks; all code steps contain complete code. No TBD/TODO in code.

**Type consistency:** `enrich_event(event, now, buckets, tags, thresholds, weights, watchlisted)` signature consistent across Tasks 4/7/8/9. `significance_score`/`compute_flags`/`compute_market_signals` signatures match between definition (Task 3) and callers. `PolymarketClient` method names match between Task 6 and Tasks 7–9. Output keys (`event_significance`, `significance_score`, `flags`, `counts`) consistent across producer (Task 4) and consumers (smoke tests).

One note carried to execution: `passes_denoise` re-derives "now" internally for the horizon check (Task 4), which is fine for live runs and the near-now test fixtures; do not refactor it to require a passed-in `now` without updating the Task 4 tests.
