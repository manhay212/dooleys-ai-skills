#!/usr/bin/env python3
"""
CLI entrypoint for dooleys-market-data.
Query, backfill, update, and manage the local market-data SQLite store.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from db import (
    get_db_path, get_market_data_dir, get_connection,
    init_db, get_series, upsert_series, upsert_ohlcv, upsert_observations,
    get_latest_date, get_last_ingest, log_ingest, query_ohlcv, query_observations,
    add_event, query_events, update_series_last_updated,
)
from catalog import load_catalog, load_sources, sync_catalog, staleness_grace_map
from summarize import (
    stats, latest, ratio, spread, dashboard, query_series_data,
)
import health

logger = logging.getLogger("market_data")


# ─── helpers ─────────────────────────────────────────────────────────────────

def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _parse_date_arg(val: str) -> Optional[date]:
    """Parse a date string like YYYY-MM-DD."""
    if not val:
        return None
    try:
        return datetime.strptime(val[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError(f"Invalid date: {val}")


def _parse_date_optional(val: Optional[str]) -> Optional[date]:
    if val is None:
        return None
    return _parse_date_arg(val)


# ─── commands ────────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> None:
    """Initialize the database from schema.sql."""
    db_path = get_db_path()
    schema_path = None
    if hasattr(args, "schema") and args.schema:
        schema_path = Path(args.schema)
    
    if db_path.exists():
        logger.warning("Database already exists at %s. Re-initializing...", db_path)
        db_path.unlink()
    
    init_db(db_path, schema_path)
    print(f"Database initialized at {db_path}")


def cmd_sync_catalog(args: argparse.Namespace) -> None:
    """Sync catalog.yaml with the series table."""
    conn = get_connection()
    try:
        catalog = load_catalog()
        result = sync_catalog(conn, catalog)
        _print_json(result)
    finally:
        conn.close()


def cmd_backfill(args: argparse.Namespace) -> None:
    """
    Backfill historical data for one or more series.
    Fetches from the configured source adapter, UPSERTs into DB,
    and updates series.last_updated.
    """
    conn = get_connection()
    try:
        # Resolve which series to backfill
        series_list = _resolve_series(conn, args)
        
        if not series_list:
            logger.error("No matching series found.")
            return
        
        sources_config = load_sources()
        catalog = load_catalog()
        
        results = []
        for s in series_list:
            ticker = s["ticker"]
            sid = s["series_id"]
            table_kind = s["table_kind"]

            # Check if recently updated (within 1 day) — resumable
            last_upd = s.get("last_updated")
            if last_upd:
                last_date = _parse_date_arg(str(last_upd)[:10]) if last_upd else None
                if last_date and last_date >= date.today() - timedelta(days=1):
                    logger.info("Skipping %s — updated %s (within 1 day)", ticker, last_date)
                    results.append({
                        "ticker": ticker, "status": "skipped",
                        "reason": f"Updated {last_date} — within 1 day",
                    })
                    continue

            try:
                df, from_date, to_date, served_by = _fetch_with_failover(
                    s, sources_config, catalog, backfill=True
                )

                if df is None or df.empty:
                    results.append({
                        "ticker": ticker, "status": "empty",
                        "reason": "No data returned from any source in chain",
                    })
                    continue

                # UPSERT
                if table_kind == "ohlcv":
                    rows = upsert_ohlcv(conn, sid, df)
                else:
                    rows = upsert_observations(conn, sid, df)

                # Update last_updated
                max_date = df["date"].max()
                update_series_last_updated(conn, sid, max_date)

                # Update first_available if needed
                min_date = df["date"].min()
                if s.get("first_available") is None:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE series SET first_available = ? WHERE series_id = ?",
                        (_to_date_str(min_date), sid),
                    )
                    conn.commit()

                # Log ingest
                run_id = log_ingest(conn, sid, rows, from_date, to_date, "success",
                                    served_by=served_by)

                logger.info("Backfilled %s: %d rows, %s to %s via %s (run %d)",
                            ticker, rows, _to_date_str(from_date) if from_date else "?",
                            _to_date_str(to_date) if to_date else "?", served_by, run_id)

                results.append({
                    "ticker": ticker, "status": "success",
                    "rows_added": rows, "served_by": served_by,
                    "from_date": _to_date_str(from_date),
                    "to_date": _to_date_str(to_date),
                    "run_id": run_id,
                })

            except Exception as exc:
                logger.error("Failed to backfill %s: %s", ticker, exc)
                log_ingest(conn, sid, 0, None, None, "error", str(exc))
                results.append({
                    "ticker": ticker, "status": "error",
                    "error": str(exc),
                })
            
            # No core-level rate-limit sleep: each adapter rate-limits itself.

        _print_json({"backfill_results": results})
    finally:
        conn.close()


def cmd_update(args: argparse.Namespace) -> None:
    """
    Incremental update: fetch from last_updated to today for matching series.
    """
    conn = get_connection()
    try:
        series_list = _resolve_series(conn, args)

        if not series_list:
            logger.error("No matching series found.")
            return

        per_timeout = getattr(args, "per_series_timeout", None)
        results = _update_series_list(conn, series_list, per_series_timeout=per_timeout)
        _print_json({"update_results": results})
    finally:
        conn.close()


# Per-series timeout so one slow/hung source can't starve the rest of the run.
class _SeriesTimeout(Exception):
    pass


def _with_timeout(seconds: Optional[int], fn, *a, **k):
    """Run fn with a hard wall-clock timeout (Unix main-thread only via SIGALRM).
    Falls back to no timeout where SIGALRM is unavailable."""
    import signal
    if not seconds or not hasattr(signal, "SIGALRM"):
        return fn(*a, **k)

    def _handler(signum, frame):  # noqa: ANN001
        raise _SeriesTimeout(f"timed out after {seconds}s")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(int(seconds))
    try:
        return fn(*a, **k)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _update_one(conn, s, sources_config, catalog) -> Dict[str, Any]:
    """Incrementally update a single series. Returns a result dict; never raises."""
    ticker = s["ticker"]
    sid = s["series_id"]
    table_kind = s["table_kind"]

    last_date = s.get("last_updated")
    last_date_obj = _parse_date_arg(str(last_date)[:10]) if last_date else None

    df, from_date, to_date, served_by = _fetch_with_failover(
        s, sources_config, catalog, backfill=False, since=last_date_obj,
    )

    if df is None or df.empty:
        # Reached the source(s), nothing newer available — record it so the health
        # check can distinguish "current with source" from "broken".
        log_ingest(conn, sid, 0, from_date, to_date, "no_new_data")
        return {"ticker": ticker, "status": "no_new_data", "reason": "No new data available"}

    if last_date_obj:
        df = _filter_after(df, last_date_obj)

    if df.empty:
        log_ingest(conn, sid, 0, from_date, to_date, "no_new_data", served_by=served_by)
        return {"ticker": ticker, "status": "no_new_data"}

    if table_kind == "ohlcv":
        rows = upsert_ohlcv(conn, sid, df)
    else:
        rows = upsert_observations(conn, sid, df)

    update_series_last_updated(conn, sid, df["date"].max())
    run_id = log_ingest(conn, sid, rows, from_date, to_date, "success", served_by=served_by)
    return {
        "ticker": ticker, "status": "success", "rows_added": rows, "served_by": served_by,
        "from_date": _to_date_str(from_date), "to_date": _to_date_str(to_date),
        "run_id": run_id,
    }


def _update_series_list(
    conn, series_list: List[Dict[str, Any]], per_series_timeout: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Update each series in turn with per-series error + timeout isolation.

    One failing or slow source records an error and the run continues — this is
    what keeps the daily ingest from going all-or-nothing.
    """
    if per_series_timeout is None:
        per_series_timeout = int(os.getenv("MARKET_DATA_SERIES_TIMEOUT", "60"))

    sources_config = load_sources()
    catalog = load_catalog()

    results: List[Dict[str, Any]] = []
    for s in series_list:
        ticker = s["ticker"]
        try:
            result = _with_timeout(
                per_series_timeout, _update_one, conn, s, sources_config, catalog
            )
        except Exception as exc:  # noqa: BLE001 — isolate every series
            logger.error("Failed to update %s: %s", ticker, exc)
            try:
                log_ingest(conn, s["series_id"], 0, None, None, "error", str(exc))
            except Exception:  # noqa: BLE001
                pass
            result = {"ticker": ticker, "status": "error", "error": str(exc)}
        results.append(result)
    return results


