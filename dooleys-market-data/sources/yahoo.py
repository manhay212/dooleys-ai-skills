"""
Yahoo Finance source adapter for dooleys-market-data.

Fetches daily OHLCV data via the yfinance library. No API key required.
Preferred over Stooq which now requires JavaScript verification.

Configuration (cfg dict):
    base_url : None (yfinance uses its own endpoints)
    rate_limit_per_min : int — (default 60)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_last_request_time: float = 0.0


def _respect_rate_limit(cfg: Dict[str, Any]) -> None:
    global _last_request_time
    rate_limit: int = int(cfg.get("rate_limit_per_min", 60))
    min_interval: float = max(60.0 / rate_limit, 1.0)
    elapsed = time.monotonic() - _last_request_time
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _last_request_time = time.monotonic()


def fetch(
    source_symbol: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """
    Fetch daily OHLCV data from Yahoo Finance for *source_symbol*.

    Parameters
    ----------
    source_symbol : str
        Yahoo Finance ticker (e.g. '^GSPC' for S&P 500, 'GC=F' for gold futures).
    start : str | None
        ISO-format start date (YYYY-MM-DD). None = max available.
    end : str | None
        ISO-format end date. None = latest.
    cfg : dict
        Adapter configuration.

    Returns
    -------
    pd.DataFrame
        Columns: ['open', 'high', 'low', 'close', 'adj_close', 'volume'].
        Empty on failure.
    """
    if cfg is None:
        cfg = {}

    _respect_rate_limit(cfg)

    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed. Run: pip install yfinance")
        return pd.DataFrame()

    try:
        ticker = yf.Ticker(source_symbol)
        df = ticker.history(start=start, end=end, auto_adjust=False)
    except Exception as exc:
        logger.warning(
            "Yahoo Finance request failed for '%s': %s", source_symbol, exc
        )
        return pd.DataFrame()

    if df.empty:
        logger.warning("Yahoo Finance: no data for '%s'", source_symbol)
        return pd.DataFrame()

    # yfinance columns: Open, High, Low, Close, Adj Close, Volume
    col_map = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
    }
    df = df.rename(columns=col_map)

    # Keep only standard columns
    keep = ["open", "high", "low", "close", "adj_close", "volume"]
    df = df[[c for c in keep if c in df.columns]]

    # If no adj_close column, use close
    if "adj_close" not in df.columns and "close" in df.columns:
        df["adj_close"] = df["close"]

    # Normalize date index (yfinance returns tz-aware)
    df.index = pd.to_datetime(df.index, errors="coerce")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df.index = df.index.normalize()
    df.index.name = "date"
    df = df.sort_index()

    # Ensure numeric
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df
