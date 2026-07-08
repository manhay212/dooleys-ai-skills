"""Unit tests for the EODHD adapter — dormant without a key, parses with one."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sources.eodhd as e  # noqa: E402


def test_dormant_without_key(monkeypatch):
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    assert e.fetch("GSPC.INDX", "2026-01-01", "2026-07-01",
                   {"auth_env": "EODHD_API_KEY"}).empty


def test_parse_with_key(monkeypatch):
    monkeypatch.setenv("EODHD_API_KEY", "k")

    class _R:
        def raise_for_status(self):
            pass
        def json(self):
            return [{"date": "2026-07-01", "open": 1, "high": 2, "low": 0.5,
                     "close": 1.5, "adjusted_close": 1.4, "volume": 9}]

    monkeypatch.setattr(e.requests, "get", lambda *a, **k: _R())
    df = e.fetch("GSPC.INDX", "2026-07-01", "2026-07-01", {"auth_env": "EODHD_API_KEY"})
    assert float(df.iloc[0]["adj_close"]) == 1.4
    assert float(df.iloc[0]["close"]) == 1.5
