"""Unit tests for the pure logic in polymarket_common.

These cover parsing / signal / scoring / de-noise / config logic that does NOT
need the network, so they run fast and offline:

    python3 tests/test_polymarket_common.py    # built-in runner (no pytest needed)
    python3 -m pytest tests/                    # also works if pytest is installed
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
    assert set(rec.keys()) == {
        "question", "consensus_outcome", "implied_prob", "extremeness",
        "move_1d", "move_1w", "volume_24h", "volume_total", "liquidity",
        "days_to_resolve", "flags", "significance_score",
    }

def test_compute_market_signals_none_price_change_safe():
    m = dict(FED_MARKET, oneDayPriceChange=None, oneWeekPriceChange=None)
    rec = c.compute_market_signals(m, NOW)
    assert rec["move_1d"] == 0.0 and rec["move_1w"] == 0.0


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


def test_load_config_defaults_when_missing():
    cfg = c.load_config("/nonexistent/dir/nope.json")
    assert cfg["thresholds"]["extreme_p"] == 0.85
    assert "monetary" in cfg["buckets"]

def test_load_config_overrides():
    import json as _json
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "categories.json")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write('{"thresholds": {"min_volume": 99}, "buckets": {"x": ["y"]}}')
        cfg = c.load_config(p)
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


# --------------------------------------------------------------------------- #
# minimal self-contained runner (no pytest dependency required)
# --------------------------------------------------------------------------- #
def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