def cmd_query(args: argparse.Namespace) -> None:
    """Handle query subcommands: latest, stats, ratio, series, dashboard."""
    conn = get_connection()
    try:
        subcmd = args.query_subcommand
        
        if subcmd == "latest":
            tickers = _parse_tickers(args.tickers)
            result = latest(conn, tickers)
            _print_json(result)
        
        elif subcmd == "stats":
            tickers = _parse_tickers(args.ticker)
            windows = _parse_windows(getattr(args, "windows", None))
            for t in tickers:
                result = stats(conn, t, windows=windows)
                _print_json(result)
        
        elif subcmd == "ratio":
            if not args.num or not args.den:
                print("Error: --num and --den tickers required for ratio", file=sys.stderr)
                sys.exit(1)
            windows = _parse_windows(getattr(args, "windows", None))
            result = ratio(conn, args.num, args.den, windows=windows)
            _print_json(result)

        elif subcmd == "spread":
            if not args.a or not args.b:
                print("Error: --a and --b tickers required for spread", file=sys.stderr)
                sys.exit(1)
            windows = _parse_windows(getattr(args, "windows", None))
            result = spread(conn, args.a, args.b, windows=windows)
            _print_json(result)

        elif subcmd == "series":
            since = getattr(args, "since", None)
            until = getattr(args, "until", None)
            resample = getattr(args, "resample", None)
            result = query_series_data(
                conn, args.ticker,
                since=since, until=until,
                resample=resample,
            )
            _print_json(result)
        
        elif subcmd == "dashboard":
            groups = _parse_tickers(getattr(args, "group", ""))
            windows = _parse_windows(getattr(args, "windows", None))
            result = dashboard(conn, groups, windows=windows)
            _print_json(result)
        
        else:
            print(f"Unknown query subcommand: {subcmd}", file=sys.stderr)
            sys.exit(1)
    finally:
        conn.close()


