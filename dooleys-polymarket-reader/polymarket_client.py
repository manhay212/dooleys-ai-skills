"""Thin HTTP transport for Polymarket's public (keyless) read APIs.

Gamma API (events/markets/search): https://gamma-api.polymarket.com
CLOB read (price history):         https://clob.polymarket.com
No authentication is used or needed for reading. The POLYMARKET_* keys are for
the trading API only and are intentionally not referenced here.
"""
from __future__ import annotations

import time

import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class PolymarketError(RuntimeError):
    """Raised when a Polymarket endpoint cannot be reached or returns non-OK."""


class PolymarketClient:
    def __init__(self, user_agent=DEFAULT_UA, timeout=30.0, max_retries=3, backoff=1.5):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})

    def _get_json(self, url, params=None):
        last_err = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code != 429 and 400 <= resp.status_code < 500:
                    raise PolymarketError(f"GET {url} -> HTTP {resp.status_code}")
                last_err = PolymarketError(f"GET {url} -> HTTP {resp.status_code}")
            except (requests.RequestException, ValueError) as e:
                last_err = PolymarketError(f"GET {url} failed: {type(e).__name__}: {e}")
            if attempt < self.max_retries - 1:
                time.sleep(self.backoff * (attempt + 1))
        raise last_err or PolymarketError(f"GET {url} failed")

    def get_events_by_tag(self, tag_slug, limit=40, active=True, closed=False):
        params = {
            "tag_slug": tag_slug, "limit": limit,
            "active": str(active).lower(), "closed": str(closed).lower(),
            "order": "volume24hr", "ascending": "false",
        }
        data = self._get_json(f"{GAMMA}/events", params=params)
        return data if isinstance(data, list) else (data.get("data") or [])

    def search_events(self, query, limit=20):
        data = self._get_json(f"{GAMMA}/public-search",
                              params={"q": query, "limit_per_type": limit})
        if isinstance(data, dict):
            return data.get("events") or []
        return []

    def get_event_by_slug(self, slug):
        data = self._get_json(f"{GAMMA}/events", params={"slug": slug})
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict) and data.get("data"):
            return data["data"][0]
        return None

    def get_event_by_id(self, event_id):
        try:
            data = self._get_json(f"{GAMMA}/events/{event_id}")
        except PolymarketError:
            return None
        return data if isinstance(data, dict) and data else None

    def get_price_history(self, token_id, interval="1w", fidelity=180):
        data = self._get_json(f"{CLOB}/prices-history",
                              params={"market": token_id, "interval": interval, "fidelity": fidelity})
        if isinstance(data, dict):
            return data.get("history") or []
        return []
