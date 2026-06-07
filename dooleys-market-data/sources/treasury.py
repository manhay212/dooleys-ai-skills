"""
US Treasury FiscalData source adapter for dooleys-market-data.

Fetches Treasury General Account (TGA) daily balances from the
U.S. Treasury FiscalData API.  No API key required.

Configuration (cfg dict):
    base_url : str — API base URL
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


def _respect_rate_limit(cfg: Dict[str, Any]) -> None:
    global _last_request_time
    rate_limit: int = int(cfg.get("rate_limit", 60))
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
    Fetch Treasury daily statement data (TGA balance).

    Parameters
    ----------
    source_symbol : str
        For the default endpoint this is ignored — the adapter fetches
        DTS Table 1 (Deposits with Federal Reserve → TGA).
        Reserved for future multi-endpoint support.
    start : str | None
        ISO start date (YYYY-MM-DD).  None → earliest available.
    end : str | None
        ISO end date.  None → latest available.
    cfg : dict
        Adapter configuration (see module docstring).

    Returns
    -------
    pd.DataFrame
        Columns: ['date', 'value'] where value is close_today_bal in millions USD.
        Empty on failure.
    """
    if cfg is None:
        cfg = {}

    base_url = cfg.get(
        "base_url",
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service",
    )
    url = f"{base_url.rstrip('/')}/v1/accounting/dts/dts_table_1"

    # Build filter string
    filters = ["account_type:eq:Deposits%20with%20Federal%20Reserve"]
    if start:
        filters.append(f"record_date:gte:{start}")
    if end:
        filters.append(f"record_date:lte:{end}")
    filter_str = ",".join(filters)

    all_rows: list[dict[str, Any]] = []
    page_number: int = 1

    while True:
        params: Dict[str, Any] = {
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
            logger.warning(
                "Treasury API request failed: %s", exc
            )
            return pd.DataFrame()

        payload = resp.json()
        data = payload.get("data", [])

        if not data:
            break

        for row in data:
            record_date = row.get("record_date", "")
            close_bal = row.get("close_today_bal")
            if close_bal is not None:
                try:
                    close_bal = float(close_bal)
                except (ValueError, TypeError):
                    close_bal = None
            all_rows.append({"date": record_date, "value": close_bal})

        # Check if there are more pages
        meta = payload.get("meta", {})
        total_pages = int(meta.get("total-pages", 1))
        if page_number >= total_pages:
            break
        page_number += 1

    if not all_rows:
        logger.warning("Treasury: no data returned")
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["date"] = df["date"].dt.normalize().dt.tz_localize("UTC")
    df = df.set_index("date").sort_index()
    df = df.dropna(subset=["value"])

    return df[["value"]]
