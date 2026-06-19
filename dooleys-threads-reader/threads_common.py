"""Shared helpers for the dooleys-threads-reader skill.

This module holds everything that does NOT need a live browser: path resolution,
credential/account/config loading (env-first, file fallback — same convention as
dooleys-twitter-x-reader), time-window math, and small parsers. Keeping it browser-free
means it can be unit-tested fast and offline (see tests/test_threads_common.py).

The Playwright-driven scripts (record.py, threads_reader.py) import from here.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Constants & paths
# --------------------------------------------------------------------------- #

THREADS_BASE = "https://www.threads.com"
LOGIN_URL = f"{THREADS_BASE}/login"

SKILL_DIR = Path(__file__).resolve().parent

# The authenticated session captured by record.py and reused by threads_reader.py.
STORAGE_STATE_PATH = SKILL_DIR / "storage_state.json"
# Where record.py drops page snapshots for Claude to read while authoring selectors.
RECORDINGS_DIR = SKILL_DIR / "recordings"
# Default config / output locations.
ACCOUNTS_PATH = SKILL_DIR / "accounts.json"
CREDENTIALS_PATH = SKILL_DIR / "config" / "credentials.json"
OUTPUT_PATH = SKILL_DIR / "output_threads_reader.json"


# --------------------------------------------------------------------------- #
# Small parsers / normalizers
# --------------------------------------------------------------------------- #

def normalize_username(value: str) -> str:
    """Reduce any handle-ish string to a bare lowercase username.

    Accepts '@Zuck', 'zuck', a full profile URL, or a '/@zuck/post/..' path.
    """
    if not value:
        return ""
    s = value.strip()
    # Pull the handle out of a URL or path if present.
    m = re.search(r"/@([^/?#\s]+)", s)
    if m:
        s = m.group(1)
    s = s.lstrip("@").strip()
    return s.lower()


def shortcode_from_url(href: str) -> Optional[str]:
    """Extract the post shortcode from a permalink like '/@zuck/post/DZpPDXbCeTt'."""
    if not href:
        return None
    m = re.search(r"/post/([^/?#]+)", href)
    return m.group(1) if m else None


def parse_count(value: Optional[str]) -> Optional[int]:
    """Parse a Threads engagement count string ('846', '17.6K', '1.2M', '1,234').

    Returns None for empty input or strings with no digits (e.g. an unlabelled button).
    """
    if not value:
        return None
    s = value.strip().replace(",", "")
    m = re.match(r"^([0-9]*\.?[0-9]+)\s*([KMB]?)$", s, re.IGNORECASE)
    if not m:
        # Fall back: if there are digits embedded, grab the first numeric token.
        m2 = re.search(r"([0-9]*\.?[0-9]+)\s*([KMB]?)", s, re.IGNORECASE)
        if not m2:
            return None
        m = m2
    num = float(m.group(1))
    mult = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[m.group(2).upper()]
    return int(round(num * mult))


# --------------------------------------------------------------------------- #
# Time-window helpers
# --------------------------------------------------------------------------- #

def parse_iso(dt_str: str) -> datetime:
    """Parse an ISO-8601 timestamp (Threads emits e.g. '2026-06-16T10:59:56.000Z') to UTC-aware."""
    s = dt_str.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_cutoff(now: Optional[datetime] = None, within_hours: float = 24) -> datetime:
    """The earliest timestamp still considered 'in window'."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - timedelta(hours=within_hours)


def within_window(dt: Optional[datetime], cutoff: datetime) -> bool:
    """True if dt is at/after the cutoff. Unknown timestamps (None) are kept (True)."""
    if dt is None:
        return True
    return dt >= cutoff


# --------------------------------------------------------------------------- #
# Config loading (env-first, file fallback)
# --------------------------------------------------------------------------- #

def load_credentials(config_path: Path = CREDENTIALS_PATH) -> Dict[str, Optional[str]]:
    """Load Threads login credentials.

    Priority: environment variables (THREADS_USERNAME / THREADS_PASSWORD) first, then
    config/credentials.json. Either may be absent — the reader prefers a saved session
    and only needs credentials for a fallback re-login. Returns dict with possibly-None values.
    """
    username = os.environ.get("THREADS_USERNAME")
    password = os.environ.get("THREADS_PASSWORD")

    if (not username or not password) and config_path.exists():
        try:
            data = json.loads(config_path.read_text())
            username = username or data.get("username") or data.get("THREADS_USERNAME")
            password = password or data.get("password") or data.get("THREADS_PASSWORD")
        except (json.JSONDecodeError, OSError):
            pass

    return {"username": username or None, "password": password or None}


