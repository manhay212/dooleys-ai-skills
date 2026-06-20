#!/usr/bin/env python3
"""Read the full content of specific Substack posts by their URLs.

Give it one or more post URLs (https://<sub>.substack.com/p/<slug>) on the command line,
via --urls, or in post_links.json. It fetches each post's full content and writes
output_substack_posts.json. No authentication is used; paid posts are flagged
(`is_paywalled` / `truncated`) rather than reported as complete.

Examples:
    python3 substack_posts.py https://cryptohayes.substack.com/p/reality-test
    python3 substack_posts.py --urls "https://a.substack.com/p/x,https://b.substack.com/p/y"
    python3 substack_posts.py                       # read post_links.json

Exit codes: 0 success · 1 no valid post URLs.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import substack_common as sc
from substack_client import SubstackClient, SubstackError

HERE = Path(__file__).resolve().parent
DEFAULT_LINKS = HERE / "post_links.json"
DEFAULT_OUTPUT = HERE / "output_substack_posts.json"


def _resolve_urls(args) -> list:
    raw: list = list(args.urls_positional or [])
    if args.urls:
        raw += [u.strip() for u in args.urls.split(",") if u.strip()]
    if not raw:
        path = Path(args.links_file)
        if path.exists():
            with path.open(encoding="utf-8") as f:
                raw = list((json.load(f) or {}).get("urls") or [])
    # Parse + de-dup, preserving order.
    seen, parsed = set(), []
    for u in raw:
        p = sc.parse_post_url(u)
        if p and p["url"] not in seen:
            seen.add(p["url"])
            parsed.append(p)
    return parsed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read specific Substack posts by URL.")
    ap.add_argument("urls_positional", nargs="*", help="Post URLs.")
    ap.add_argument("--urls", default=None, help="Comma-separated post URLs.")
    ap.add_argument("--links-file", default=str(DEFAULT_LINKS),
                    help="Path to post_links.json (default: alongside this script).")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output JSON path.")
    args = ap.parse_args(argv)

    links = _resolve_urls(args)
    if not links:
        print("No valid Substack post URLs. Pass URLs, --urls, or fill post_links.json.",
              file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    client = SubstackClient()
    posts, errors = [], {}

    for link in links:
        try:
            full = client.get_post(link["subdomain"], link["slug"])
        except SubstackError as e:
            errors[link["url"]] = str(e)
            continue
        rec = sc.build_post_record(full, link["subdomain"])
        rec["requested_url"] = link["url"]
        posts.append(rec)

    result = {
        "timestamp": now.isoformat(),
        "total_requested": len(links),
        "total_fetched": len(posts),
        "posts": posts,
        "errors": errors,
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print(f"Wrote {args.output}: {len(posts)}/{len(links)} post(s) fetched."
          + (f" {len(errors)} error(s)." if errors else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
