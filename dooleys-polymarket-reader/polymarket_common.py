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
    momentum_norm = min(1.0, abs(move_1w or 0) / t["momentum_ref"])
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
