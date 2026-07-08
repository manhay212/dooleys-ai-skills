"""Direct Yahoo Finance v8 chart adapter for dooleys-market-data.

Fetches daily OHLCV straight from query{1,2}.finance.yahoo.com/v8/finance/chart.
No API key, no crumb (the v8 chart endpoint is crumbless).

Transport: uses curl_cffi with browser TLS impersonation when available — this is
what defeats Yahoo's anti-bot 429s that plain `requests` trips (verified live:
plain requests -> 429 on the same IP where curl_cffi impersonate=chrome -> 200).
Falls back to `requests` (with a rotating User-Agent) if curl_cffi is missing.

Hardened with host rotation (query1<->query2) and retry+backoff. Independent of
the `yahoo` (yfinance) adapter on purpose: two different code paths to the same
data give genuine redundancy in a failover chain.

Returns a DataFrame indexed by UTC date with columns
['open','high','low','close','volume','adj_close']; EMPTY on soft failure.
"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_HOSTS = ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"]
_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
]
_last_request_time: float = 0.0


def _respect_rate_limit(cfg: Dict[str, Any]) -> None:
    global _last_request_time
    rate_limit = int(cfg.get("rate_limit_per_min", 30))
    min_interval = max(60.0 / rate_limit, 1.0)
    elapsed = time.monotonic() - _last_request_time
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed + random.uniform(0, 0.4))  # jitter
    _last_request_time = time.monotonic()


def _to_epoch(d: Optional[str], default: int) -> int:
    if not d:
        return default
    return int(datetime.strptime(d[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def _http_get(url: str, params: Dict[str, Any]):
    """GET with curl_cffi browser impersonation if available, else requests.

    Returns a response-like object exposing .status_code and .json(), or None on
    transport error.
    """
    # Preferred: curl_cffi with Chrome TLS fingerprint (bypasses Yahoo anti-bot).
    try:
        from curl_cffi import requests as creq  # type: ignore
        try:
            return creq.get(url, params=params, impersonate="chrome", timeout=30)
        except Exception as exc:  # noqa: BLE001
            logger.debug("curl_cffi GET failed (%s); trying requests", exc)
    except ImportError:
        pass
    # Fallback: plain requests with a rotating UA.
    try:
        import requests
        return requests.get(
            url, params=params,
            headers={"User-Agent": random.choice(_UAS), "Accept": "application/json"},
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("requests GET failed: %s", exc)
        return None


def fetch(source_symbol: str, start: Optional[str] = None,
          end: Optional[str] = None, cfg: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    cfg = cfg or {}
    _respect_rate_limit(cfg)

    p1 = _to_epoch(start, 0)
    p2 = _to_epoch(end, int(datetime.now(timezone.utc).timestamp())) + 86400
    params = {"period1": p1, "period2": p2, "interval": "1d", "events": "div,splits"}

    data = None
    attempts = int(cfg.get("max_retries", 3))
    for attempt in range(attempts):
        host = _HOSTS[attempt % len(_HOSTS)]
        url = f"{host}/v8/finance/chart/{source_symbol}"
        resp = _http_get(url, params)
        if resp is not None and getattr(resp, "status_code", None) == 200:
            try:
                data = resp.json()
                break
            except Exception:  # noqa: BLE001
                data = None
        code = getattr(resp, "status_code", "n/a") if resp is not None else "n/a"
        logger.info("yahoo_direct %s -> HTTP %s (attempt %d)", source_symbol, code, attempt + 1)
        time.sleep(min(2 ** attempt, 8) + random.uniform(0, 0.5))  # exp backoff + jitter

    if not data:
        logger.warning("yahoo_direct: no usable response for '%s'", source_symbol)
        return pd.DataFrame()

    try:
        result = data["chart"]["result"][0]
        ts = result["timestamp"]
        q = result["indicators"]["quote"][0]
        adj = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
    except (KeyError, IndexError, TypeError):
        logger.warning("yahoo_direct: unexpected payload for '%s'", source_symbol)
        return pd.DataFrame()

    df = pd.DataFrame({
        "date": pd.to_datetime(ts, unit="s", utc=True).normalize(),
        "open": q.get("open"), "high": q.get("high"), "low": q.get("low"),
        "close": q.get("close"), "volume": q.get("volume"),
        "adj_close": adj if adj is not None else q.get("close"),
    })
    df = df.dropna(subset=["close"]).set_index("date").sort_index()
    df.index.name = "date"
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
