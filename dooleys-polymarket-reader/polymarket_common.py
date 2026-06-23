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
