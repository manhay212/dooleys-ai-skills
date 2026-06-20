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

def normalize_post_metrics(post: Dict[str, Any]) -> Dict[str, Any]:
    """In-place: keep the raw metric strings under `metrics_raw` and parse `metrics` to ints."""
    metrics = post.get("metrics") or {}
    post["metrics_raw"] = metrics
    post["metrics"] = {k: parse_count(v) for k, v in metrics.items()}
    return post


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
# Post-link parsing (for threads_posts.py)
# --------------------------------------------------------------------------- #

POST_LINKS_PATH = SKILL_DIR / "post_links.json"


def parse_post_ref(value: str) -> Optional[Dict[str, str]]:
    """Parse a Threads post reference into {author, code, url}.

    Accepts a full URL (`https://www.threads.com/@zuck/post/DZpPDXbCeTt?x=1`), a bare
    path (`/@zuck/post/DZpPDXbCeTt`), or the same with `threads.net`. Returns None if no
    `/@author/post/code` pattern is found (a code alone can't be resolved — author is
    needed to build the URL).
    """
    if not value:
        return None
    s = value.strip()
    m = re.search(r"/@([^/?#\s]+)/post/([^/?#\s]+)", s)
    if not m:
        return None
    author, code = m.group(1).lower(), m.group(2)
    return {"author": author, "code": code, "url": f"{THREADS_BASE}/@{author}/post/{code}"}


def load_post_urls(
    urls_arg: Optional[str] = None,
    positional: Optional[List[str]] = None,
    links_path: Path = POST_LINKS_PATH,
) -> List[Dict[str, str]]:
    """Resolve the post references to read, as a list of {author, code, url} dicts.

    Priority: `--urls` CSV and/or positional args (combined) win; otherwise read the
    "urls" array from post_links.json. Invalid entries are skipped; duplicates (by code)
    are removed, order preserved.
    """
    raw: List[str] = []
    if urls_arg:
        raw.extend(urls_arg.split(","))
    if positional:
        raw.extend(positional)
    if not raw and links_path.exists():
        try:
            data = json.loads(links_path.read_text())
            raw = data.get("urls", []) if isinstance(data, dict) else list(data)
        except (json.JSONDecodeError, OSError):
            raw = []

    out: List[Dict[str, str]] = []
    seen = set()
    for item in raw:
        ref = parse_post_ref(str(item))
        if ref and ref["code"] not in seen:
            seen.add(ref["code"])
            out.append(ref)
    return out


def assemble_posts_output(
    posts: List[Dict[str, Any]],
    requested: int,
    errors: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build the final JSON document for threads_posts.py."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_requested": requested,
        "total_fetched": len(posts),
        "posts": posts,
        "errors": errors or {},
    }


# --------------------------------------------------------------------------- #
# Browser-side extraction scripts
# --------------------------------------------------------------------------- #
#
# Two entry points share one container parser:
#   POST_EXTRACTION_JS      -> profile feeds (record.py snapshots & threads_reader.py)
#   POST_PAGE_EXTRACTION_JS -> a single post's permalink page (threads_posts.py)
# Selectors verified during live DOM recon (see SKILL.md "Selectors").

# Shared fragment: defines parsePost(container, ownerNorm) -> post dict (or null).
# Prepended to each entry-point function below.
_CONTAINER_PARSER_JS = r"""
const norm = s => (s || '').replace(/^\/@?/, '').replace(/^@/, '').split('/')[0].trim().toLowerCase();

function extractLinks(c) {
  // External links render as l.threads.com redirects with the real URL in ?u=.
  const out = [];
  for (const a of c.querySelectorAll('a[href]')) {
    let href = a.getAttribute('href');
    if (!href || href.startsWith('/') || href.startsWith('#')) continue;
    if (href.includes('l.threads.com') || href.includes('l.instagram.com')) {
      try {
        const u = new URL(href).searchParams.get('u');
        if (u) href = decodeURIComponent(u);
      } catch (e) { /* keep original */ }
    }
    if (!/^https?:\/\//i.test(href)) continue;
    try {
      const host = new URL(href).hostname;
      if (host.endsWith('threads.com') || host.endsWith('threads.net')) continue;
    } catch (e) { continue; }
    out.push(href);
  }
  return [...new Set(out)];
}

function parsePost(c, ownerNorm) {
  const permalinkEl = c.querySelector('a[href*="/post/"]');
  if (!permalinkEl) return null;
  const href = permalinkEl.getAttribute('href');
  const m = href.match(/\/post\/([^\/?#]+)/);
  if (!m) return null;
  const id = m[1];

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
  const is_repost = !!repostBanner || (!!author && !!ownerNorm && author !== ownerNorm);

  const media = [];
  if (c.querySelector('video')) media.push('video');
  if (c.querySelector('img[src*="cdninstagram"], img[src*="fbcdn"]')) media.push('image');

  const truncated = [...c.querySelectorAll('[role="button"], span, div')]
    .some(e => /^(…\s*)?more$/i.test((e.innerText || '').trim()));

  return {
    id,
    url: location.origin + href,
    author,
    datetime,
    is_repost,
    text,
    links: extractLinks(c),
    metrics,
    media,
    truncated,
  };
}
"""

# Each entry point is a single arrow-function EXPRESSION (Playwright evaluates a string
# as an expression and calls it with the single argument passed to page.evaluate). The
# shared parser declarations live inside each function body.

# Profile-feed extraction: arg = profile username; returns a deduped list of posts.
POST_EXTRACTION_JS = "(profileUsername) => {\n" + _CONTAINER_PARSER_JS + r"""
  const owner = norm(profileUsername);
  const seen = new Set();
  const posts = [];
  for (const c of document.querySelectorAll('[data-pressable-container]')) {
    const p = parsePost(c, owner);
    if (!p || seen.has(p.id)) continue;
    seen.add(p.id);
    posts.push(p);
  }
  return posts;
}"""

# Permalink-page extraction: arg = {focusCode, focusAuthor}; classifies every post on the
# page into the focused post, the author's own thread continuation, and replies.
POST_PAGE_EXTRACTION_JS = "(arg) => {\n" + _CONTAINER_PARSER_JS + r"""
  const focusCode = arg.focusCode;
  const owner = norm(arg.focusAuthor || '');
  const seen = new Set();
  let focus = null;
  const thread = [];
  const replies = [];
  for (const c of document.querySelectorAll('[data-pressable-container]')) {
    const p = parsePost(c, owner);
    if (!p || seen.has(p.id)) continue;
    seen.add(p.id);
    if (focusCode && p.id === focusCode) {
      focus = p;
    } else if (owner && p.author === owner) {
      thread.push(p);                 // author's own connected continuation
    } else {
      replies.push(p);
    }
  }
  // Fallback: if the focused post wasn't matched by code, take the first container.
  if (!focus) {
    const first = document.querySelector('[data-pressable-container]');
    if (first) focus = parsePost(first, owner);
  }
  return { focus, thread, replies };
}"""
