"""Unit tests for summarize.py — stats, ratio, spread — on synthetic in-memory data.

Run: python -m pytest tests/test_summarize.py -q
"""

import os
import sys
import sqlite3
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import summarize  # noqa: E402

SCHEMA = """
CREATE TABLE series (
    series_id INTEGER PRIMARY KEY, ticker TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
    asset_class TEXT NOT NULL, subclass TEXT, source TEXT NOT NULL, source_symbol TEXT NOT NULL,
    unit TEXT, frequency TEXT, table_kind TEXT NOT NULL, first_available DATE, last_updated DATE,
    status TEXT DEFAULT 'active', trigger_levels TEXT, notes TEXT
);
CREATE TABLE ohlcv (
    series_id INTEGER, date DATE, open REAL, high REAL, low REAL, close REAL, adj_close REAL,
    volume REAL, PRIMARY KEY (series_id, date)
);
CREATE TABLE observations (
    series_id INTEGER, date DATE, value REAL, PRIMARY KEY (series_id, date)
);
"""


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def _add_obs(c, sid, ticker, name, values, start=date(2026, 1, 1), unit="percent", trig=None):
    c.execute(
        "INSERT INTO series (series_id,ticker,name,asset_class,source,source_symbol,unit,frequency,table_kind,trigger_levels,status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,'active')",
        (sid, ticker, name, "macro-rates", "fred", ticker, unit, "daily", "observations", trig),
    )
    for i, v in enumerate(values):
        d = (start + timedelta(days=i)).isoformat()
        c.execute("INSERT INTO observations (series_id,date,value) VALUES (?,?,?)", (sid, d, v))
    c.commit()


def test_stats_basic_and_percentile():
    c = _conn()
    _add_obs(c, 1, "DGS10", "US 10Y", [float(x) for x in range(1, 101)])  # 1..100
    r = summarize.stats(c, "DGS10", windows=["1d", "1m"])
    assert r["latest_value"] == 100.0
    assert r["data_points"] == 100
    # latest is the max → percentile 99 (99 of 100 values are below it)
    assert r["percentile"] == 99.0
    assert "z_score" in r


def test_stats_nearest_trigger():
    c = _conn()
    _add_obs(c, 1, "VIX", "VIX", [10, 12, 14, 26], unit="index", trig='{"complacent":13,"stress":25,"panic":35}')
    r = summarize.stats(c, "VIX")
    assert r["nearest_trigger"]["trigger"] == "stress"
    assert r["nearest_trigger"]["direction"] == "above"


def test_spread_difference():
    c = _conn()
    # 2Y = 4.5 flat, FFR = 4.0 flat → spread +0.5
    _add_obs(c, 1, "DGS2", "US 2Y", [4.5] * 30)
    _add_obs(c, 2, "EFFR", "Fed Funds", [4.0] * 30)
    r = summarize.spread(c, "DGS2", "EFFR", windows=["1w"])
    assert r["current_spread"] == 0.5
    assert r["a_ticker"] == "DGS2" and r["b_ticker"] == "EFFR"


def test_spread_missing_series_errors():
    c = _conn()
    _add_obs(c, 1, "DGS2", "US 2Y", [4.5] * 5)
    r = summarize.spread(c, "DGS2", "NOPE")
    assert "error" in r


def test_ratio_basic():
    c = _conn()
    _add_obs(c, 1, "HG", "Copper", [4.0] * 20, unit="usd")
    _add_obs(c, 2, "GC", "Gold", [2.0] * 20, unit="usd")
    r = summarize.ratio(c, "HG", "GC", windows=["1w"])
    assert r["current_ratio"] == 2.0
