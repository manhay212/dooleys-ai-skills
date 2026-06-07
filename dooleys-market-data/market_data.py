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
    get_latest_date, log_ingest, query_ohlcv, query_observations,
    add_event, query_events, update_series_last_updated,
)
from catalog import load_catalog, load_sources, sync_catalog
from summarize import (
    stats, latest, ratio, dashboard, query_series_data,
)

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
            source_name = s["source"]
            
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
            
            # Fetch data from source adapter
            source_cfg = sources_config.get("sources", {}).get(source_name, {})
            rate_limit = source_cfg.get("rate_limit_per_min", 60)
            
            try:
                df, from_date, to_date = _fetch_from_source(
                    source_name, s, source_cfg, catalog, backfill=True
                )
                
                if df is None or df.empty:
                    results.append({
                        "ticker": ticker, "status": "empty",
                        "reason": "No data returned from source",
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
                run_id = log_ingest(conn, sid, rows, from_date, to_date, "success")
                
                logger.info("Backfilled %s: %d rows, %s to %s (run %d)",
                            ticker, rows, _to_date_str(from_date) if from_date else "?",
                            _to_date_str(to_date) if to_date else "?", run_id)
                
                results.append({
                    "ticker": ticker, "status": "success",
                    "rows_added": rows,
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
            
            # Rate-limit sleep
            sleep_sec = 60.0 / rate_limit if rate_limit > 0 else 1.0
            time.sleep(sleep_sec)
        
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
        
        sources_config = load_sources()
        catalog = load_catalog()
        
        results = []
        for s in series_list:
            ticker = s["ticker"]
            sid = s["series_id"]
            table_kind = s["table_kind"]
            source_name = s["source"]
            
            # Get last_updated — incremental from there
            last_date = s.get("last_updated")
            if last_date:
                last_date_obj = _parse_date_arg(str(last_date)[:10]) if last_date else None
            else:
                last_date_obj = None
            
            source_cfg = sources_config.get("sources", {}).get(source_name, {})
            rate_limit = source_cfg.get("rate_limit_per_min", 60)
            
            try:
                df, from_date, to_date = _fetch_from_source(
                    source_name, s, source_cfg, catalog,
                    backfill=False, since=last_date_obj,
                )
                
                if df is None or df.empty:
                    results.append({
                        "ticker": ticker, "status": "no_new_data",
                        "reason": "No new data available",
                    })
                    continue
                
                # Only insert rows newer than last_updated
                if last_date_obj:
                    df["_date_parsed"] = pd.to_datetime(df["date"])
                    df = df[df["_date_parsed"] > pd.Timestamp(last_date_obj)]
                    df = df.drop(columns=["_date_parsed"])
                
                if df.empty:
                    results.append({
                        "ticker": ticker, "status": "no_new_data",
                    })
                    continue
                
                if table_kind == "ohlcv":
                    rows = upsert_ohlcv(conn, sid, df)
                else:
                    rows = upsert_observations(conn, sid, df)
                
                max_date = df["date"].max()
                update_series_last_updated(conn, sid, max_date)
                
                run_id = log_ingest(conn, sid, rows, from_date, to_date, "success")
                
                results.append({
                    "ticker": ticker, "status": "success",
                    "rows_added": rows,
                    "from_date": _to_date_str(from_date),
                    "to_date": _to_date_str(to_date),
                    "run_id": run_id,
                })
                
            except Exception as exc:
                logger.error("Failed to update %s: %s", ticker, exc)
                log_ingest(conn, sid, 0, None, None, "error", str(exc))
                results.append({
                    "ticker": ticker, "status": "error", "error": str(exc),
                })
            
            time.sleep(60.0 / rate_limit if rate_limit > 0 else 1.0)
        
        _print_json({"update_results": results})
    finally:
        conn.close()


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


def cmd_doctor(args: argparse.Namespace) -> None:
    """
    Health check: for each active series, check freshness, gaps, source health.
    Prints a report.
    """
    conn = get_connection()
    try:
        all_series = get_series(conn, status="%")
        active = [s for s in all_series if s["status"] == "active"]
        
        issues: List[Dict[str, Any]] = []
        healthy = 0
        
        for s in active:
            ticker = s["ticker"]
            sid = s["series_id"]
            frequency = s.get("frequency") or "daily"
            table_kind = s["table_kind"]
            
            latest_date = get_latest_date(conn, sid, table_kind)
            last_updated = s.get("last_updated")
            
            series_issues = []
            
            # Check freshness
            if latest_date:
                expected_max_age = {
                    "daily": 2,
                    "weekly": 8,
                    "monthly": 35,
                }.get(frequency, 2)
                
                age = (date.today() - latest_date).days
                if age > expected_max_age:
                    series_issues.append(f"Stale: last data {latest_date} ({age}d ago, expected <={expected_max_age}d)")
            else:
                series_issues.append("No data in database")
            
            # Check if last_updated is set
            if not last_updated:
                series_issues.append("last_updated not set")
            
            if series_issues:
                issues.append({
                    "ticker": ticker,
                    "name": s["name"],
                    "asset_class": s.get("asset_class"),
                    "source": s["source"],
                    "issues": series_issues,
                })
            else:
                healthy += 1
        
        report = {
            "total_series": len(all_series),
            "active": len(active),
            "healthy": healthy,
            "with_issues": len(issues),
            "issues": issues,
        }
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


def cmd_export(args: argparse.Namespace) -> None:
    """Export all tables to a Parquet snapshot."""
    conn = get_connection()
    try:
        export_dir = get_market_data_dir() / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        
        export_path = export_dir / "market_snapshot.parquet"
        
        if hasattr(args, "format") and args.format:
            fmt = args.format
            if fmt != "parquet":
                print(f"Unsupported format: {fmt}. Only 'parquet' supported.", file=sys.stderr)
                sys.exit(1)
        
        # Read all tables
        tables: Dict[str, pd.DataFrame] = {}
        
        tables["series"] = pd.read_sql_query("SELECT * FROM series", conn)
        tables["ohlcv"] = pd.read_sql_query("SELECT * FROM ohlcv", conn)
        tables["observations"] = pd.read_sql_query("SELECT * FROM observations", conn)
        tables["events"] = pd.read_sql_query("SELECT * FROM events", conn)
        tables["ingest_runs"] = pd.read_sql_query("SELECT * FROM ingest_runs", conn)
        
        # Write to Parquet with multiple tables (using directories)
        table = pa.Table.from_pandas(tables["series"])
        pq.write_table(table, export_path, compression="snappy")
        
        # For multi-table export, use a partitioned approach
        for name, df in tables.items():
            tbl_path = export_dir / f"market_snapshot_{name}.parquet"
            tbl = pa.Table.from_pandas(df)
            pq.write_table(tbl, tbl_path, compression="snappy")
        
        logger.info("Exported %d tables to %s", len(tables), export_dir)
        print(f"Exported to {export_dir}/market_snapshot_*.parquet")
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


# ─── source adapter dispatch ─────────────────────────────────────────────────

def _fetch_from_source(
    source_name: str,
    series_info: Dict[str, Any],
    source_cfg: Dict[str, Any],
    catalog: Dict[str, Any],
    backfill: bool = True,
    since: Optional[date] = None,
) -> tuple:
    """
    Dispatch to the appropriate source adapter to fetch data.
    
    Returns (DataFrame, from_date, to_date).
    DataFrame has a 'date' column and OHLCV columns or 'value' column.
    Returns (None, since, to_date) if adapter is unavailable or returns no data.
    
    Uses the adapter registry in sources/__init__.py.
    Each adapter exposes a fetch(source_symbol, start, end, cfg) function
    that returns a pd.DataFrame indexed by date.
    """
    from sources import get_adapter
    
    source_symbol = series_info["source_symbol"]
    
    # Default lookback
    backfill_years = catalog.get("defaults", {}).get("backfill_years", 30)
    sources_cfg = catalog.get("sources", {})
    
    # Compute date range
    if backfill and since is None:
        from_date = date.today() - timedelta(days=int(backfill_years * 365.25))
    elif since is not None:
        from_date = since
    else:
        from_date = date.today() - timedelta(days=7)
    
    to_date = date.today()
    
    start_str = from_date.strftime("%Y-%m-%d") if from_date else None
    end_str = to_date.strftime("%Y-%m-%d") if to_date else None
    
    try:
        adapter_mod = get_adapter(source_name)
    except (ImportError, AttributeError) as exc:
        logger.warning(
            "Cannot load adapter for source '%s': %s. Skipping %s.",
            source_name, exc, series_info["ticker"],
        )
        return None, from_date, to_date
    
    # Build adapter config: merge source config with extra series fields
    adapter_cfg = dict(source_cfg)
    adapter_cfg["series_info"] = series_info
    
    try:
        df = adapter_mod.fetch(source_symbol, start_str, end_str, adapter_cfg)
    except Exception as exc:
        logger.error("Adapter '%s' fetch failed for %s: %s", source_name, source_symbol, exc)
        raise
    
    if df is None or df.empty:
        return None, from_date, to_date
    
    # Ensure DataFrame has a 'date' column
    if df.index.name == "date" or (isinstance(df.index, pd.DatetimeIndex) and "date" not in df.columns):
        df = df.reset_index()
    if "date" not in df.columns and isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
    
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    
    return df, from_date, to_date


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
        "query": cmd_query,
        "query-events": cmd_query_events,
        "add-event": cmd_add_event,
        "doctor": cmd_doctor,
        "status": cmd_status,
        "export": cmd_export,
        "import": cmd_import,
    }
    
    handler = command_map.get(args.command)
    if handler:
        handler(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
