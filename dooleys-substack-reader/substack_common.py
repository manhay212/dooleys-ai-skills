"""Pure, network-free logic for the Substack reader.

Everything here is deterministic and unit-tested (see tests/test_substack_common.py):
config + URL parsing, profile -> publication resolution, time-window filtering, paywall
detection, HTML -> Markdown conversion, and assembling the normalized post records.

The actual HTTP lives in substack_client.py; the entry scripts (substack_reader.py /
substack_posts.py) wire the two together.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import html2text


# --------------------------------------------------------------------------- #
# Config / account-entry parsing
# --------------------------------------------------------------------------- #
def accounts_from_config(data: dict) -> list:
    """Pull the raw account-entry list out of an accounts.json-shaped dict."""
    if not isinstance(data, dict):
        return []
    return list(data.get("accounts") or [])


def normalize_account_entry(entry: str) -> dict:
    """Classify a single config entry as either a Substack @handle or a publication.

    Returns one of:
      {"kind": "handle", "handle": "<handle>"}            (a substack.com/@handle profile)
      {"kind": "publication", "subdomain": "<subdomain>"} (a <sub>.substack.com publication)

    Accepts bare handles ("cryptohayes", "@CryptoHayes"), profile URLs
    ("https://substack.com/@marcusjin"), and publication forms
    ("capitalcycle.substack.com", "https://capitalcycle.substack.com/archive").
    """
    raw = (entry or "").strip()
    if not raw:
        raise ValueError("empty account entry")

    # A *.substack.com host means a specific publication (NOT the substack.com/@ profile host).
    host = raw
    if "://" in raw or "/" in raw:
        parsed = urlparse(raw if "://" in raw else "//" + raw, scheme="https")
        host = (parsed.netloc or "").lower()
        path = parsed.path or ""
        # Profile URL form: substack.com/@handle
        m = re.search(r"/@([A-Za-z0-9_-]+)", path)
        if host in ("substack.com", "www.substack.com") and m:
            return {"kind": "handle", "handle": m.group(1).lower()}
    else:
        host = raw.lower()

    if host.endswith(".substack.com"):
        subdomain = host[: -len(".substack.com")]
        if subdomain and subdomain not in ("www",):
            return {"kind": "publication", "subdomain": subdomain}

    # Fall back to treating it as a bare @handle.
    handle = raw.lstrip("@").strip().lower()
    handle = handle.split("/")[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", handle):
        raise ValueError(f"unrecognized account entry: {entry!r}")
    return {"kind": "handle", "handle": handle}


# --------------------------------------------------------------------------- #
# Profile -> publications
# --------------------------------------------------------------------------- #
def _pub_summary(pub: dict) -> dict | None:
    if not isinstance(pub, dict):
        return None
    sub = pub.get("subdomain")
    if not sub:
        return None
    return {"id": pub.get("id"), "subdomain": sub, "name": pub.get("name")}


def publications_from_profile(profile: dict) -> list:
    """Return all publications a profile authors, primary first, de-duplicated by subdomain.

    Reads `primaryPublication` and every `publicationUsers[].publication` from a
    /api/v1/user/<handle>/public_profile response.
    """
    out: list = []
    seen: set = set()

    def _add(pub):
        s = _pub_summary(pub)
        if s and s["subdomain"] not in seen:
            seen.add(s["subdomain"])
            out.append(s)

    if isinstance(profile, dict):
        _add(profile.get("primaryPublication") or {})
        for pu in profile.get("publicationUsers") or []:
            if isinstance(pu, dict):
                _add(pu.get("publication") or {})
    return out


# --------------------------------------------------------------------------- #
# Post URL parsing (for the by-link reader)
# --------------------------------------------------------------------------- #
def parse_post_url(url: str) -> dict | None:
    """Parse a Substack post URL into {subdomain, slug, url}, or None if it isn't one.

    Valid form: https://<subdomain>.substack.com/p/<slug>[?...]
    """
    if not url or "://" not in str(url):
        return None
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if not host.endswith(".substack.com"):
        return None
    subdomain = host[: -len(".substack.com")]
    if not subdomain or subdomain == "www":
        return None
    m = re.match(r"/p/([A-Za-z0-9_-]+)", parsed.path or "")
    if not m:
        return None
    return {"subdomain": subdomain, "slug": m.group(1),
            "url": f"https://{host}{parsed.path}"}


# --------------------------------------------------------------------------- #
# Time window
# --------------------------------------------------------------------------- #
def compute_cutoff(now: datetime, within_hours: float) -> datetime:
    return now - timedelta(hours=within_hours)


def parse_post_date(value) -> datetime | None:
    """Parse Substack's ISO-8601 `post_date` (e.g. '2026-06-17T13:00:46.272Z') to aware UTC."""
    if not value or not isinstance(value, str):
        return None
    s = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def filter_posts_by_window(posts: list, cutoff: datetime) -> list:
    """Keep posts whose post_date is at or after `cutoff`; drop unparseable/older ones."""
    kept = []
    for p in posts or []:
        dt = parse_post_date(p.get("post_date") if isinstance(p, dict) else None)
        if dt is not None and dt >= cutoff:
            kept.append(p)
    return kept


# --------------------------------------------------------------------------- #
# HTML -> Markdown + word count
# --------------------------------------------------------------------------- #
def html_to_markdown(html: str) -> str:
    """Convert post body_html to readable Markdown (links preserved, no hard wrapping)."""
    if not html:
        return ""
    h = html2text.HTML2Text()
    h.body_width = 0          # don't hard-wrap paragraphs
    h.ignore_images = True    # images add noise for a text-consuming agent
    h.ignore_emphasis = False
    h.protect_links = True
    md = h.handle(html)
    # Drop empty links left behind by ignored images (Substack wraps images in <a>),
    # e.g. "[](<https://substackcdn.com/...>)" or "[](url)" with no link text.
    md = re.sub(r"\[\]\(<[^>]*>\)", "", md)
    md = re.sub(r"\[\]\([^)]*\)", "", md)
    # Collapse runs of blank lines and trailing spaces.
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def count_words(text: str) -> int:
    if not text:
        return 0
    return len(text.split())


# --------------------------------------------------------------------------- #
# Paywall detection + record assembly
# --------------------------------------------------------------------------- #
def is_paid_audience(post: dict) -> bool:
    """True when a post is restricted to paying subscribers (audience != everyone)."""
    aud = post.get("audience")
    return aud not in (None, "", "everyone")


def is_truncated(post: dict) -> bool:
    """True when the API only returned a teaser (we're unauthenticated on a paid post)."""
    return bool(post.get("should_show_paywall"))


def build_post_record(post: dict, subdomain: str) -> dict:
    """Normalize a Substack post JSON object into our compact output record."""
    body_html = post.get("body_html") or ""
    text = html_to_markdown(body_html)
    url = post.get("canonical_url") or (
        f"https://{subdomain}.substack.com/p/{post.get('slug')}" if post.get("slug") else None)
    return {
        "id": post.get("id"),
        "title": post.get("title"),
        "subtitle": post.get("subtitle"),
        "url": url,
        "publication": subdomain,
        "slug": post.get("slug"),
        "post_date": post.get("post_date"),
        "audience": post.get("audience"),
        "is_paywalled": is_paid_audience(post),
        "truncated": is_truncated(post),
        "word_count": count_words(text),
        "text": text,
    }
