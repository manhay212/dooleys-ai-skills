"""Unit test for the yahoo_direct v8 payload parser (no network)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sources.yahoo_direct as yd  # noqa: E402

FIXTURE = {"chart": {"result": [{
    "timestamp": [1751328000],
    "indicators": {
        "quote": [{"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5], "volume": [100]}],
        "adjclose": [{"adjclose": [1.4]}],
    }}]}}


class _Resp:
    status_code = 200
    def json(self):
        return FIXTURE


def test_parse(monkeypatch):
    # Bypass the transport entirely; feed the fixture to the parser.
    monkeypatch.setattr(yd, "_http_get", lambda url, params: _Resp())
    df = yd.fetch("^GSPC", "2025-07-01", "2025-07-02", {})
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "adj_close"]
    assert float(df.iloc[0]["adj_close"]) == 1.4
    assert float(df.iloc[0]["close"]) == 1.5


def test_empty_on_no_response(monkeypatch):
    monkeypatch.setattr(yd, "_http_get", lambda url, params: None)
    assert yd.fetch("^GSPC", "2025-07-01", "2025-07-02", {"max_retries": 1}).empty
