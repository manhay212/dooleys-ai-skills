"""
US Treasury FiscalData source adapter for dooleys-market-data.

Fetches the daily Treasury General Account (TGA) closing balance from the
Daily Treasury Statement (DTS). No API key required.

History
-------
The original `/v1/accounting/dts/dts_table_1` endpoint was retired by Treasury
(now 404s). This adapter targets the current endpoint
`/v1/accounting/dts/operating_cash_balance`, filtering to the
"Treasury General Account (TGA) Closing Balance" row. In the new schema the
closing balance is carried in `open_today_bal` (the legacy `close_today_bal`
field is null), in millions of USD.

Configuration (cfg dict):
    base_url   : str — API base URL
                 (default: https://api.fiscaldata.treasury.gov/services/api/fiscal_service)
    rate_limit : int — max requests per minute (default 60)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_last_request_time: float = 0.0

# The account_type row that carries the daily TGA closing balance.
_TGA_CLOSING = "Treasury General Account (TGA) Closing Balance"


def _respect_rate_limit(cfg: Dict[str, Any]) -> None:
    global _last_request_time
    rate_limit: int = int(cfg.get("rate_limit_per_min", cfg.get("rate_limit", 60)))
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
    Fetch the daily TGA closing balance (millions USD).

    Parameters
    ----------
    source_symbol : str
        Ignored — retained for interface compatibility. The endpoint and filter
        are fixed to the TGA closing balance.
    start, end : str | None
        ISO dates (YYYY-MM-DD) bounding record_date.
    cfg : dict
        Adapter configuration (see module docstring).

    Returns
    -------
    pd.DataFrame
        Columns: ['value'], indexed by tz-aware UTC date. Empty on failure.
    """
    if cfg is None:
        cfg = {}

    base_url = cfg.get(
        "base_url",
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service",
    )
    url = f"{base_url.rstrip('/')}/v1/accounting/dts/operating_cash_balance"

    filters = [f"account_type:eq:{_TGA_CLOSING}"]
    if start:
        filters.append(f"record_date:gte:{start}")
    if end:
        filters.append(f"record_date:lte:{end}")
    filter_str = ",".join(filters)

    all_rows: list[dict[str, Any]] = []
    page_number = 1

    while True:
        params: Dict[str, Any] = {
            "fields": "record_date,account_type,open_today_bal,close_today_bal",
            "filter": filter_str,
            "sort": "record_date",
            "page[size]": 10000,
            "page[number]": page_number,
        }

        _respect_rate_limit(cfg)

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Treasury API request failed: %s", exc)
            return pd.DataFrame()

        payload = resp.json()
        data = payload.get("data", [])
        if not data:
            break

        for row in data:
            record_date = row.get("record_date", "")
            # New schema: value is in open_today_bal; fall back to close_today_bal.
            raw = row.get("open_today_bal")
            if raw in (None, "null", ""):
                raw = row.get("close_today_bal")
            try:
                val = float(raw) if raw not in (None, "null", "") else None
            except (ValueError, TypeError):
                val = None
            all_rows.append({"date": record_date, "value": val})

        meta = payload.get("meta", {})
        total_pages = int(meta.get("total-pages", 1))
        if page_number >= total_pages:
            break
        page_number += 1

    if not all_rows:
        logger.warning("Treasury: no TGA closing-balance data returned")
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["date"] = df["date"].dt.normalize().dt.tz_localize("UTC")
    df = df.set_index("date").sort_index()
    df = df.dropna(subset=["value"])

    return df[["value"]]
