"""
Health / freshness classification for dooleys-market-data.

Pure, dependency-light logic (no DB, no network) so it can be unit-tested.

The old `doctor` flagged "stale" purely on days-since-latest-data. That produced
constant false alarms because:
  - FRED dates monthly series at the *start* of the period and publishes with a
    multi-week lag, so a perfectly current CPI reading can look "52 days old".
  - FRED FX / EIA series publish with their own lags.
  - Weekends and US market holidays mean daily series legitimately don't move.

The reliable signal is the *fetch result*, not the date: if the most recent
ingest attempt succeeded (returned data or a clean "nothing newer"), the series
is as current as the source allows. A series is only BROKEN if the fetch itself
errored or there is no data at all. Date-age is used only as a soft, generous
"feed may be frozen" watch flag.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

# Generous calendar-day bounds, by series frequency, beyond which a *successfully
# fetched* series is soft-flagged as "late" (source may be lagging / feed frozen).
# These are deliberately loose to avoid the false alarms the old doctor produced.
WATCH_BOUNDS_DAYS: Dict[str, int] = {
    "daily": 12,    # weekend + holiday + typical publication lag
    "weekly": 16,   # one missed weekly release
    "monthly": 100,  # period-start dating + multi-week release lag; only flag if truly frozen
}

# Statuses, in severity order (worst first) for sorting/reporting.
SEVERITY = {"broken": 0, "no_data": 1, "late": 2, "ok": 3, "paused": 4}

# Ingest statuses that mean "we successfully reached the source".
_FETCH_OK_STATUSES = {"success", "no_new_data"}


def classify_series_freshness(
    *,
    frequency: Optional[str],
    latest_date: Optional[date],
    last_ingest_status: Optional[str],
    today: date,
    grace_days: Optional[int] = None,
) -> Tuple[str, str]:
    """Classify one series' freshness. Pure function.

    Parameters
    ----------
    frequency : 'daily' | 'weekly' | 'monthly' | None
        Series cadence (None → treated as daily).
    latest_date : date | None
        Date of the most recent stored data point, or None if the series has no data.
    last_ingest_status : str | None
        Status of the most recent ingest run: 'success', 'no_new_data', 'error',
        or None if there is no ingest history.
    today : date
        Reference date.
    grace_days : int | None
        Per-series override for the "late" bound (for known-laggy feeds).

    Returns
    -------
    (status, reason) where status ∈ {'ok', 'late', 'broken', 'no_data'}.
    """
    freq = (frequency or "daily").lower()

    if latest_date is None:
        if last_ingest_status == "error":
            return ("broken", "no data in DB and last fetch errored — adapter/source needs a fix")
        return ("no_data", "no data in DB — run backfill")

    # We have data. The most-recent fetch result is the authoritative signal.
    if last_ingest_status == "error":
        return ("broken", "last fetch errored — adapter/source needs a fix")

    bound = grace_days if grace_days is not None else WATCH_BOUNDS_DAYS.get(
        freq, WATCH_BOUNDS_DAYS["daily"]
    )
    age = (today - latest_date).days

    if age > bound:
        return (
            "late",
            f"latest data {latest_date.isoformat()} is {age}d old (>{bound}d for {freq}); "
            "source may be lagging or the feed is frozen — verify directly",
        )
    return ("ok", f"current ({age}d since latest {freq} data point)")


def build_report(series_health: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-series health dicts into a summary report.

    Each input dict must have: ticker, source, frequency, latest_date (date|None),
    status, reason. Optional: asset_class, name.

    "needs_attention" = broken + no_data (genuinely actionable).
    """
    counts: Dict[str, int] = {"ok": 0, "late": 0, "broken": 0, "no_data": 0}
    by_source: Dict[str, Dict[str, int]] = {}

    for s in series_health:
        st = s["status"]
        counts[st] = counts.get(st, 0) + 1
        src = s.get("source", "?")
        bucket = by_source.setdefault(src, {"ok": 0, "late": 0, "broken": 0, "no_data": 0})
        bucket[st] = bucket.get(st, 0) + 1

    needs_attention = [
        s for s in series_health if s["status"] in ("broken", "no_data")
    ]
    watch = [s for s in series_health if s["status"] == "late"]

    total = len(series_health)
    healthy = counts["ok"] + counts["late"]

    return {
        "total_active": total,
        "healthy": healthy,           # ok + late (data present, fetch not erroring)
        "ok": counts["ok"],
        "late": counts["late"],
        "needs_attention": len(needs_attention),
        "broken": counts["broken"],
        "no_data": counts["no_data"],
        "by_source": by_source,
        "attention_list": needs_attention,
        "watch_list": watch,
    }


