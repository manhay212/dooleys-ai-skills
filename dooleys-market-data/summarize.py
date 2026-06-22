"""
Analytics layer for dooleys-market-data.
Computes statistics, ratios, dashboards from the local SQLite database.
All functions return JSON-serializable dicts.
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Any, Optional, Union

import pandas as pd
import numpy as np

from db import (
    get_connection, get_series, query_ohlcv, query_observations,
    get_latest_date,
)

logger = logging.getLogger(__name__)

# Standard analysis windows
DEFAULT_WINDOWS = ["1d", "1w", "1m", "3m", "1y", "5y"]

_WINDOW_DAYS: Dict[str, int] = {
    "1d": 1,
    "1w": 7,
    "2w": 14,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
}


def _resolve_window_days(window: str) -> int:
    """Convert a window label like '1w' to number of days."""
    if window in _WINDOW_DAYS:
        return _WINDOW_DAYS[window]
    # Try to parse like '30d'
    if window.endswith("d"):
        try:
            return int(window[:-1])
        except ValueError:
            pass
    raise ValueError(f"Unknown window: {window}")


def _load_series_data(
    conn: "sqlite3.Connection",  # type: ignore[name-defined] # noqa: F821
    series_row: Dict[str, Any],
) -> pd.Series:
    """
    Load the full time series for a given series row.
    Returns a pandas Series with datetime index and numeric values.
    For ohlcv, uses adj_close (falling back to close).
    For observations, uses value.
    """
    sid = series_row["series_id"]
    table_kind = series_row["table_kind"]
    
    if table_kind == "ohlcv":
        df = query_ohlcv(conn, sid)
        if df.empty:
            return pd.Series(dtype=float)
        # Use adj_close if available, fall back to close
        if "adj_close" in df.columns and df["adj_close"].notna().any():
            series = df.set_index("date")["adj_close"]
        else:
            series = df.set_index("date")["close"]
    else:
        df = query_observations(conn, sid)
        if df.empty:
            return pd.Series(dtype=float)
        series = df.set_index("date")["value"]
    
    # Drop NaN values
    series = series.dropna()
    series = series.sort_index()
    return series


def _parse_trigger_levels(trigger_levels_raw: Any) -> Dict[str, float]:
    """Parse trigger_levels from JSON string or dict."""
    if trigger_levels_raw is None:
        return {}
    if isinstance(trigger_levels_raw, dict):
        return {k: float(v) for k, v in trigger_levels_raw.items()}
    if isinstance(trigger_levels_raw, str):
        try:
            parsed = json.loads(trigger_levels_raw)
            return {k: float(v) for k, v in parsed.items()}
        except (json.JSONDecodeError, ValueError, TypeError):
            return {}
    return {}


def _compute_change(series: pd.Series, window: str) -> Optional[float]:
    """
    Compute percentage change over a window.
    Returns None if insufficient data.
    """
    days = _resolve_window_days(window)
    if len(series) < 2:
        return None
    
    cutoff = series.index[-1] - pd.Timedelta(days=days)
    past_vals = series[series.index <= cutoff]
    
    if past_vals.empty:
        # Try the earliest available value
        past_val = series.iloc[0]
    else:
        past_val = past_vals.iloc[-1]
    
    latest = series.iloc[-1]
    
    if past_val == 0 or pd.isna(past_val) or pd.isna(latest):
        return None
    
    return round(float((latest - past_val) / abs(past_val) * 100), 4)


def _nearest_trigger(
    latest: float, trigger_levels: Dict[str, float]
) -> Optional[Dict[str, Any]]:
    """
    Find the nearest trigger level and compute distance-to-trigger.
    Returns None if no trigger levels defined.
    """
    if not trigger_levels:
        return None
    
    # Find the trigger level closest to latest value
    nearest_name = None
    nearest_level = None
    nearest_dist = float("inf")
    
    for name, level in trigger_levels.items():
        dist = abs(latest - level)
        if dist < nearest_dist:
            nearest_dist = dist
            nearest_name = name
            nearest_level = level
    
    if nearest_name is None:
        return None
    
    # Compute distance as percentage
    try:
        distance_pct = round(float((latest - nearest_level) / abs(nearest_level) * 100), 4)
    except (ZeroDivisionError, TypeError):
        distance_pct = None
    
    # Determine direction
    direction = "above" if latest > nearest_level else ("below" if latest < nearest_level else "at")
    
    return {
        "trigger": nearest_name,
        "level": round(nearest_level, 4),
        "distance_pct": distance_pct,
        "direction": direction,
    }


def stats(
    conn: "sqlite3.Connection",  # type: ignore[name-defined] # noqa: F821
    ticker: str,
    windows: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compute full statistical context for a series.
    
    Returns a dict with:
        ticker, name, latest_date, latest_value, unit,
        changes: {window: pct_change},
        range_52w: {high, low, high_date, low_date, pct_from_high, pct_from_low},
        full_range: {min, max, min_date, max_date},
        percentile: percentile rank of latest vs full history,
        z_score: z-score of latest,
        rolling_20d_vol: rolling 20-day annualized volatility,
        nearest_trigger: {trigger, level, distance_pct, direction},
        data_points: count of observations,
        error: (only if series has no data)
    """
    if windows is None:
        windows = DEFAULT_WINDOWS
    
    # Get series metadata
    series_rows = get_series(conn, ticker=ticker, status="%")
    if not series_rows:
        return {"ticker": ticker, "error": "Series not found in database"}
    
    series_row = series_rows[0]
    
    # Load data
    ts = _load_series_data(conn, series_row)
    
    if ts.empty:
        return {
            "ticker": ticker,
            "name": series_row["name"],
            "error": "No data available for this series",
        }
    
    latest_date = ts.index[-1]
    latest_val = round(float(ts.iloc[-1]), 4)
    
    result: Dict[str, Any] = {
        "ticker": ticker,
        "name": series_row["name"],
        "asset_class": series_row.get("asset_class"),
        "unit": series_row.get("unit"),
        "frequency": series_row.get("frequency", "daily"),
        "latest_date": latest_date.strftime("%Y-%m-%d") if hasattr(latest_date, "strftime") else str(latest_date)[:10],
        "latest_value": latest_val,
        "data_points": len(ts),
    }
    
    # Changes per window
    changes: Dict[str, Optional[float]] = {}
    for window in windows:
        changes[window] = _compute_change(ts, window)
    result["changes"] = changes
    
    # 52-week range
    one_year_ago = ts.index[-1] - pd.Timedelta(days=365)
    ts_52w = ts[ts.index >= one_year_ago]
    if len(ts_52w) >= 2:
        high_52w = float(ts_52w.max())
        low_52w = float(ts_52w.min())
        high_date = ts_52w.idxmax()
        low_date = ts_52w.idxmin()
        try:
            pct_from_high = round(float((latest_val - high_52w) / abs(high_52w) * 100), 4)
        except ZeroDivisionError:
            pct_from_high = None
        try:
            pct_from_low = round(float((latest_val - low_52w) / abs(low_52w) * 100), 4)
        except ZeroDivisionError:
            pct_from_low = None
        
        result["range_52w"] = {
            "high": round(high_52w, 4),
            "low": round(low_52w, 4),
            "high_date": high_date.strftime("%Y-%m-%d") if hasattr(high_date, "strftime") else str(high_date)[:10],
            "low_date": low_date.strftime("%Y-%m-%d") if hasattr(low_date, "strftime") else str(low_date)[:10],
            "pct_from_high": pct_from_high,
            "pct_from_low": pct_from_low,
        }
    
    # Full history range
    full_min = float(ts.min())
    full_max = float(ts.max())
    min_date = ts.idxmin()
    max_date = ts.idxmax()
    result["full_range"] = {
        "min": round(full_min, 4),
        "max": round(full_max, 4),
        "min_date": min_date.strftime("%Y-%m-%d") if hasattr(min_date, "strftime") else str(min_date)[:10],
        "max_date": max_date.strftime("%Y-%m-%d") if hasattr(max_date, "strftime") else str(max_date)[:10],
    }
    
    # Percentile rank of latest vs full history
    if len(ts) >= 2:
        percentile = (ts < latest_val).sum() / len(ts) * 100
        result["percentile"] = round(float(percentile), 2)
    
    # Z-score
    if len(ts) >= 2 and ts.std() > 0:
        z_score = (latest_val - ts.mean()) / ts.std()
        result["z_score"] = round(float(z_score), 4)
    
    # Rolling 20-day annualized volatility
    if len(ts) >= 20:
        daily_returns = ts.pct_change().dropna()
        if len(daily_returns) >= 20:
            rolling_vol = daily_returns.rolling(window=20).std().iloc[-1]
            if not pd.isna(rolling_vol):
                # Annualize: multiply by sqrt(252)
                result["rolling_20d_vol"] = round(float(rolling_vol * np.sqrt(252) * 100), 4)
    
    # Nearest trigger level
    trigger_levels = _parse_trigger_levels(series_row.get("trigger_levels"))
    trigger_info = _nearest_trigger(latest_val, trigger_levels)
    if trigger_info:
        result["nearest_trigger"] = trigger_info
    
    return result


