#!/usr/bin/env python3
"""threads_reader.py — the unattended Threads scraper for dooleys-threads-reader.

Reads recent posts from a configured list of Threads accounts and writes them to JSON.
There is no Threads API, so this drives a headless Chromium via Playwright, reusing the
authenticated session captured by record.py.

Flow per run:
  1. Load storage_state.json (the saved session). Open threads.com and confirm we are
     logged in. If the session is dead and THREADS_USERNAME/THREADS_PASSWORD are available,
     attempt one headless re-login; if a 2FA/checkpoint appears, abort with guidance to
     re-run record.py (we never loop on a challenge).
  2. For each account: navigate via Search (/search?q=USER) and open the matching profile
     (falling back to the direct /@USER URL if the search result isn't found).
  3. Scroll the profile, collecting originals + reposts (replies are excluded — they live
     on a separate tab), until posts fall outside the --within-hours window or the feed
     stops growing.
  4. Write output_threads_reader.json.

Usage:
    python3 threads_reader.py --within-hours 24
    python3 threads_reader.py --accounts zuck,mosseri --within-hours 48
    python3 threads_reader.py --headed            # watch it run, for debugging
    python3 threads_reader.py --nav-mode direct   # skip Search, go straight to /@user
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import threads_common as tc

try:
    from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright
except ImportError:
    sys.exit(
        "Playwright is not installed. Run:\n"
        "  pip install -r requirements.txt\n"
        "  python -m playwright install chromium"
    )

import threads_browser as tb
from threads_browser import SessionError  # re-exported for callers/back-compat


# --------------------------------------------------------------------------- #
# Navigation + scraping
# --------------------------------------------------------------------------- #

def _open_profile(page, username: str, nav_mode: str) -> None:
    """Land on the account's profile. Honors Search-first, with direct-URL fallback."""
    profile_url = f"{tc.THREADS_BASE}/@{username}"

    if nav_mode == "search":
        page.goto(f"{tc.THREADS_BASE}/search?q={username}", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        link = page.locator(f'a[href="/@{username}"]').first
        try:
            if link.count() > 0:
                link.click(timeout=8000)
                page.wait_for_url(f"**/@{username}**", timeout=10000)
                tb.wait_for_feed(page)
                return
        except PWTimeout:
            pass  # fall through to direct navigation

    page.goto(profile_url, wait_until="domcontentloaded")
    tb.wait_for_feed(page)


def _scrape_profile(page, username: str, cutoff, max_scrolls: int) -> list:
    """Scroll the profile, collecting in-window posts authored/reposted by the account."""
    collected: dict = {}
    stale_rounds = 0

    for _ in range(max_scrolls):
        raw_posts = page.evaluate(tc.POST_EXTRACTION_JS, username)
        before = len(collected)
        reached_old = False

        for post in raw_posts:
            pid = post.get("id")
            if not pid or pid in collected:
                continue
            dt = tc.parse_iso(post["datetime"]) if post.get("datetime") else None
            if not tc.within_window(dt, cutoff):
                # Feed is reverse-chronological: an in-window-failing post means we're
                # past the window for this account.
                reached_old = True
                continue
            tc.normalize_post_metrics(post)  # raw strings -> ints (+ metrics_raw)
            collected[pid] = post

        if reached_old:
            break

        # Stop if scrolling stops yielding new in-window posts.
        if len(collected) == before:
            stale_rounds += 1
            if stale_rounds >= 3:
                break
        else:
            stale_rounds = 0

        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        page.wait_for_timeout(2200)

    # Return newest-first for readability.
    posts = list(collected.values())
    posts.sort(key=lambda p: p.get("datetime") or "", reverse=True)
    return posts


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def read_accounts(usernames, within_hours, headed, nav_mode, max_scrolls):
    cutoff = tc.compute_cutoff(within_hours=within_hours)
    creds = tc.load_credentials()
    results: dict = {}
    errors: dict = {}

    tb.require_auth_material()  # raises SessionError if nothing to authenticate with

    with sync_playwright() as p:
        browser, context = tb.new_context(p, headed=headed)
        page = context.new_page()

        tb.ensure_session(context, page, creds)  # raises SessionError on failure

        for username in usernames:
            print(f"  reading @{username} ...")
            try:
                _open_profile(page, username, nav_mode)
                if not tb.is_logged_in(page) and page.locator('[data-pressable-container]').count() == 0:
                    errors[username] = "no posts found / profile not accessible"
                    results[username] = []
                    continue
                posts = _scrape_profile(page, username, cutoff, max_scrolls)
                results[username] = posts
                print(f"    -> {len(posts)} post(s) in window")
            except Exception as e:  # one bad account shouldn't sink the run
                errors[username] = f"{type(e).__name__}: {e}"
                results[username] = []
                print(f"    -> error: {e}")

        context.close()
        browser.close()

    return tc.assemble_output(results, within_hours, cutoff, errors)


def main() -> int:
    ap = argparse.ArgumentParser(description="Read recent posts from configured Threads accounts.")
    ap.add_argument("--within-hours", type=float, default=24,
                    help="Capture posts from the last N hours (default: 24).")
    ap.add_argument("--accounts", default=None,
                    help="Comma-separated usernames; overrides accounts.json.")
    ap.add_argument("--nav-mode", choices=["search", "direct"], default="search",
                    help="How to reach each profile (default: search, per spec).")
    ap.add_argument("--headed", action="store_true", help="Show the browser (debugging).")
    ap.add_argument("--max-scrolls", type=int, default=25,
                    help="Safety cap on scroll iterations per account (default: 25).")
    ap.add_argument("--output", default=str(tc.OUTPUT_PATH), help="Output JSON path.")
    args = ap.parse_args()

    usernames = tc.load_accounts(args.accounts)
    if not usernames:
        print("No accounts to read. Add usernames to accounts.json or pass --accounts a,b,c.")
        return 1

    print(f"Reading {len(usernames)} account(s), window={args.within_hours}h, nav={args.nav_mode}")
    try:
        output = read_accounts(
            usernames, args.within_hours, args.headed, args.nav_mode, args.max_scrolls
        )
    except SessionError as e:
        print(f"\nSESSION ERROR:\n{e}")
        return 2

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {output['total_posts']} post(s) across {output['total_accounts']} "
          f"account(s) -> {args.output}")
    if output["errors"]:
        print(f"Errors: {output['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
