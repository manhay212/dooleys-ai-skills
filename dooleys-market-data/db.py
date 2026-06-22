"""
Database layer for dooleys-market-data.
Handles SQLite connections, schema init, and all CRUD operations.
"""

import os
import sqlite3
import logging
from pathlib import Path
from datetime import date, datetime
from typing import Optional, List, Dict, Any, Union

import pandas as pd

logger = logging.getLogger(__name__)


def get_market_data_dir() -> Path:
    """Return MARKET_DATA_DIR from env, defaulting to ~/.hermes-backup-repo/market-data."""
    env_val = os.getenv("MARKET_DATA_DIR")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return Path.home() / ".hermes-backup-repo" / "market-data"


def get_db_path() -> Path:
    """Return the path to the SQLite database file."""
    return get_market_data_dir() / "db" / "market.db"


def init_db(db_path: Path, schema_path: Optional[Path] = None) -> None:
    """
    Read schema.sql and execute all statements to create the database.
    
    Args:
        db_path: Path to the SQLite database file.
        schema_path: Path to schema.sql. If None, defaults to
                     MARKET_DATA_DIR/db/schema.sql.
    """
    if schema_path is None:
        schema_path = get_market_data_dir() / "db" / "schema.sql"
    
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    schema_sql = schema_path.read_text()
    
    conn = sqlite3.connect(str(db_path))
    try:
        # Execute each statement (split on semicolons, skip empty)
        statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
        for stmt in statements:
            if stmt:
                conn.execute(stmt)
        conn.commit()
        logger.info("Database initialized at %s", db_path)
    finally:
        conn.close()


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Open a SQLite connection with WAL mode and row_factory = sqlite3.Row.
    
    Args:
        db_path: Path to the database. If None, uses get_db_path().
    
    Returns:
        sqlite3.Connection
    """
    if db_path is None:
        db_path = get_db_path()
    
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)


def upsert_ohlcv(conn: sqlite3.Connection, series_id: int, df: pd.DataFrame) -> int:
    """
    UPSERT OHLCV data. DataFrame must have columns:
    date, open, high, low, close, adj_close, volume.
    
    Returns number of rows upserted.
    """
    required = {"date", "open", "high", "low", "close", "adj_close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")
    
    rows_upserted = 0
    cur = conn.cursor()
    for _, row in df.iterrows():
        cur.execute(
            """
            INSERT OR REPLACE INTO ohlcv
                (series_id, date, open, high, low, close, adj_close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                series_id,
                _to_date_str(row["date"]),
                _safe_float(row["open"]),
                _safe_float(row["high"]),
                _safe_float(row["low"]),
                _safe_float(row["close"]),
                _safe_float(row["adj_close"]),
                _safe_float(row["volume"]),
            ),
        )
        rows_upserted += 1
    conn.commit()
    return rows_upserted


