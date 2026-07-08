"""Unit tests for cross-provider table_kind normalization."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
from market_data import _normalize_kind  # noqa: E402


def test_obs_to_ohlcv():
    df = pd.DataFrame({"date": ["2026-07-01"], "value": [100.0]})
    out = _normalize_kind(df, "ohlcv")
    assert out.iloc[0]["close"] == 100.0 and out.iloc[0]["adj_close"] == 100.0
    assert "value" not in out.columns


def test_ohlcv_to_obs():
    df = pd.DataFrame({"date": ["2026-07-01"], "close": [10.0], "adj_close": [9.5]})
    out = _normalize_kind(df, "observations")
    assert out.iloc[0]["value"] == 9.5
    assert "value" in out.columns


def test_passthrough_ohlcv():
    df = pd.DataFrame({"date": ["2026-07-01"], "close": [10.0], "adj_close": [10.0]})
    out = _normalize_kind(df, "ohlcv")
    assert "close" in out.columns and "value" not in out.columns


def test_unusable_to_obs_returns_empty():
    df = pd.DataFrame({"date": ["2026-07-01"], "volume": [5.0]})  # no close/adj_close
    out = _normalize_kind(df, "observations")
    assert out.empty
