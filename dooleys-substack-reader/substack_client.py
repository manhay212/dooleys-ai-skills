"""Thin HTTP transport for Substack's public (unauthenticated) JSON API.

This is the only module that touches the network. It wraps a requests.Session with a
browser User-Agent, sane timeouts, and a small retry/backoff. No authentication is used
or needed for public posts; paid-subscriber posts simply come back truncated and are
flagged downstream (see substack_common.is_truncated / is_paid_audience).

Endpoints used (all GET, no auth):
  - https://substack.com/api/v1/user/<handle>/public_profile
  - https://<subdomain>.substack.com/api/v1/posts?limit=<n>&offset=<n>
  - https://<subdomain>.substack.com/api/v1/posts/<slug>
"""
from __future__ import annotations

import time

import requests

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class SubstackError(RuntimeError):
    """Raised when the Substack API cannot be reached or returns a non-OK status."""


class SubstackClient:
    def __init__(self, user_agent: str = DEFAULT_UA, timeout: float = 30.0,
                 max_retries: int = 3, backoff: float = 1.5):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})

    # -- low level ---------------------------------------------------------- #
    def _get_json(self, url: str, params: dict | None = None):
        last_err = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json()
                # 429 / 5xx are transient; retry. 4xx (except 429) are fatal.
                if resp.status_code != 429 and 400 <= resp.status_code < 500:
                    raise SubstackError(f"GET {url} -> HTTP {resp.status_code}")
                last_err = SubstackError(f"GET {url} -> HTTP {resp.status_code}")
            except (requests.RequestException, ValueError) as e:
                last_err = SubstackError(f"GET {url} failed: {type(e).__name__}: {e}")
            if attempt < self.max_retries - 1:
                time.sleep(self.backoff * (attempt + 1))
        raise last_err or SubstackError(f"GET {url} failed")

    # -- API surface -------------------------------------------------------- #
    def get_public_profile(self, handle: str) -> dict:
        """Resolve a substack.com/@<handle> profile (name, bio, publications)."""
        url = f"https://substack.com/api/v1/user/{handle}/public_profile"
        data = self._get_json(url)
        if not isinstance(data, dict):
            raise SubstackError(f"unexpected profile payload for @{handle}")
        return data

    def list_posts(self, subdomain: str, limit: int = 12, offset: int = 0) -> list:
        """List a publication's posts, newest first."""
        url = f"https://{subdomain}.substack.com/api/v1/posts"
        data = self._get_json(url, params={"limit": limit, "offset": offset})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("posts") or []
        raise SubstackError(f"unexpected posts payload for {subdomain}")

    def get_post(self, subdomain: str, slug: str) -> dict:
        """Fetch a single post's full content (authoritative body_html)."""
        url = f"https://{subdomain}.substack.com/api/v1/posts/{slug}"
        data = self._get_json(url)
        if not isinstance(data, dict):
            raise SubstackError(f"unexpected post payload for {subdomain}/{slug}")
        return data