def load_accounts(accounts_arg: Optional[str] = None, accounts_path: Path = ACCOUNTS_PATH) -> List[str]:
    """Resolve the list of usernames to read.

    A `--accounts a,b,c` CSV argument takes priority; otherwise read the "usernames"
    array from accounts.json. Normalizes and dedupes while preserving order.
    """
    raw: List[str] = []
    if accounts_arg:
        raw = accounts_arg.split(",")
    elif accounts_path.exists():
        try:
            data = json.loads(accounts_path.read_text())
            raw = data.get("usernames", []) if isinstance(data, dict) else list(data)
        except (json.JSONDecodeError, OSError):
            raw = []

    out: List[str] = []
    for item in raw:
        u = normalize_username(str(item))
        if u and u not in out:
            out.append(u)
    return out


# --------------------------------------------------------------------------- #
# Output assembly
# --------------------------------------------------------------------------- #

def assemble_output(
    results: Dict[str, List[Dict[str, Any]]],
    within_hours: float,
    cutoff: datetime,
    errors: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build the final JSON-serializable result document."""
    accounts: Dict[str, Any] = {}
    total = 0
    for username, posts in results.items():
        accounts[username] = {
            "username": username,
            "post_count": len(posts),
            "posts": posts,
        }
        total += len(posts)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "within_hours": within_hours,
        "cutoff": cutoff.isoformat(),
        "total_accounts": len(accounts),
        "total_posts": total,
        "accounts": accounts,
        "errors": errors or {},
    }


# --------------------------------------------------------------------------- #
# Browser-side extraction script (shared by record.py snapshots & the reader)
# --------------------------------------------------------------------------- #

# Injected via page.evaluate(...). Takes the profile username and returns a list of
# structured post dicts scraped from the currently-rendered DOM. Selectors are the
# ones verified during live DOM recon (see SKILL.md "Selectors").
POST_EXTRACTION_JS = r"""
(profileUsername) => {
  const norm = s => (s || '').replace(/^\/@?/, '').replace(/^@/, '').split('/')[0].trim().toLowerCase();
  const owner = norm(profileUsername);
  const containers = [...document.querySelectorAll('[data-pressable-container]')];
  const seen = new Set();
  const posts = [];

  for (const c of containers) {
    const permalinkEl = c.querySelector('a[href*="/post/"]');
    if (!permalinkEl) continue;
    const href = permalinkEl.getAttribute('href');
    const m = href.match(/\/post\/([^\/?#]+)/);
    if (!m) continue;
    const id = m[1];
    if (seen.has(id)) continue;
    seen.add(id);

    const timeEl = c.querySelector('time[datetime]');
    const datetime = timeEl ? timeEl.getAttribute('datetime') : null;
    const timeText = timeEl ? (timeEl.innerText || '').trim() : null;

    const authorEl = [...c.querySelectorAll('a[href^="/@"]')]
      .find(a => !a.getAttribute('href').includes('/post/'));
    const author = authorEl ? norm(authorEl.getAttribute('href')) : null;

    const metrics = {};
    for (const label of ['Like', 'Comment', 'Repost', 'Share']) {
      const svg = c.querySelector(`svg[aria-label="${label}"]`);
      if (svg) {
        const btn = svg.closest('[role="button"]') || svg.parentElement;
        metrics[label.toLowerCase()] = btn ? (btn.innerText || '').trim() : null;
      }
    }

    // Body text: dir="auto" spans that are not the timestamp, not inside a link
    // (author/mention chrome), and not inside a metric action button.
    const parts = [];
    for (const el of c.querySelectorAll('[dir="auto"]')) {
      if (el.closest('time')) continue;
      if (el.closest('a')) continue;
      const btn = el.closest('[role="button"]');
      if (btn && btn.querySelector('svg[aria-label]')) continue;
      const t = (el.innerText || '').trim();
      if (!t) continue;
      if (timeText && t === timeText) continue;            // the post's own timestamp chip
      if (author && t.toLowerCase() === author) continue;  // a bare author handle line
      parts.push(t);
    }
    const text = [...new Set(parts)].join('\n').trim();

    const firstLines = (c.innerText || '').split('\n').slice(0, 3);
    const repostBanner = firstLines.some(l => /reposted|pinned/i.test(l));
    const is_repost = !!repostBanner || (!!author && !!owner && author !== owner);

    const media = [];
    if (c.querySelector('video')) media.push('video');
    if (c.querySelector('img[src*="cdninstagram"], img[src*="fbcdn"]')) media.push('image');

    const truncated = [...c.querySelectorAll('[role="button"], span, div')]
      .some(e => /^(…\s*)?more$/i.test((e.innerText || '').trim()));

    posts.push({
      id,
      url: location.origin + href,
      author,
      datetime,
      is_repost,
      text,
      metrics,
      media,
      truncated,
    });
  }
  return posts;
}
"""
