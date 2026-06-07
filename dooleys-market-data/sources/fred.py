"""
FRED API source adapter for dooleys-market-data.

Fetches economic time-series observations from the Federal Reserve
Economic Data (FRED) API.

Configuration (cfg dict):
    base_url : str   — API base URL (default: https://api.stlouisfed.org/fred)
    auth_env : str   — environment variable name holding the API key
    api_key  : str   — fallback key if auth_env is not set
    rate_limit : int — max requests per minute (default 120)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level rate-limit state (per-process, not per-symbol)
# ---------------------------------------------------------------------------
_last_request_time: float = 0.0
_MIN_INTERVAL: float = 0.5  # seconds between requests (default for 120/min)


def _respect_rate_limit(cfg: Dict[str, Any]) -> None:
    """Sleep if necessary to stay under the configured rate limit."""
    global _last_request_time
    rate_limit: int = int(cfg.get("rate_limit", 120))
    min_interval: float = max(60.0 / rate_limit, 0.5)
    elapsed = time.monotonic() - _last_request_time
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _last_request_time = time.monotonic()


def _get_api_key(cfg: Dict[str, Any]) -> Optional[str]:
    """Resolve the FRED API key from environment or config."""
    env_var = cfg.get("auth_env", "FRED_API_KEY")
    key = os.getenv(env_var)
    if key:
        return key
    key = cfg.get("api_key")
    if key:
        return str(key)
    return None


def fetch(
    source_symbol: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """
    Fetch FRED observations for *source_symbol*.

    Parameters
    ----------
    source_symbol : str
        FRED series ID (e.g. DGS10, UNRATE, GDP).
    start : str | None
        ISO-format start date (YYYY-MM-DD).  None → earliest available.
    end : str | None
        ISO-format end date.  None → latest available.
    cfg : dict
        Adapter configuration (see module docstring).

    Returns
    -------
    pd.DataFrame
        Columns: ['date', 'value'].  Empty on failure.
    """
    if cfg is None:
        cfg = {}

    api_key = _get_api_key(cfg)
    if not api_key:
        logger.warning(
            "FRED adapter: no API key found (set env %s or cfg.api_key). "
            "Returning empty frame.",
            cfg.get("auth_env", "FRED_API_KEY"),
        )
        return pd.DataFrame()

    base_url = cfg.get("base_url", "https://api.stlouisfed.org")
    url = f"{base_url.rstrip('/')}/fred/series/observations"

    params: Dict[str, str] = {
        "series_id": source_symbol,
        "api_key": api_key,
        "file_type": "json",
    }
    if start:
        params["observation_start"] = start
    if end:
        params["observation_end"] = end

    _respect_rate_limit(cfg)

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning(
            "FRED API request failed for series '%s': %s", source_symbol, exc
        )
        return pd.DataFrame()

    data = resp.json()
    observations = data.get("observations", [])

    if not observations:
        logger.warning("FRED: no observations returned for series '%s'", source_symbol)
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for obs in observations:
        raw_date = obs.get("date", "")
        raw_value = obs.get("value", ".")
        if raw_value == ".":
            raw_value = None
        else:
            try:
                raw_value = float(raw_value)
            except (ValueError, TypeError):
                raw_value = None
        rows.append({"date": raw_date, "value": raw_value})

    df = pd.DataFrame(rows)

    # Parse date column
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["date"] = df["date"].dt.normalize().dt.tz_localize("UTC")

    df = df.set_index("date").sort_index()

    # Drop rows where value is NaN (FRED '.' markers)
    df = df.dropna(subset=["value"])

    return df[["value"]]