def _sort_key(s: Dict[str, Any]):
    return (SEVERITY.get(s["status"], 9), s.get("source", ""), s["ticker"])


def render_update_log(
    report: Dict[str, Any],
    run_summary: Optional[Dict[str, int]],
    series_health: List[Dict[str, Any]],
    timestamp: str,
) -> str:
    """Render a clean, trustworthy UPDATE_LOG.md (pure string building).

    run_summary (optional): {'updated': n, 'current': n, 'errors': n} from the
    update pass that preceded the health check.
    """
    lines: List[str] = []
    lines.append("# Market Data Update Log")
    lines.append("")
    lines.append(f"**Last run:** {timestamp}")

    attention = report["needs_attention"]
    icon = "✅" if attention == 0 else "⚠️"
    lines.append(
        f"**Result:** {icon} {report['ok']} OK · {report['late']} lagging · "
        f"{attention} need attention · {report['total_active']} active series"
    )
    if run_summary is not None:
        lines.append(
            f"**This run:** {run_summary.get('updated', 0)} updated, "
            f"{run_summary.get('current', 0)} already-current, "
            f"{run_summary.get('errors', 0)} fetch errors"
        )
    lines.append("")

    # Needs-attention section (only genuinely broken series).
    if report["attention_list"]:
        lines.append(f"## ⚠️ Needs attention ({len(report['attention_list'])})")
        lines.append("")
        lines.append("| Ticker | Source | Problem |")
        lines.append("|--------|--------|---------|")
        for s in sorted(report["attention_list"], key=_sort_key):
            lines.append(f"| {s['ticker']} | {s.get('source','?')} | {s['reason']} |")
        lines.append("")
    else:
        lines.append("All active series fetched cleanly — nothing needs attention. 🎉")
        lines.append("")

    # Soft watch (lagging feeds) — informational, not failures.
    if report["watch_list"]:
        lines.append(f"## 🕊 Watch — possibly-lagging feeds ({len(report['watch_list'])})")
        lines.append("")
        lines.append("| Ticker | Source | Note |")
        lines.append("|--------|--------|------|")
        for s in sorted(report["watch_list"], key=_sort_key):
            lines.append(f"| {s['ticker']} | {s.get('source','?')} | {s['reason']} |")
        lines.append("")

    # Per-source summary.
    lines.append("## By source")
    lines.append("")
    lines.append("| Source | OK | Lagging | Needs attention |")
    lines.append("|--------|----|---------|-----------------|")
    for src in sorted(report["by_source"]):
        b = report["by_source"][src]
        lines.append(
            f"| {src} | {b.get('ok',0)} | {b.get('late',0)} | "
            f"{b.get('broken',0) + b.get('no_data',0)} |"
        )
    lines.append("")

    # Full freshness table (so the user can see every series' latest data point).
    lines.append("## Freshness (latest stored data point per active series)")
    lines.append("")
    lines.append("| Ticker | Source | Freq | Latest | Status |")
    lines.append("|--------|--------|------|--------|--------|")
    status_icon = {"ok": "✅", "late": "🕊", "broken": "❌", "no_data": "❌"}
    for s in sorted(series_health, key=_sort_key):
        ld = s.get("latest_date")
        ld_str = ld.isoformat() if isinstance(ld, date) else (str(ld) if ld else "—")
        freq = s.get("frequency") or "daily"
        ic = status_icon.get(s["status"], "")
        lines.append(
            f"| {s['ticker']} | {s.get('source','?')} | {freq} | {ld_str} | {ic} {s['status']} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("*Auto-generated by `market_data.py daily`. "
                 "OK = fetched cleanly and as current as the source allows; "
                 "lagging = fetch fine but data older than expected (verify); "
                 "needs attention = fetch failing or no data.*")
    lines.append("")
    return "\n".join(lines)