def cmd_query_events(args: argparse.Namespace) -> None:
    """Query events from the database."""
    conn = get_connection()
    try:
        since = getattr(args, "since", None)
        category = getattr(args, "category", None)
        events = query_events(conn, since=since, category=category)
        _print_json(events)
    finally:
        conn.close()


def cmd_add_event(args: argparse.Namespace) -> None:
    """Add an event to the database."""
    conn = get_connection()
    try:
        event_id = add_event(
            conn,
            event_date=args.date,
            category=args.category,
            title=args.title,
            value=args.value,
            prior=args.prior,
            consensus=args.consensus,
            surprise=args.surprise,
            source_url=args.source_url,
            doc_ref=args.doc_ref,
        )
        print(f"Event added with id={event_id}")
    finally:
        conn.close()


def _series_health(conn, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Compute per-series freshness for every ACTIVE series.

    Uses the most-recent ingest result (success / no_new_data / error) as the
    authoritative signal, with a generous, frequency-aware date-age watch flag.
    Returns a list of health dicts consumable by health.build_report / render.
    """
    if today is None:
        today = date.today()

    try:
        grace_map = staleness_grace_map()
    except Exception:  # noqa: BLE001
        grace_map = {}

    out: List[Dict[str, Any]] = []
    for s in get_series(conn, status="active"):
        sid = s["series_id"]
        latest_date = get_latest_date(conn, sid, s["table_kind"])
        last_ingest = get_last_ingest(conn, sid)
        last_status = last_ingest["status"] if last_ingest else None
        served_by = last_ingest.get("served_by") if last_ingest else None
        primary_source = s["source"]
        status, reason = health.classify_series_freshness(
            frequency=s.get("frequency"),
            latest_date=latest_date,
            last_ingest_status=last_status,
            today=today,
            grace_days=grace_map.get(s["ticker"]),
        )
        out.append({
            "ticker": s["ticker"],
            "name": s["name"],
            "asset_class": s.get("asset_class"),
            "source": primary_source,
            "primary_source": primary_source,
            "served_by": served_by,
            "fell_back": bool(served_by and served_by != primary_source),
            "frequency": s.get("frequency") or "daily",
            "latest_date": latest_date,
            "status": status,
            "reason": reason,
        })
    return out


def cmd_doctor(args: argparse.Namespace) -> None:
    """
    Health check. Classifies each active series as ok / late / broken / no_data
    using the last fetch result + a calendar-aware freshness bound, and prints a
    compact JSON report. "needs_attention" lists only genuinely-broken series.
    """
    conn = get_connection()
    try:
        series_health = _series_health(conn)
        report = health.build_report(series_health)
        # Serialize latest_date in the attention/watch lists for JSON output.
        for key in ("attention_list", "watch_list"):
            for item in report[key]:
                ld = item.get("latest_date")
                item["latest_date"] = ld.isoformat() if hasattr(ld, "isoformat") else (str(ld) if ld else None)
        _print_json(report)
    finally:
        conn.close()


def cmd_status(args: argparse.Namespace) -> None:
    """Show series metadata + latest value for a ticker."""
    conn = get_connection()
    try:
        series_rows = get_series(conn, ticker=args.ticker, status="%")
        if not series_rows:
            print(f"Series not found: {args.ticker}", file=sys.stderr)
            sys.exit(1)
        
        s = series_rows[0]
        
        # Get latest value
        from summarize import _load_series_data
        ts = _load_series_data(conn, s)
        
        status_info = {
            "ticker": s["ticker"],
            "name": s["name"],
            "asset_class": s.get("asset_class"),
            "source": s["source"],
            "source_symbol": s["source_symbol"],
            "table_kind": s["table_kind"],
            "unit": s.get("unit"),
            "frequency": s.get("frequency", "daily"),
            "first_available": str(s.get("first_available")) if s.get("first_available") else None,
            "last_updated": str(s.get("last_updated")) if s.get("last_updated") else None,
            "status": s["status"],
            "data_points": len(ts),
        }
        
        if not ts.empty:
            status_info["latest_date"] = ts.index[-1].strftime("%Y-%m-%d") if hasattr(ts.index[-1], "strftime") else str(ts.index[-1])[:10]
            status_info["latest_value"] = round(float(ts.iloc[-1]), 4)
        
        if s.get("trigger_levels"):
            import json as _json
            try:
                status_info["trigger_levels"] = _json.loads(s["trigger_levels"]) if isinstance(s["trigger_levels"], str) else s["trigger_levels"]
            except (_json.JSONDecodeError, TypeError):
                pass
        
        _print_json(status_info)
    finally:
        conn.close()


def _export_parquet(conn) -> Path:
    """Write a multi-table Parquet snapshot under MARKET_DATA_DIR/exports.
    Returns the export directory. Raises on failure (caller decides what to do)."""
    export_dir = get_market_data_dir() / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    tables: Dict[str, pd.DataFrame] = {
        "series": pd.read_sql_query("SELECT * FROM series", conn),
        "ohlcv": pd.read_sql_query("SELECT * FROM ohlcv", conn),
        "observations": pd.read_sql_query("SELECT * FROM observations", conn),
        "events": pd.read_sql_query("SELECT * FROM events", conn),
        "ingest_runs": pd.read_sql_query("SELECT * FROM ingest_runs", conn),
    }

    # series doubles as the canonical single-file snapshot for quick restore.
    pq.write_table(pa.Table.from_pandas(tables["series"]),
                   export_dir / "market_snapshot.parquet", compression="snappy")
    for name, df in tables.items():
        pq.write_table(pa.Table.from_pandas(df),
                       export_dir / f"market_snapshot_{name}.parquet", compression="snappy")

    logger.info("Exported %d tables to %s", len(tables), export_dir)
    return export_dir


def cmd_export(args: argparse.Namespace) -> None:
    """Export all tables to a Parquet snapshot."""
    if hasattr(args, "format") and args.format and args.format != "parquet":
        print(f"Unsupported format: {args.format}. Only 'parquet' supported.", file=sys.stderr)
        sys.exit(1)
    conn = get_connection()
    try:
        export_dir = _export_parquet(conn)
        print(f"Exported to {export_dir}/market_snapshot_*.parquet")
    finally:
        conn.close()


def cmd_daily(args: argparse.Namespace) -> None:
    """
    One-shot daily routine — the single command a cron/agent should call.

    Robust and self-contained (no fragile shell glue):
      1. Update every active series, with per-series error + timeout isolation.
      2. Run the health check.
      3. Write a clean, trustworthy UPDATE_LOG.md.
      4. Export a Parquet snapshot (best-effort).
      5. Print a JSON summary (with a top-level `timestamp`).

    Exit code is 0 unless a series genuinely needs attention AND --strict is set.
    """
    conn = get_connection()
    try:
        active = get_series(conn, status="active")
        update_results = _update_series_list(
            conn, active, per_series_timeout=getattr(args, "per_series_timeout", None)
        )
        run_summary = {
            "updated": sum(1 for r in update_results if r["status"] == "success"),
            "current": sum(1 for r in update_results if r["status"] == "no_new_data"),
            "errors": sum(1 for r in update_results if r["status"] == "error"),
        }

        series_health = _series_health(conn)
        report = health.build_report(series_health)

        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        md = health.render_update_log(report, run_summary, series_health, ts)
        log_path = get_market_data_dir() / "UPDATE_LOG.md"
        log_path.write_text(md)

        export_error = None
        try:
            _export_parquet(conn)
        except Exception as exc:  # noqa: BLE001 — snapshot is best-effort
            export_error = str(exc)
            logger.error("Parquet export failed: %s", exc)

        summary = {
            "timestamp": ts,
            "run_summary": run_summary,
            "health": {k: report[k] for k in
                       ("total_active", "ok", "late", "broken", "no_data", "needs_attention")},
            "needs_attention": [
                {"ticker": s["ticker"], "source": s.get("source"), "reason": s["reason"]}
                for s in report["attention_list"]
            ],
            "update_log": str(log_path),
            "export_error": export_error,
        }
        _print_json(summary)

        if getattr(args, "strict", False) and report["needs_attention"] > 0:
            sys.exit(2)
    finally:
        conn.close()


def cmd_import(args: argparse.Namespace) -> None:
    """Import a Parquet snapshot into the database."""
    conn = get_connection()
    try:
        import_path = Path(args.from_path)
        
        if not import_path.exists():
            print(f"Import path not found: {import_path}", file=sys.stderr)
            sys.exit(1)
        
        # Determine if it's a directory of files or a single file
        if import_path.is_dir():
            parquet_files = list(import_path.glob("market_snapshot_*.parquet"))
        else:
            parquet_files = [import_path]
        
        total_rows = 0
        
        for pf in parquet_files:
            table_name = pf.stem.replace("market_snapshot_", "")
            if table_name not in {"series", "ohlcv", "observations", "events", "ingest_runs"}:
                logger.warning("Skipping unknown table: %s", table_name)
                continue
            
            df = pd.read_parquet(pf)
            
            if table_name == "series":
                for _, row in df.iterrows():
                    upsert_series(conn, row.to_dict())
            
            elif table_name == "ohlcv":
                for sid in df["series_id"].unique():
                    sub = df[df["series_id"] == sid]
                    upsert_ohlcv(conn, int(sid), sub)
            
            elif table_name == "observations":
                for sid in df["series_id"].unique():
                    sub = df[df["series_id"] == sid]
                    upsert_observations(conn, int(sid), sub)
            
            elif table_name == "events":
                for _, row in df.iterrows():
                    add_event(
                        conn,
                        event_date=row.get("date"),
                        category=row.get("category"),
                        title=row.get("title"),
                        value=row.get("value"),
                        prior=row.get("prior"),
                        consensus=row.get("consensus"),
                        surprise=row.get("surprise"),
                        source_url=row.get("source_url"),
                        doc_ref=row.get("doc_ref"),
                    )
            
            elif table_name == "ingest_runs":
                for _, row in df.iterrows():
                    conn.execute(
                        """INSERT OR REPLACE INTO ingest_runs
                           (run_id, series_id, ts, rows_added, from_date, to_date, status, error)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            row.get("run_id"), row.get("series_id"), row.get("ts"),
                            row.get("rows_added"), row.get("from_date"), row.get("to_date"),
                            row.get("status"), row.get("error"),
                        ),
                    )
                conn.commit()
            
            total_rows += len(df)
            logger.info("Imported %d rows into %s", len(df), table_name)
        
        print(f"Imported {total_rows} total rows from {import_path}")
    finally:
        conn.close()