def latest(
    conn: "sqlite3.Connection",  # type: ignore[name-defined] # noqa: F821
    tickers: List[str],
) -> List[Dict[str, Any]]:
    """
    Return the latest value/close for each ticker, plus date and day change.
    
    Returns a list of dicts:
        {ticker, name, latest_date, latest_value, day_change_pct, unit}
    """
    results: List[Dict[str, Any]] = []
    
    for ticker in tickers:
        series_rows = get_series(conn, ticker=ticker, status="%")
        if not series_rows:
            results.append({"ticker": ticker, "error": "Series not found"})
            continue
        
        series_row = series_rows[0]
        ts = _load_series_data(conn, series_row)
        
        if ts.empty:
            results.append({
                "ticker": ticker,
                "name": series_row["name"],
                "error": "No data available",
            })
            continue
        
        latest_date = ts.index[-1]
        latest_val = round(float(ts.iloc[-1]), 4)
        
        entry: Dict[str, Any] = {
            "ticker": ticker,
            "name": series_row["name"],
            "latest_date": latest_date.strftime("%Y-%m-%d") if hasattr(latest_date, "strftime") else str(latest_date)[:10],
            "latest_value": latest_val,
            "unit": series_row.get("unit"),
        }
        
        # Day change
        day_change = _compute_change(ts, "1d")
        if day_change is not None:
            entry["day_change_pct"] = day_change
        
        results.append(entry)
    
    return results


