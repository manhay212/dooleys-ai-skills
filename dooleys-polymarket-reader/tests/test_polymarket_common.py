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
