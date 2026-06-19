"""
EIA API v2 source adapter for dooleys-market-data.

Fetches energy data from the U.S. Energy Information Administration API v2.

Configuration (cfg dict):
    base_url : str   — API base URL (default: https://api.eia.gov/v2)
    auth_env : str   — environment variable name holding the API key (default: EIA_API_KEY)
    route    : str   — API route fragment (e.g. 'petroleum/pri/spt')
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_last_request_time: float = 0.0


def _respect_rate_limit(cfg: Dict[str, Any]) -> None:
    global _last_request_time
    rate_limit: int = int(cfg.get("rate_limit", 60))
    min_interval: float = max(60.0 / rate_limit, 1.0)
    elapsed = time.monotonic() - _last_request_time
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _last_request_time = time.monotonic()


def _get_api_key(cfg: Dict[str, Any]) -> Optional[str]:
    env_var = cfg.get("auth_env", "EIA_API_KEY")
    return os.getenv(env_var)


def fetch(
    source_symbol: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """
    Fetch EIA v2 time-series data for *source_symbol*.

    Parameters
    ----------
    source_symbol : str
        EIA series ID (e.g. 'RWTC', 'RBRTE').
    start : str | None
        ISO start date (YYYY-MM-DD).  None → earliest available.
    end : str | None
        ISO end date.  None → latest available.
    cfg : dict
        Must include 'route' key with the API route fragment
        (e.g. 'petroleum/pri/spt').

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
            "EIA adapter: no API key found (set env %s). Returning empty frame.",
            cfg.get("auth_env", "EIA_API_KEY"),
        )
        return pd.DataFrame()

    route = cfg.get("route")
    if not route:
        logger.warning(
            "EIA adapter: no 'route' in cfg for series '%s'. Returning empty frame.",
            source_symbol,
        )
        return pd.DataFrame()

    base_url = cfg.get("base_url", "https://api.eia.gov/v2")
    url = f"{base_url.rstrip('/')}/{route.strip('/')}/data/"

    # Use series frequency if available, default to daily
    freq = cfg.get("frequency", "daily")
    # Normalize: weekly/monthly/quarterly → lowercase for EIA API
    if freq and freq.lower() in ("weekly", "monthly", "quarterly", "annual"):
        freq = freq.lower()
    else:
        freq = "daily"

    params: Dict[str, Any] = {
        "api_key": api_key,
        "frequency": freq,
        "data[0]": "value",
        f"facets[series][]": source_symbol,
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "offset": 0,
        "length": 5000,
    }

    if start:
        params["start"] = start
    if end:
        params["end"] = end

    all_rows: list[dict[str, Any]] = []

    while True:
        _respect_rate_limit(cfg)

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning(
                "EIA API request failed for series '%s': %s", source_symbol, exc
            )
            return pd.DataFrame()

        payload = resp.json()
        response_data = payload.get("response", {})
        data_rows = response_data.get("data", [])

        if not data_rows:
            break

        for row in data_rows:
            period = row.get("period", "")
            raw_value = row.get("value")
            if raw_value is not None:
                try:
                    raw_value = float(raw_value)
                except (ValueError, TypeError):
                    raw_value = None
            all_rows.append({"date": period, "value": raw_value})

        total = int(response_data.get("total", 0))
        offset = int(params.get("offset", 0))
        length = int(params.get("length", 5000))

        if offset + length >= total:
            break

        params["offset"] = offset + length

    if not all_rows:
        logger.warning("EIA: no data returned for series '%s'", source_symbol)
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["date"] = df["date"].dt.normalize().dt.tz_localize("UTC")
    df = df.set_index("date").sort_index()
    df = df.dropna(subset=["value"])

    return df[["value"]]