def ratio(
    conn: "sqlite3.Connection",  # type: ignore[name-defined] # noqa: F821
    num_ticker: str,
    den_ticker: str,
    windows: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compute the ratio of two series (numerator / denominator).
    
    Returns:
        {num_ticker, den_ticker, current_ratio, latest_date,
         changes: {window: ratio_pct_change},
         percentile: percentile rank of current ratio vs history,
         z_score: z-score of current ratio}
    """
    if windows is None:
        windows = DEFAULT_WINDOWS
    
    # Load both series
    num_rows = get_series(conn, ticker=num_ticker, status="%")
    den_rows = get_series(conn, ticker=den_ticker, status="%")
    
    if not num_rows:
        return {"error": f"Numerator series '{num_ticker}' not found"}
    if not den_rows:
        return {"error": f"Denominator series '{den_ticker}' not found"}
    
    num_ts = _load_series_data(conn, num_rows[0])
    den_ts = _load_series_data(conn, den_rows[0])
    
    if num_ts.empty:
        return {"error": f"No data for numerator '{num_ticker}'"}
    if den_ts.empty:
        return {"error": f"No data for denominator '{den_ticker}'"}
    
    # Align on dates (intersection)
    common_idx = num_ts.index.intersection(den_ts.index)
    if len(common_idx) < 2:
        return {"error": "Insufficient overlapping dates for ratio calculation"}
    
    num_aligned = num_ts.loc[common_idx]
    den_aligned = den_ts.loc[common_idx]
    
    # Compute ratio series
    ratio_series = num_aligned / den_aligned
    ratio_series = ratio_series.dropna()
    
    if ratio_series.empty:
        return {"error": "Ratio series is empty after alignment"}
    
    latest_date = ratio_series.index[-1]
    current_ratio = round(float(ratio_series.iloc[-1]), 6)
    
    result: Dict[str, Any] = {
        "num_ticker": num_ticker,
        "den_ticker": den_ticker,
        "current_ratio": current_ratio,
        "latest_date": latest_date.strftime("%Y-%m-%d") if hasattr(latest_date, "strftime") else str(latest_date)[:10],
        "num_name": num_rows[0]["name"],
        "den_name": den_rows[0]["name"],
    }
    
    # Changes per window for the ratio
    changes: Dict[str, Optional[float]] = {}
    for window in windows:
        changes[window] = _compute_change(ratio_series, window)
    result["changes"] = changes
    
    # Percentile
    if len(ratio_series) >= 2:
        percentile = (ratio_series < current_ratio).sum() / len(ratio_series) * 100
        result["percentile"] = round(float(percentile), 2)
    
    # Z-score
    if len(ratio_series) >= 2 and ratio_series.std() > 0:
        z_score = (current_ratio - ratio_series.mean()) / ratio_series.std()
        result["z_score"] = round(float(z_score), 4)
    
    return result


def spread(
    conn: "sqlite3.Connection",  # type: ignore[name-defined] # noqa: F821
    a_ticker: str,
    b_ticker: str,
    windows: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compute the spread (a - b) between two series, aligned on common dates.

    Unlike `ratio` (a / b), this is a difference — the right shape for rate
    spreads like 2Y - Fed Funds (Hayes' "market demanding hikes" signal),
    10Y - 2Y, breakeven gaps, etc.

    Returns:
        {a_ticker, b_ticker, current_spread, latest_date, a_name, b_name,
         changes: {window: absolute_change}, percentile, z_score, unit}
    """
    if windows is None:
        windows = DEFAULT_WINDOWS

    a_rows = get_series(conn, ticker=a_ticker, status="%")
    b_rows = get_series(conn, ticker=b_ticker, status="%")

    if not a_rows:
        return {"error": f"Series '{a_ticker}' not found"}
    if not b_rows:
        return {"error": f"Series '{b_ticker}' not found"}

    a_ts = _load_series_data(conn, a_rows[0])
    b_ts = _load_series_data(conn, b_rows[0])

    if a_ts.empty:
        return {"error": f"No data for '{a_ticker}'"}
    if b_ts.empty:
        return {"error": f"No data for '{b_ticker}'"}

    common_idx = a_ts.index.intersection(b_ts.index)
    if len(common_idx) < 2:
        return {"error": "Insufficient overlapping dates for spread calculation"}

    spread_series = (a_ts.loc[common_idx] - b_ts.loc[common_idx]).dropna()
    if spread_series.empty:
        return {"error": "Spread series is empty after alignment"}

    latest_date = spread_series.index[-1]
    current_spread = round(float(spread_series.iloc[-1]), 6)

    result: Dict[str, Any] = {
        "a_ticker": a_ticker,
        "b_ticker": b_ticker,
        "a_name": a_rows[0]["name"],
        "b_name": b_rows[0]["name"],
        "current_spread": current_spread,
        "unit": a_rows[0].get("unit"),
        "latest_date": latest_date.strftime("%Y-%m-%d") if hasattr(latest_date, "strftime") else str(latest_date)[:10],
    }

    # Absolute change over each window (a spread of rates is already in the unit;
    # report the change in level, not a percentage of a possibly-near-zero base).
    changes: Dict[str, Optional[float]] = {}
    for window in windows:
        days = _resolve_window_days(window)
        cutoff = spread_series.index[-1] - pd.Timedelta(days=days)
        past_vals = spread_series[spread_series.index <= cutoff]
        if past_vals.empty:
            changes[window] = None
        else:
            changes[window] = round(float(current_spread - past_vals.iloc[-1]), 6)
    result["changes"] = changes

    if len(spread_series) >= 2:
        percentile = (spread_series < current_spread).sum() / len(spread_series) * 100
        result["percentile"] = round(float(percentile), 2)
    if len(spread_series) >= 2 and spread_series.std() > 0:
        z = (current_spread - spread_series.mean()) / spread_series.std()
        result["z_score"] = round(float(z), 4)

    return result


def dashboard(
    conn: "sqlite3.Connection",  # type: ignore[name-defined] # noqa: F821
    groups: List[str],
    windows: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Run stats() for every active series in the named asset_class groups.
    
    Args:
        groups: List of asset_class group names (e.g., ['macro-rates', 'equity-index']).
        windows: Passed through to stats().
    
    Returns:
        List of stats dicts, one per active series in the requested groups.
    """
    if windows is None:
        windows = DEFAULT_WINDOWS
    
    results: List[Dict[str, Any]] = []
    
    for group in groups:
        # Get all active series in this group
        series_rows = get_series(conn, asset_class=group, status="active")
        
        for row in series_rows:
            ticker = row["ticker"]
            try:
                stat_result = stats(conn, ticker, windows=windows)
                # Add group context
                stat_result["group"] = group
                results.append(stat_result)
            except Exception as exc:
                logger.error("Error computing stats for %s: %s", ticker, exc)
                results.append({
                    "ticker": ticker,
                    "name": row.get("name", ticker),
                    "group": group,
                    "error": str(exc),
                })
    
    return results


def query_series_data(
    conn: "sqlite3.Connection",  # type: ignore[name-defined] # noqa: F821
    ticker: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    resample: Optional[str] = None,
    max_rows: int = 500,
) -> Dict[str, Any]:
    """
    Return a bounded slice of data for a series.
    For chart-like reads. NEVER returns full daily history uncapped.
    
    Args:
        ticker: Series ticker.
        since: Start date (YYYY-MM-DD).
        until: End date (YYYY-MM-DD).
        resample: Resample frequency ('weekly', 'monthly', 'quarterly'). Uses last().
        max_rows: Hard cap on returned rows.
    
    Returns:
        {ticker, name, data: [...], truncated: bool}
    """
    series_rows = get_series(conn, ticker=ticker, status="%")
    if not series_rows:
        return {"ticker": ticker, "error": "Series not found"}
    
    series_row = series_rows[0]
    table_kind = series_row["table_kind"]
    sid = series_row["series_id"]
    
    if table_kind == "ohlcv":
        df = query_ohlcv(conn, sid, since=since, until=until)
        # Use adj_close for value representation
        if not df.empty and "adj_close" in df.columns and df["adj_close"].notna().any():
            df["value"] = df["adj_close"]
        elif not df.empty:
            df["value"] = df["close"]
    else:
        df = query_observations(conn, sid, since=since, until=until)
    
    if df.empty:
        return {"ticker": ticker, "name": series_row["name"], "data": [], "data_points": 0}
    
    # Resample if requested
    if resample:
        resample_map = {
            "weekly": "W",
            "monthly": "M",
            "month": "M",
            "quarterly": "Q",
            "quarter": "Q",
        }
        freq = resample_map.get(resample.lower(), resample)
        df = df.set_index("date")
        df = df.resample(freq).last().dropna()
        df = df.reset_index()
    
    # Cap rows
    truncated = len(df) > max_rows
    if truncated:
        df = df.iloc[-max_rows:]
    
    # Convert to list of dicts
    data = []
    for _, row in df.iterrows():
        entry = {
            "date": row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])[:10],
        }
        if "value" in row:
            entry["value"] = round(float(row["value"]), 4) if not pd.isna(row["value"]) else None
        if "open" in row:
            entry["open"] = round(float(row["open"]), 4) if not pd.isna(row["open"]) else None
        if "high" in row:
            entry["high"] = round(float(row["high"]), 4) if not pd.isna(row["high"]) else None
        if "low" in row:
            entry["low"] = round(float(row["low"]), 4) if not pd.isna(row["low"]) else None
        if "close" in row:
            entry["close"] = round(float(row["close"]), 4) if not pd.isna(row["close"]) else None
        if "volume" in row:
            entry["volume"] = round(float(row["volume"]), 2) if not pd.isna(row["volume"]) else None
        data.append(entry)
    
    return {
        "ticker": ticker,
        "name": series_row["name"],
        "data": data,
        "data_points": len(data),
        "truncated": truncated,
        "unit": series_row.get("unit"),
    }
