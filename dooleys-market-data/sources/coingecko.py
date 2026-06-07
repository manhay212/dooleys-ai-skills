"""
CoinGecko API source adapter for dooleys-market-data.

Fetches cryptocurrency OHLCV and observation data from CoinGecko API v3.

Configuration (cfg dict):
    base_url    : str   — API base URL (default: https://api.coingecko.com/api/v3)
    auth_env    : str   — environment variable holding API key (optional — free tier works keyless)
    api_key     : str   — fallback key
    table_kind  : str   — 'ohlcv' or 'observations' (controls endpoint selection)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_last_request_time: float = 0.0


def _respect_rate_limit(cfg: Dict[str, Any]) -> None:
    global _last_request_time
    has_key = bool(_get_api_key(cfg))
    rate_limit: int = 30 if has_key else 10  # with key: 30/min, free: 10/min
    min_interval: float = 60.0 / rate_limit
    elapsed = time.monotonic() - _last_request_time
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _last_request_time = time.monotonic()


def _get_api_key(cfg: Dict[str, Any]) -> Optional[str]:
    env_var = cfg.get("auth_env", "COINGECKO_API_KEY")
    key = os.getenv(env_var)
    if key:
        return key
    key = cfg.get("api_key")
    if key:
        return str(key)
    return None


def _get_headers(cfg: Dict[str, Any]) -> Dict[str, str]:
    """Build request headers including API key if available."""
    headers: Dict[str, str] = {"Accept": "application/json"}
    api_key = _get_api_key(cfg)
    if api_key:
        headers["x-cg-pro-api-key"] = api_key
    return headers


def _fetch_ohlcv(
    source_symbol: str,
    cfg: Dict[str, Any],
) -> pd.DataFrame:
    """
    Fetch daily OHLCV via /coins/{id}/market_chart?vs_currency=usd&days=max&interval=daily
    """
    base_url = cfg.get("base_url", "https://api.coingecko.com/api/v3")
    url = (
        f"{base_url.rstrip('/')}/coins/{source_symbol}"
        f"/market_chart?vs_currency=usd&days=max&interval=daily"
    )

    _respect_rate_limit(cfg)

    try:
        resp = requests.get(url, headers=_get_headers(cfg), timeout=30)
        if resp.status_code == 429:
            logger.warning(
                "CoinGecko rate-limited for '%s'. Returning empty frame.", source_symbol
            )
            return pd.DataFrame()
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning(
            "CoinGecko OHLCV request failed for '%s': %s", source_symbol, exc
        )
        return pd.DataFrame()

    data = resp.json()
    prices = data.get("prices", [])
    total_volumes = data.get("total_volumes", [])

    if not prices:
        logger.warning("CoinGecko: no price data for '%s'", source_symbol)
        return pd.DataFrame()

    # Build volume lookup by timestamp (ms)
    vol_by_ts: Dict[int, float] = {}
    for tv in total_volumes:
        ts = int(tv[0]) // 1000  # ms → s
        vol_by_ts[ts] = float(tv[1])

    rows: list[dict[str, Any]] = []
    prev_price: Optional[float] = None

    for i, p in enumerate(prices):
        ts_ms = int(p[0])
        ts = ts_ms // 1000
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        price = float(p[1])
        volume = vol_by_ts.get(ts, 0.0)

        # CoinGecko daily endpoint only gives price + volume.
        # For OHLCV we set open=high=low=close=price as a simple approximation.
        row = {
            "date": dt,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "adj_close": price,
            "volume": volume,
        }

        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.set_index("date").sort_index()
    return df[["open", "high", "low", "close", "adj_close", "volume"]]


def _fetch_observation(
    source_symbol: str,
    cfg: Dict[str, Any],
) -> pd.DataFrame:
    """
    Fetch current circulating supply from /coins/{id}?localization=false&...
    This gives only the current snapshot.  Historical supply is limited on free tier.
    """
    base_url = cfg.get("base_url", "https://api.coingecko.com/api/v3")
    url = (
        f"{base_url.rstrip('/')}/coins/{source_symbol}"
        f"?localization=false&tickers=false&community_data=false&developer_data=false"
    )

    _respect_rate_limit(cfg)

    try:
        resp = requests.get(url, headers=_get_headers(cfg), timeout=30)
        if resp.status_code == 429:
            logger.warning(
                "CoinGecko rate-limited for '%s'. Returning empty frame.", source_symbol
            )
            return pd.DataFrame()
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning(
            "CoinGecko observation request failed for '%s': %s", source_symbol, exc
        )
        return pd.DataFrame()

    data = resp.json()
    market_data = data.get("market_data", {})
    circulating = market_data.get("circulating_supply")

    if circulating is None:
        logger.warning(
            "CoinGecko: no circulating_supply in response for '%s'", source_symbol
        )
        return pd.DataFrame()

    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    df = pd.DataFrame([{"date": now, "value": float(circulating)}])
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.set_index("date")
    return df[["value"]]


def fetch(
    source_symbol: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """
    Fetch data from CoinGecko for *source_symbol*.

    Parameters
    ----------
    source_symbol : str
        CoinGecko coin ID (e.g. 'bitcoin', 'ethereum', 'tether').
    start : str | None
        Ignored for CoinGecko (returns full range or current snapshot).
    end : str | None
        Ignored for CoinGecko.
    cfg : dict
        Must include 'table_kind' key: 'ohlcv' or 'observations'.

    Returns
    -------
    pd.DataFrame
        ohlcv: ['open','high','low','close','adj_close','volume']
        observations: ['value'] (single row, current supply)
        Empty on failure.
    """
    if cfg is None:
        cfg = {}

    table_kind = cfg.get("table_kind", "ohlcv")

    if table_kind == "observations":
        return _fetch_observation(source_symbol, cfg)
    else:
        return _fetch_ohlcv(source_symbol, cfg)