def upsert_observations(conn: sqlite3.Connection, series_id: int, df: pd.DataFrame) -> int:
    """
    UPSERT observation data. DataFrame must have columns: date, value.
    
    Returns number of rows upserted.
    """
    required = {"date", "value"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")
    
    rows_upserted = 0
    cur = conn.cursor()
    for _, row in df.iterrows():
        cur.execute(
            """
            INSERT OR REPLACE INTO observations (series_id, date, value)
            VALUES (?, ?, ?)
            """,
            (series_id, _to_date_str(row["date"]), _safe_float(row["value"])),
        )
        rows_upserted += 1
    conn.commit()
    return rows_upserted


def get_series(
    conn: sqlite3.Connection,
    ticker: Optional[str] = None,
    series_id: Optional[int] = None,
    asset_class: Optional[str] = None,
    status: str = "active",
) -> List[Dict[str, Any]]:
    """
    Query series from the registry.
    
    Args:
        conn: Database connection.
        ticker: Filter by ticker (exact match).
        series_id: Filter by series_id.
        asset_class: Filter by asset_class.
        status: Filter by status. Default 'active'. Use '%' for all.
    
    Returns:
        List of dicts representing series rows.
    """
    query = "SELECT * FROM series WHERE 1=1"
    params: List[Any] = []
    
    if ticker is not None:
        query += " AND ticker = ?"
        params.append(ticker)
    if series_id is not None:
        query += " AND series_id = ?"
        params.append(series_id)
    if asset_class is not None:
        query += " AND asset_class = ?"
        params.append(asset_class)
    if status != "%":
        query += " AND status = ?"
        params.append(status)
    
    query += " ORDER BY asset_class, ticker"
    
    cur = conn.execute(query, params)
    return [_row_to_dict(row) for row in cur.fetchall()]


def upsert_series(conn: sqlite3.Connection, series_dict: Dict[str, Any]) -> int:
    """
    INSERT OR REPLACE a series row. The dict keys must match the `series` table columns.
    
    If series_id is provided and exists, it replaces that row.
    If ticker matches an existing row, the existing series_id is reused.
    
    Returns the series_id.
    """
    # If ticker already exists, carry over the series_id
    ticker = series_dict.get("ticker")
    if ticker:
        existing = conn.execute(
            "SELECT series_id FROM series WHERE ticker = ?", (ticker,)
        ).fetchone()
        if existing and "series_id" not in series_dict:
            series_dict["series_id"] = existing["series_id"]
    
    columns = [
        "series_id", "ticker", "name", "asset_class", "subclass",
        "source", "source_symbol", "unit", "frequency", "table_kind",
        "first_available", "last_updated", "status", "trigger_levels", "notes",
    ]
    
    # Build INSERT OR REPLACE
    present_cols = [c for c in columns if c in series_dict]
    placeholders = ", ".join(["?" for _ in present_cols])
    col_names = ", ".join(present_cols)
    values = [series_dict[c] for c in present_cols]
    
    # Handle trigger_levels as JSON string
    if "trigger_levels" in series_dict and isinstance(series_dict["trigger_levels"], dict):
        import json
        idx = present_cols.index("trigger_levels")
        values[idx] = json.dumps(series_dict["trigger_levels"])
    
    cur = conn.execute(
        f"INSERT OR REPLACE INTO series ({col_names}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    return cur.lastrowid or 0


def log_ingest(
    conn: sqlite3.Connection,
    series_id: int,
    rows_added: int,
    from_date: Optional[Union[str, date]] = None,
    to_date: Optional[Union[str, date]] = None,
    status: str = "success",
    error: Optional[str] = None,
) -> int:
    """
    Log an ingest run. Returns the run_id.
    """
    ts = datetime.utcnow().isoformat() + "Z"
    cur = conn.execute(
        """
        INSERT INTO ingest_runs (series_id, ts, rows_added, from_date, to_date, status, error)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            series_id,
            ts,
            rows_added,
            _to_date_str(from_date) if from_date else None,
            _to_date_str(to_date) if to_date else None,
            status,
            error,
        ),
    )
    conn.commit()
    return cur.lastrowid or 0


def get_last_ingest(
    conn: sqlite3.Connection, series_id: int
) -> Optional[Dict[str, Any]]:
    """
    Return the most recent ingest_runs row for a series as a dict
    {status, ts, rows_added, error}, or None if the series has no ingest history.

    This is the authoritative "did our last fetch reach the source?" signal used
    by the health/doctor logic — far more reliable than days-since-latest-data.
    """
    row = conn.execute(
        "SELECT status, ts, rows_added, error FROM ingest_runs "
        "WHERE series_id = ? ORDER BY run_id DESC LIMIT 1",
        (series_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def get_latest_date(
    conn: sqlite3.Connection, series_id: int, table_kind: str
) -> Optional[date]:
    """
    Return the latest date for a series, or None if no data.
    
    Args:
        conn: Database connection.
        series_id: The series ID.
        table_kind: 'ohlcv' or 'observations'.
    """
    if table_kind == "observations":
        row = conn.execute(
            "SELECT MAX(date) AS max_date FROM observations WHERE series_id = ?",
            (series_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT MAX(date) AS max_date FROM ohlcv WHERE series_id = ?",
            (series_id,),
        ).fetchone()
    
    if row and row["max_date"]:
        return _parse_date(row["max_date"])
    return None


def query_ohlcv(
    conn: sqlite3.Connection,
    series_id: int,
    since: Optional[Union[str, date]] = None,
    until: Optional[Union[str, date]] = None,
) -> pd.DataFrame:
    """
    Query OHLCV data for a series. Returns DataFrame with columns:
    date, open, high, low, close, adj_close, volume.
    """
    query = """
        SELECT date, open, high, low, close, adj_close, volume
        FROM ohlcv
        WHERE series_id = ?
    """
    params: List[Any] = [series_id]
    
    if since is not None:
        query += " AND date >= ?"
        params.append(_to_date_str(since))
    if until is not None:
        query += " AND date <= ?"
        params.append(_to_date_str(until))
    
    query += " ORDER BY date ASC"
    
    df = pd.read_sql_query(query, conn, params=params)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
    return df


def query_observations(
    conn: sqlite3.Connection,
    series_id: int,
    since: Optional[Union[str, date]] = None,
    until: Optional[Union[str, date]] = None,
) -> pd.DataFrame:
    """
    Query observation data for a series. Returns DataFrame with columns: date, value.
    """
    query = """
        SELECT date, value
        FROM observations
        WHERE series_id = ?
    """
    params: List[Any] = [series_id]
    
    if since is not None:
        query += " AND date >= ?"
        params.append(_to_date_str(since))
    if until is not None:
        query += " AND date <= ?"
        params.append(_to_date_str(until))
    
    query += " ORDER BY date ASC"
    
    df = pd.read_sql_query(query, conn, params=params)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
    return df


def add_event(
    conn: sqlite3.Connection,
    event_date: Union[str, date],
    category: str,
    title: str,
    value: Optional[float] = None,
    prior: Optional[float] = None,
    consensus: Optional[float] = None,
    surprise: Optional[float] = None,
    source_url: Optional[str] = None,
    doc_ref: Optional[str] = None,
    notes: Optional[str] = None,
) -> int:
    """Insert an event and return its event_id."""
    cur = conn.execute(
        """
        INSERT INTO events (date, category, title, value, prior, consensus, surprise,
                            source_url, doc_ref, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _to_date_str(event_date),
            category,
            title,
            value,
            prior,
            consensus,
            surprise,
            source_url,
            doc_ref,
            notes,
        ),
    )
    conn.commit()
    return cur.lastrowid or 0


def query_events(
    conn: sqlite3.Connection,
    since: Optional[Union[str, date]] = None,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query events, optionally filtered by since date and/or category."""
    query = "SELECT * FROM events WHERE 1=1"
    params: List[Any] = []
    
    if since is not None:
        query += " AND date >= ?"
        params.append(_to_date_str(since))
    if category is not None:
        # Support comma-separated categories
        cats = [c.strip() for c in category.split(",") if c.strip()]
        placeholders = ", ".join(["?" for _ in cats])
        query += f" AND category IN ({placeholders})"
        params.extend(cats)
    
    query += " ORDER BY date DESC"
    
    cur = conn.execute(query, params)
    return [_row_to_dict(row) for row in cur.fetchall()]


def update_series_last_updated(
    conn: sqlite3.Connection, series_id: int, date_val: Union[str, date]
) -> None:
    """Update the last_updated field for a series."""
    conn.execute(
        "UPDATE series SET last_updated = ? WHERE series_id = ?",
        (_to_date_str(date_val), series_id),
    )
    conn.commit()


def update_series_status(
    conn: sqlite3.Connection, series_id: int, status: str
) -> None:
    """Update the status field for a series."""
    conn.execute(
        "UPDATE series SET status = ? WHERE series_id = ?",
        (status, series_id),
    )
    conn.commit()


# ── helpers ──────────────────────────────────────────────────────────────────

def _to_date_str(val: Union[str, date, datetime, pd.Timestamp, None]) -> Optional[str]:
    """Convert various date-like types to YYYY-MM-DD string."""
    if val is None:
        return None
    if isinstance(val, str):
        return val[:10]  # Handle ISO format strings
    if isinstance(val, (date, datetime)):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, pd.Timestamp):
        return val.strftime("%Y-%m-%d")
    return str(val)[:10]


def _parse_date(val: Optional[str]) -> Optional[date]:
    """Parse a YYYY-MM-DD string to a date object."""
    if val is None:
        return None
    return datetime.strptime(val[:10], "%Y-%m-%d").date()


def _safe_float(val: Any) -> Optional[float]:
    """Convert a value to float, returning None for NaN/inf/null."""
    if val is None:
        return None
    try:
        f = float(val)
        if pd.isna(f) or f in (float("inf"), float("-inf")):
            return None
        return f
    except (ValueError, TypeError):
        return None