# ─── source adapter dispatch (failover chain) ────────────────────────────────

def _source_available(source_name: str, sources_config: Dict[str, Any]) -> bool:
    """A source is usable iff its credential prerequisite is met.

    - auth_env is None/absent -> always available (keyless: yahoo_direct, yahoo,
      treasury, stooq).
    - auth_env set            -> available iff that env var is non-empty.
    - unknown source name     -> unavailable (skip, don't crash).

    This is what lets `eodhd` sit dormant in a chain until EODHD_API_KEY exists:
    with no key it is silently skipped; the day the key appears it activates with
    no catalog or code change.
    """
    sources = sources_config.get("sources", {})
    if source_name not in sources:
        return False
    auth_env = sources[source_name].get("auth_env")
    if not auth_env:
        return True
    return bool(os.getenv(auth_env))


def _normalize_kind(df: "pd.DataFrame", target_kind: str) -> "pd.DataFrame":
    """Coerce an adapter's frame to the series' canonical table_kind.

    - target 'ohlcv' but frame is observations (only 'value'): value -> close and
      adj_close; open/high/low/volume left absent (NaN on upsert).
    - target 'observations' but frame is ohlcv: adj_close (else close) -> value.
    - already-matching frames pass through untouched.
    Operates on a frame that still has 'date' as a column or the index.
    """
    if df is None or df.empty:
        return df
    cols = set(df.columns)
    if target_kind == "ohlcv" and "value" in cols and "close" not in cols:
        df = df.copy()
        df["close"] = df["value"]
        df["adj_close"] = df["value"]
        df = df.drop(columns=["value"])
    elif target_kind == "observations" and "value" not in cols:
        df = df.copy()
        src_col = "adj_close" if "adj_close" in cols else ("close" if "close" in cols else None)
        if src_col is None:
            return df.iloc[0:0]  # nothing usable -> empty, let failover continue
        df["value"] = df[src_col]
        keep = [c for c in ("date", "value") if c in df.columns]
        df = df[keep] if "date" in df.columns else df[["value"]]
    return df


