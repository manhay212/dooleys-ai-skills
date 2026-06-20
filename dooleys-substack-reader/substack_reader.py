#!/usr/bin/env python3
"""Read recent Substack posts from monitored profiles.

For each account in accounts.json (a substack @handle, or a specific <sub>.substack.com
publication), this resolves the handle to ALL of its publications, lists each one's posts,
keeps those published within --within-hours, fetches each kept post's full content, and
writes a JSON briefing to output_substack_reader.json.

No authentication is used. Paid-subscriber posts are still listed but flagged
(`is_paywalled` / `truncated`) since their body comes back as a teaser when unauthenticated.

Examples:
    python3 substack_reader.py                          # accounts.json, last 48h
    python3 substack_reader.py --within-hours 168       # last 7 days
    python3 substack_reader.py --accounts cryptohayes,marcusjin
    python3 substack_reader.py --list-limit 20          # scan deeper per publication

Exit codes: 0 success · 1 no accounts configured · 2 fatal error before any account ran.
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
DEFAULT_ACCOUNTS = HERE / "accounts.json"
DEFAULT_OUTPUT = HERE / "output_substack_reader.json"


def _load_accounts(args) -> list:
    if args.accounts:
        return [a.strip() for a in args.accounts.split(",") if a.strip()]
    path = Path(args.accounts_file)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return sc.accounts_from_config(json.load(f))


def _resolve_publications(client: SubstackClient, entry: str) -> tuple[str, str, list]:
    """Return (key, display_name, publications[]) for one config entry."""
    target = sc.normalize_account_entry(entry)
    if target["kind"] == "publication":
        sub = target["subdomain"]
        return sub, sub, [{"id": None, "subdomain": sub, "name": None}]
    handle = target["handle"]
    profile = client.get_public_profile(handle)
    pubs = sc.publications_from_profile(profile)
    return handle, profile.get("name") or handle, pubs


def _collect_posts(client: SubstackClient, pubs: list, cutoff, list_limit: int,
                   pub_errors: dict) -> list:
    posts = []
    for pub in pubs:
        sub = pub["subdomain"]
        try:
            listed = client.list_posts(sub, limit=list_limit)
        except SubstackError as e:
            pub_errors[sub] = str(e)
            continue
        for stub in sc.filter_posts_by_window(listed, cutoff):
            slug = stub.get("slug")
            full = stub
            if slug:
                try:
                    full = client.get_post(sub, slug)  # authoritative full body
                except SubstackError:
                    full = stub  # fall back to the list payload (already has body_html)
            posts.append(sc.build_post_record(full, sub))
    posts.sort(key=lambda p: p.get("post_date") or "", reverse=True)
    return posts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read recent Substack posts from monitored profiles.")
    ap.add_argument("--within-hours", type=float, default=48.0,
                    help="Keep posts published within this many hours (default 48).")
    ap.add_argument("--accounts", default=None,
                    help="Comma-separated accounts override (handles or *.substack.com).")
    ap.add_argument("--accounts-file", default=str(DEFAULT_ACCOUNTS),
                    help="Path to accounts.json (default: alongside this script).")
    ap.add_argument("--list-limit", type=int, default=12,
                    help="How many recent posts to scan per publication (default 12).")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output JSON path.")
    args = ap.parse_args(argv)

    entries = _load_accounts(args)
    if not entries:
        print("No accounts configured. Add them to accounts.json or pass --accounts.",
              file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    cutoff = sc.compute_cutoff(now, args.within_hours)
    client = SubstackClient()

    accounts_out: dict = {}
    errors: dict = {}
    total_posts = 0

    for entry in entries:
        try:
            key, name, pubs = _resolve_publications(client, entry)
        except (SubstackError, ValueError) as e:
            errors[entry] = str(e)
            continue
        if not pubs:
            errors[entry] = "no publications found for this profile"
            continue
        pub_errors: dict = {}
        posts = _collect_posts(client, pubs, cutoff, args.list_limit, pub_errors)
        accounts_out[key] = {
            "handle": key,
            "name": name,
            "publications": [{"subdomain": p["subdomain"], "name": p.get("name")} for p in pubs],
            "post_count": len(posts),
            "posts": posts,
        }
        if pub_errors:
            accounts_out[key]["publication_errors"] = pub_errors
        total_posts += len(posts)

    result = {
        "timestamp": now.isoformat(),
        "within_hours": args.within_hours,
        "cutoff": cutoff.isoformat(),
        "total_accounts": len(accounts_out),
        "total_posts": total_posts,
        "accounts": accounts_out,
        "errors": errors,
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print(f"Wrote {args.output}: {total_posts} post(s) across {len(accounts_out)} account(s) "
          f"within {args.within_hours}h."
          + (f" {len(errors)} account error(s)." if errors else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
