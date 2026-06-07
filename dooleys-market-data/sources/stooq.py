"""
Stooq CSV source adapter for dooleys-market-data.

Fetches free daily OHLCV data from stooq.com.  No API key required.

Configuration (cfg dict):
    base_url : str — API base URL (default: https://stooq.com/q/d/l/)
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any, Dict, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Rate-limit: Stooq is free — be gentle (min 1 s between calls)
_last_request_time: float = 0.0


def _respect_rate_limit(cfg: Dict[str, Any]) -> None:
    global _last_request_time
    min_interval: float = 1.0  # Stooq default
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
    Fetch daily OHLCV data from Stooq for *source_symbol*.

    Parameters
    ----------
    source_symbol : str
        Stooq ticker (e.g. 'aapl.us', 'wig').
    start : str | None
        Ignored — Stooq returns full history.  Filtered client-side if needed.
    end : str | None
        Ignored — Stooq returns full history.
    cfg : dict
        Adapter configuration (see module docstring).

    Returns
    -------
    pd.DataFrame
        Columns: ['open', 'high', 'low', 'close', 'adj_close', 'volume'].
        Empty on failure.
    """
    if cfg is None:
        cfg = {}

    base_url = cfg.get("base_url", "https://stooq.com/q/d/l/")
    if not base_url.endswith("/"):
        base_url += "/"

    url = f"{base_url}?s={source_symbol}&i=d"

    _respect_rate_limit(cfg)

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning(
            "Stooq request failed for symbol '%s': %s", source_symbol, exc
        )
        return pd.DataFrame()

    csv_text = resp.text.strip()
    if not csv_text or "No data" in csv_text:
        logger.warning(
            "Stooq: empty response or 'No data' for symbol '%s'", source_symbol
        )
        return pd.DataFrame()

    try:
        df = pd.read_csv(
            io.StringIO(csv_text),
            parse_dates=["Date"],
            dayfirst=False,
        )
    except Exception as exc:
        logger.warning(
            "Stooq: failed to parse CSV for '%s': %s", source_symbol, exc
        )
        return pd.DataFrame()

    # Expected columns: Date, Open, High, Low, Close, Volume
    col_map = {
        "Date": "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    # Rename columns that exist
    rename = {k: v for k, v in col_map.items() if k in df.columns}
    df = df.rename(columns=rename)

    # Use Close as proxy for adj_close
    if "close" in df.columns:
        df["adj_close"] = df["close"]
    else:
        logger.warning("Stooq: no 'Close' column in CSV for '%s'", source_symbol)
        return pd.DataFrame()

    # Keep only standard columns
    keep = ["date", "open", "high", "low", "close", "adj_close", "volume"]
    df = df[[c for c in keep if c in df.columns]]

    # Parse and normalize date
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["date"] = df["date"].dt.normalize().dt.tz_localize("UTC")
    df = df.set_index("date").sort_index()

    # Ensure numeric columns
    for col in ["open", "high", "low", "close", "adj_close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df[keep]
