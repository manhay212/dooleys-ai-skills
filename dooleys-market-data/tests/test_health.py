"""Unit tests for health.py — the freshness classifier and report rendering.

Run: python -m pytest tests/test_health.py -q
(from the dooleys-market-data skill root)
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import health  # noqa: E402


TODAY = date(2026, 6, 22)


# ─── classify_series_freshness ───────────────────────────────────────────────

def test_daily_series_fetched_today_is_ok_even_if_data_a_few_days_old():
    # DGS10: latest FRED data is 2026-06-17 (Juneteenth + weekend gap), but the
    # fetch succeeded today with nothing newer → current, NOT stale.
    status, reason = health.classify_series_freshness(
        frequency="daily",
        latest_date=date(2026, 6, 17),
        last_ingest_status="no_new_data",
        today=TODAY,
    )
    assert status == "ok", reason


def test_monthly_series_with_period_start_dating_is_not_stale():
    # CPI dated at month-start; "52 days old" is normal between releases.
    status, _ = health.classify_series_freshness(
        frequency="monthly",
        latest_date=date(2026, 5, 1),
        last_ingest_status="no_new_data",
        today=TODAY,
    )
    assert status == "ok"


def test_monthly_pce_82_days_is_still_ok():
    # COREPCE dated 2026-04-01 (82d) — current given PCE's release lag.
    status, _ = health.classify_series_freshness(
        frequency="monthly",
        latest_date=date(2026, 4, 1),
        last_ingest_status="success",
        today=TODAY,
    )
    assert status == "ok"


def test_errored_fetch_is_broken():
    status, reason = health.classify_series_freshness(
        frequency="daily",
        latest_date=date(2026, 6, 1),
        last_ingest_status="error",
        today=TODAY,
    )
    assert status == "broken"
    assert "errored" in reason


def test_no_data_at_all_is_no_data():
    status, _ = health.classify_series_freshness(
        frequency="daily",
        latest_date=None,
        last_ingest_status="no_new_data",
        today=TODAY,
    )
    assert status == "no_data"


def test_no_data_plus_error_is_broken():
    status, _ = health.classify_series_freshness(
        frequency="daily",
        latest_date=None,
        last_ingest_status="error",
        today=TODAY,
    )
    assert status == "broken"


def test_frozen_daily_feed_eventually_flags_late():
    # Successful fetches but data is 40 days old → soft "late" watch.
    status, reason = health.classify_series_freshness(
        frequency="daily",
        latest_date=date(2026, 5, 13),
        last_ingest_status="no_new_data",
        today=TODAY,
    )
    assert status == "late"
    assert "frozen" in reason or "lagging" in reason


def test_grace_override_suppresses_false_alarm_for_laggy_fx():
    # FRED FX publishes with ~1-week lag; a 10-day-old reading with grace=14 is fine.
    status, _ = health.classify_series_freshness(
        frequency="daily",
        latest_date=date(2026, 6, 12),
        last_ingest_status="no_new_data",
        today=TODAY,
        grace_days=14,
    )
    assert status == "ok"


def test_none_frequency_defaults_to_daily_bound():
    status, _ = health.classify_series_freshness(
        frequency=None,
        latest_date=date(2026, 6, 20),
        last_ingest_status="success",
        today=TODAY,
    )
    assert status == "ok"


def test_none_ingest_status_with_data_uses_age_only():
    # No ingest history (e.g. legacy backfill) but fresh data → ok, not broken.
    status, _ = health.classify_series_freshness(
        frequency="daily",
        latest_date=date(2026, 6, 20),
        last_ingest_status=None,
        today=TODAY,
    )
    assert status == "ok"


# ─── build_report ────────────────────────────────────────────────────────────

def _mk(ticker, source, status, freq="daily", latest=date(2026, 6, 20)):
    return {
        "ticker": ticker,
        "source": source,
        "frequency": freq,
        "latest_date": latest,
        "status": status,
        "reason": f"{status} reason",
    }


def test_build_report_counts_and_buckets():
    health_rows = [
        _mk("DGS10", "fred", "ok"),
        _mk("CPI", "fred", "ok", freq="monthly"),
        _mk("TGA_DAILY", "treasury", "broken"),
        _mk("CCL", "centaline", "no_data"),
        _mk("WM2NS", "fred", "late", freq="weekly"),
    ]
    rep = health.build_report(health_rows)
    assert rep["total_active"] == 5
    assert rep["ok"] == 2
    assert rep["late"] == 1
    assert rep["broken"] == 1
    assert rep["no_data"] == 1
    assert rep["needs_attention"] == 2  # broken + no_data
    assert rep["healthy"] == 3          # ok + late
    assert rep["by_source"]["fred"]["ok"] == 2
    assert len(rep["attention_list"]) == 2
    assert len(rep["watch_list"]) == 1


# ─── render_update_log ───────────────────────────────────────────────────────

def test_render_clean_run_has_celebration_and_no_attention_table():
    rows = [_mk("DGS10", "fred", "ok"), _mk("SPX", "yahoo", "ok")]
    rep = health.build_report(rows)
    md = health.render_update_log(rep, {"updated": 1, "current": 1, "errors": 0}, rows, "2026-06-22T06:00:00+08:00")
    assert "✅ 2 OK" in md
    assert "nothing needs attention" in md
    assert "## ⚠️ Needs attention" not in md
    # Freshness table lists every series.
    assert "DGS10" in md and "SPX" in md


def test_render_flags_broken_series_in_attention_table():
    rows = [_mk("DGS10", "fred", "ok"), _mk("TGA_DAILY", "treasury", "broken")]
    rep = health.build_report(rows)
    md = health.render_update_log(rep, None, rows, "2026-06-22T06:00:00+08:00")
    assert "## ⚠️ Needs attention (1)" in md
    assert "TGA_DAILY" in md
    assert "⚠️" in md  # the result line warns


def test_render_shows_served_by_column_and_fallback_marker():
    served = _mk("SPX", "yahoo_direct", "ok")
    served["served_by"] = "yahoo_direct"
    served["fell_back"] = False
    fell = _mk("NDX", "yahoo_direct", "ok")
    fell["served_by"] = "fred"           # primary was yahoo_direct → this is a fall-back
    fell["fell_back"] = True
    rep = health.build_report([served, fell])
    md = health.render_update_log(rep, None, [served, fell], "2026-07-09T06:00:00+08:00")
    assert "Served by" in md              # new column header
    assert "fred ⚠" in md                 # fall-back marked
    # the primary-served row shows the source with no warning marker
    assert "| SPX | yahoo_direct | yahoo_direct |" in md
