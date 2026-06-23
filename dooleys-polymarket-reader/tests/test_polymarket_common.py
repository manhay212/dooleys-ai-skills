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
