"""EOD Historical Data (eodhd.com) adapter for dooleys-market-data.

DORMANT BY DEFAULT: gated on EODHD_API_KEY. With no key set, _source_available()
in the engine skips it, and even if called directly fetch() returns an empty
frame — so it can live in catalog chains harmlessly until a key is purchased.

Symbols use EODHD's EXCHANGE-suffix form: 'GSPC.INDX', 'AAPL.US', '0700.HK',
'KS11.INDX', 'GDAXI.INDX'.

Returns a DataFrame indexed by UTC date with OHLCV columns; EMPTY on soft failure.
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
    rate_limit = int(cfg.get("rate_limit_per_min", 60))
    min_interval = max(60.0 / rate_limit, 0.2)
    elapsed = time.monotonic() - _last_request_time
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _last_request_time = time.monotonic()


def _api_key(cfg: Dict[str, Any]) -> Optional[str]:
    return os.getenv(cfg.get("auth_env", "EODHD_API_KEY")) or cfg.get("api_key")


def fetch(source_symbol: str, start: Optional[str] = None,
          end: Optional[str] = None, cfg: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    cfg = cfg or {}
    key = _api_key(cfg)
    if not key:
        return pd.DataFrame()  # dormant — no key

    base = cfg.get("base_url", "https://eodhd.com/api")
    url = f"{base.rstrip('/')}/eod/{source_symbol}"
    params: Dict[str, Any] = {"api_token": key, "fmt": "json", "period": "d"}
    if start:
        params["from"] = start[:10]
    if end:
        params["to"] = end[:10]

    _respect_rate_limit(cfg)
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("eodhd request failed for '%s': %s", source_symbol, exc)
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if "date" not in df.columns:
        return pd.DataFrame()
    df = df.rename(columns={"adjusted_close": "adj_close"})
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.normalize()
    keep = [c for c in ["date", "open", "high", "low", "close", "adj_close", "volume"] if c in df.columns]
    df = df[keep].set_index("date").sort_index()
    if "adj_close" not in df.columns and "close" in df.columns:
        df["adj_close"] = df["close"]
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