def _resolve_chain(series_info: Dict[str, Any], catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the ordered source chain for this series.

    The chain lives in catalog.yaml, but the series dict handed to the fetcher
    comes from the DB (get_series) and only carries the legacy source/source_symbol.
    So prefer the catalog entry (matched by ticker); fall back to whatever the
    series_info itself declares (legacy single-source rows, and unit tests that
    pass an inline `sources` list).
    """
    from catalog import normalize_sources
    ticker = series_info.get("ticker")
    for ac_info in catalog.get("asset_classes", {}).values():
        if not isinstance(ac_info, dict):
            continue
        for cat_series in ac_info.get("series", []):
            if isinstance(cat_series, dict) and cat_series.get("ticker") == ticker:
                refs = normalize_sources(cat_series)
                if refs:
                    return refs
    return normalize_sources(series_info)


def _inject_eia_route(adapter_cfg: Dict[str, Any], catalog: Dict[str, Any],
                      series_info: Dict[str, Any]) -> None:
    for ac_info in catalog.get("asset_classes", {}).values():
        if not isinstance(ac_info, dict):
            continue
        for cat_series in ac_info.get("series", []):
            if isinstance(cat_series, dict) and cat_series.get("ticker") == series_info.get("ticker"):
                route = cat_series.get("eia_route")
                if route:
                    adapter_cfg["route"] = route
                return


def _fetch_with_failover(
    series_info: Dict[str, Any],
    sources_config: Dict[str, Any],
    catalog: Dict[str, Any],
    backfill: bool = True,
    since: Optional[date] = None,
) -> tuple:
    """Try each source in the series' chain until one returns non-empty data.

    Returns (DataFrame|None, from_date, to_date, served_by|None). Skips
    unavailable sources (missing credentials). Records provenance via served_by
    (the source that produced the rows). Only returns (None, ..., None) when
    EVERY source in the chain fails or empties.

    DataFrame (on success) has a 'date' column plus OHLCV or 'value' columns,
    normalized to the series' canonical table_kind.
    """
    from sources import get_adapter

    target_kind = series_info.get("table_kind", "observations")
    chain = _resolve_chain(series_info, catalog)  # catalog is source of truth

    backfill_years = catalog.get("defaults", {}).get("backfill_years", 30)
    if backfill and since is None:
        from_date = date.today() - timedelta(days=int(backfill_years * 365.25))
    elif since is not None:
        from_date = since
    else:
        from_date = date.today() - timedelta(days=7)
    to_date = date.today()
    start_str = from_date.strftime("%Y-%m-%d")
    end_str = to_date.strftime("%Y-%m-%d")

    last_error: Optional[str] = None
    any_reached = False  # did any source respond at all (even empty, no raise)?
    for ref in chain:
        source_name = ref["source"]
        if not _source_available(source_name, sources_config):
            logger.debug("Skipping unavailable source '%s' for %s",
                         source_name, series_info.get("ticker"))
            continue
        try:
            adapter_mod = get_adapter(source_name)
        except (ImportError, AttributeError) as exc:
            logger.warning("Adapter '%s' unavailable for %s: %s",
                           source_name, series_info.get("ticker"), exc)
            last_error = str(exc)
            continue

        source_cfg = sources_config.get("sources", {}).get(source_name, {})
        adapter_cfg = dict(source_cfg)
        adapter_cfg["series_info"] = series_info
        # The provider's NATIVE kind for THIS ref (so the adapter emits the right shape).
        adapter_cfg["table_kind"] = ref.get("kind") or target_kind
        for key in ("frequency", "unit"):
            if key in series_info and key not in adapter_cfg:
                adapter_cfg[key] = series_info[key]
        if source_name == "eia":
            _inject_eia_route(adapter_cfg, catalog, series_info)

        try:
            df = adapter_mod.fetch(ref["symbol"], start_str, end_str, adapter_cfg)
        except Exception as exc:  # noqa: BLE001 — try the next source
            logger.warning("Source '%s' fetch raised for %s (%s): %s",
                           source_name, series_info.get("ticker"), ref["symbol"], exc)
            last_error = str(exc)
            continue

        any_reached = True  # adapter responded without raising (even if empty)
        if df is None or df.empty:
            logger.info("Source '%s' returned no data for %s (%s); trying next",
                        source_name, series_info.get("ticker"), ref["symbol"])
            continue

        # Ensure a 'date' column (adapters may index by date).
        if df.index.name == "date" or (isinstance(df.index, pd.DatetimeIndex) and "date" not in df.columns):
            df = df.reset_index()
        if "date" not in df.columns and isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        df = _normalize_kind(df, target_kind)
        if df is None or df.empty:
            continue

        return df, from_date, to_date, source_name

    # Nothing served. If NO source was even reachable and something hard-errored,
    # raise so the outer handler logs it as 'error' (broken) — matches the old
    # single-source semantics. If at least one source was reached but returned
    # empty (e.g. genuinely no new data, or a soft 429), fall through to None so
    # the caller records 'no_new_data'.
    if not any_reached and last_error:
        raise RuntimeError(f"all sources unreachable: {last_error}")
    if last_error:
        logger.error("All sources failed for %s (last error: %s)",
                     series_info.get("ticker"), last_error)
    return None, from_date, to_date, None


# ─── helpers ─────────────────────────────────────────────────────────────────

def _resolve_series(conn, args) -> List[Dict[str, Any]]:
    """Resolve which series to operate on from CLI args."""
    if hasattr(args, "all") and args.all:
        return get_series(conn, status="active")
    
    if hasattr(args, "ticker") and args.ticker:
        tickers = _parse_tickers(args.ticker)
        result = []
        for t in tickers:
            rows = get_series(conn, ticker=t, status="%")
            result.extend(rows)
        return result
    
    if hasattr(args, "asset_class") and args.asset_class:
        return get_series(conn, asset_class=args.asset_class, status="active")
    
    return []


def _parse_tickers(raw: Optional[str]) -> List[str]:
    """Parse comma-separated ticker list."""
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _parse_windows(raw: Optional[str]) -> Optional[List[str]]:
    """Parse comma-separated window list."""
    if not raw:
        return None
    return [w.strip() for w in raw.split(",") if w.strip()]


def _filter_after(df: "pd.DataFrame", last_date_obj: date) -> "pd.DataFrame":
    """Keep only rows whose calendar date is strictly after last_date_obj.

    Robust under pandas 3.x: adapters may return tz-aware OR tz-naive 'date'
    columns, and comparing the two raises. We collapse both sides to tz-naive
    normalized calendar dates before comparing.
    """
    parsed = pd.to_datetime(df["date"], errors="coerce")
    tz = getattr(parsed.dt, "tz", None)
    if tz is not None:
        parsed = parsed.dt.tz_localize(None)
    cutoff = pd.Timestamp(last_date_obj).normalize()
    mask = parsed.dt.normalize() > cutoff
    return df[mask.fillna(False).values]


def _to_date_str(val) -> Optional[str]:
    """Convert a date-ish value to YYYY-MM-DD string."""
    if val is None:
        return None
    if isinstance(val, str):
        return val[:10]
    if isinstance(val, (date, datetime)):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, pd.Timestamp):
        return val.strftime("%Y-%m-%d")
    return str(val)[:10]


# ─── CLI definition ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="market_data",
        description="Market Data CLI — query, backfill, and manage local market-data store",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    
    sub = parser.add_subparsers(dest="command", help="Available commands")
    
    # init
    p_init = sub.add_parser("init", help="Initialize the database from schema.sql")
    p_init.add_argument("--schema", help="Path to schema.sql (default: MARKET_DATA_DIR/db/schema.sql)")
    
    # sync-catalog
    p_sync = sub.add_parser("sync-catalog", help="Sync catalog.yaml with series table")
    
    # backfill
    p_bf = sub.add_parser("backfill", help="Backfill historical data")
    p_bf.add_argument("--ticker", help="Comma-separated tickers")
    p_bf.add_argument("--asset-class", help="Asset class group name")
    p_bf.add_argument("--all", action="store_true", help="Backfill all active series")
    
    # update
    p_up = sub.add_parser("update", help="Incremental update from last_updated to today")
    p_up.add_argument("--ticker", help="Comma-separated tickers")
    p_up.add_argument("--asset-class", help="Asset class group name")
    p_up.add_argument("--all", action="store_true", help="Update all active series")
    p_up.add_argument("--per-series-timeout", type=int, dest="per_series_timeout",
                      help="Hard timeout (seconds) per series; default env MARKET_DATA_SERIES_TIMEOUT or 60")

    # daily (the one-shot cron/agent routine)
    p_daily = sub.add_parser(
        "daily",
        help="Update all active series, write UPDATE_LOG.md, export snapshot, print summary",
    )
    p_daily.add_argument("--per-series-timeout", type=int, dest="per_series_timeout",
                         help="Hard timeout (seconds) per series; default 60")
    p_daily.add_argument("--strict", action="store_true",
                         help="Exit non-zero (2) if any series needs attention")
    
    # query (with sub-subcommands)
    p_query = sub.add_parser("query", help="Query the database")
    q_sub = p_query.add_subparsers(dest="query_subcommand", help="Query type")
    
    # query latest
    q_latest = q_sub.add_parser("latest", help="Get latest values")
    q_latest.add_argument("--tickers", required=True, help="Comma-separated tickers")
    
    # query stats
    q_stats = q_sub.add_parser("stats", help="Full statistical context")
    q_stats.add_argument("--ticker", required=True, help="Ticker symbol")
    q_stats.add_argument("--windows", default="1d,1w,1m,3m,1y,5y",
                          help="Comma-separated windows (default: 1d,1w,1m,3m,1y,5y)")
    
    # query ratio
    q_ratio = q_sub.add_parser("ratio", help="Cross-asset ratio")
    q_ratio.add_argument("--num", required=True, help="Numerator ticker")
    q_ratio.add_argument("--den", required=True, help="Denominator ticker")
    q_ratio.add_argument("--windows", default="1d,1w,1m,3m,1y,5y",
                          help="Comma-separated windows")

    # query spread (a - b; e.g. 2Y - Fed Funds)
    q_spread = q_sub.add_parser("spread", help="Difference between two series (a - b)")
    q_spread.add_argument("--a", required=True, help="First ticker (minuend)")
    q_spread.add_argument("--b", required=True, help="Second ticker (subtrahend)")
    q_spread.add_argument("--windows", default="1d,1w,1m,3m,1y,5y",
                          help="Comma-separated windows")
    
    # query series
    q_series = q_sub.add_parser("series", help="Bounded data slice")
    q_series.add_argument("--ticker", required=True, help="Ticker symbol")
    q_series.add_argument("--since", help="Start date (YYYY-MM-DD)")
    q_series.add_argument("--until", help="End date (YYYY-MM-DD)")
    q_series.add_argument("--resample", help="Resample: weekly, monthly, quarterly")
    
    # query dashboard
    q_dash = q_sub.add_parser("dashboard", help="Stats for all series in groups")
    q_dash.add_argument("--group", required=True,
                        help="Comma-separated asset class groups")
    q_dash.add_argument("--windows", default="1d,1w,1m,3m,1y,5y",
                         help="Comma-separated windows")
    
    # query-events
    p_qev = sub.add_parser("query-events", help="Query events")
    p_qev.add_argument("--since", help="Start date (YYYY-MM-DD)")
    p_qev.add_argument("--category", help="Comma-separated categories")
    
    # add-event
    p_aev = sub.add_parser("add-event", help="Add a macro event")
    p_aev.add_argument("--date", required=True, help="Event date (YYYY-MM-DD)")
    p_aev.add_argument("--category", required=True, help="Event category")
    p_aev.add_argument("--title", required=True, help="Event title")
    p_aev.add_argument("--value", type=float, help="Actual value")
    p_aev.add_argument("--prior", type=float, help="Prior value")
    p_aev.add_argument("--consensus", type=float, help="Consensus forecast")
    p_aev.add_argument("--surprise", type=float, help="Surprise (actual - consensus)")
    p_aev.add_argument("--source-url", help="Source URL")
    p_aev.add_argument("--doc-ref", help="Document reference")
    
    # doctor
    sub.add_parser("doctor", help="Health check on all active series")
    
    # status
    p_status = sub.add_parser("status", help="Show series metadata + latest value")
    p_status.add_argument("--ticker", required=True, help="Ticker symbol")
    
    # export
    p_export = sub.add_parser("export", help="Export DB to Parquet snapshot")
    p_export.add_argument("--format", default="parquet", help="Export format (default: parquet)")
    
    # import
    p_import = sub.add_parser("import", help="Import Parquet snapshot into DB")
    p_import.add_argument("--from", dest="from_path", required=True,
                           help="Path to parquet file or directory")
    
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    
    _setup_logging(verbose=args.verbose if hasattr(args, "verbose") else False)
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    command_map = {
        "init": cmd_init,
        "sync-catalog": cmd_sync_catalog,
        "backfill": cmd_backfill,
        "update": cmd_update,
        "daily": cmd_daily,
        "query": cmd_query,
        "query-events": cmd_query_events,
        "add-event": cmd_add_event,
        "doctor": cmd_doctor,
        "status": cmd_status,
        "export": cmd_export,
        "import": cmd_import,
    }
    
    handler = command_map.get(args.command)
    if not handler:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)

    import sqlite3
    try:
        handler(args)
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            print(
                f"Error: the market-data DB is not initialized at {get_db_path()}.\n"
                "Run:  python3 market_data.py init  &&  python3 market_data.py sync-catalog\n"
                "(then `backfill --all`), or set MARKET_DATA_DIR to the right location.",
                file=sys.stderr,
            )
            sys.exit(1)
        raise
    except FileNotFoundError as exc:
        print(f"Error: required config/file missing — {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
