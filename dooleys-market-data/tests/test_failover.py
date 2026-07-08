"""Unit tests for _fetch_with_failover — chain fall-through, provenance, gating."""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
from sources import register_adapter  # noqa: E402
import market_data as md  # noqa: E402


def _fake(name, df=None, raises=False):
    """Register a fake adapter module named sources.fake_<name>."""
    mod = types.ModuleType(f"sources.fake_{name}")

    def _fetch(*a, **k):
        if raises:
            raise RuntimeError("boom")
        return df if df is not None else pd.DataFrame()

    mod.fetch = _fetch
    sys.modules[mod.__name__] = mod
    register_adapter(name, mod.__name__)


CATALOG = {"defaults": {}}


def test_falls_through_to_second_source():
    _fake("empty1", pd.DataFrame())
    _fake("good2", pd.DataFrame({"date": ["2026-07-01"], "value": [5.0]}))
    series = {"ticker": "X", "table_kind": "observations",
              "sources": [{"source": "empty1", "symbol": "a"},
                          {"source": "good2", "symbol": "b"}]}
    cfg = {"sources": {"empty1": {"auth_env": None}, "good2": {"auth_env": None}}}
    df, _f, _t, served = md._fetch_with_failover(series, cfg, CATALOG, backfill=False, since=None)
    assert served == "good2" and not df.empty


def test_all_empty_returns_none():
    _fake("e1", pd.DataFrame())
    _fake("e2", pd.DataFrame())
    series = {"ticker": "Y", "table_kind": "ohlcv",
              "sources": [{"source": "e1", "symbol": "a"}, {"source": "e2", "symbol": "b"}]}
    cfg = {"sources": {"e1": {"auth_env": None}, "e2": {"auth_env": None}}}
    df, _f, _t, served = md._fetch_with_failover(series, cfg, CATALOG, backfill=False, since=None)
    assert df is None and served is None


def test_gated_primary_skipped_then_fallback_served(monkeypatch):
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    _fake("k+backup", pd.DataFrame({"date": ["2026-07-01"], "value": [9.0]}))
    series = {"ticker": "Z", "table_kind": "observations",
              "sources": [{"source": "eodhd", "symbol": "Z.INDX"},          # dormant, no key
                          {"source": "k+backup", "symbol": "z"}]}
    cfg = {"sources": {"eodhd": {"auth_env": "EODHD_API_KEY"},
                       "k+backup": {"auth_env": None}}}
    df, _f, _t, served = md._fetch_with_failover(series, cfg, CATALOG, backfill=False, since=None)
    assert served == "k+backup" and not df.empty


def test_all_hard_error_raises():
    _fake("boom1", raises=True)
    _fake("boom2", raises=True)
    series = {"ticker": "E", "table_kind": "ohlcv",
              "sources": [{"source": "boom1", "symbol": "a"}, {"source": "boom2", "symbol": "b"}]}
    cfg = {"sources": {"boom1": {"auth_env": None}, "boom2": {"auth_env": None}}}
    try:
        md._fetch_with_failover(series, cfg, CATALOG, backfill=False, since=None)
        assert False, "expected RuntimeError when every source hard-errors"
    except RuntimeError:
        pass
