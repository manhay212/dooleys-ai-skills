#!/usr/bin/env python3
"""threads_posts.py — read specific Threads posts by their links.

Companion to threads_reader.py. Where the reader walks an account's profile feed (which
Threads caps at ~7-10 posts before infinite scroll stalls), this script takes **post
permalinks you already have** and reads each one directly. A post's own permalink page also
gives you the **full untruncated text** and the author's **thread continuation** — things
the profile feed doesn't surface.

Give it one or many post links (the agent typically passes them on the command line):

    python3 threads_posts.py https://www.threads.com/@zuck/post/DZpPDXbCeTt
    python3 threads_posts.py --urls "https://www.threads.com/@zuck/post/AAA,https://www.threads.com/@mosseri/post/BBB"
    python3 threads_posts.py            # reads post_links.json ({"urls": [...]})
    python3 threads_posts.py URL --with-replies   # also capture other people's replies

For each link it returns the focused post, the author's connected thread (same-author posts
on the page), and — only with --with-replies — replies from others. Output: output_threads_posts.json.
"""
from __future__ import annotations

import argparse
import json
import sys

import threads_common as tc
import threads_browser as tb

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit(
        "Playwright is not installed. Run:\n"
        "  pip install -r requirements.txt\n"
        "  python -m playwright install chromium"
    )


def _open_post(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    tb.wait_for_feed(page)


def _read_one(page, ref: dict, with_replies: bool, reply_scrolls: int) -> dict:
    """Extract one post page into {requested_url, focus fields..., thread, replies}."""
    _open_post(page, ref["url"])

    data = page.evaluate(
        tc.POST_PAGE_EXTRACTION_JS, {"focusCode": ref["code"], "focusAuthor": ref["author"]}
    )
    focus = data.get("focus")
    if not focus:
        raise RuntimeError("post not found on page (deleted, private, or DOM changed)")

    tc.normalize_post_metrics(focus)
    thread = [tc.normalize_post_metrics(p) for p in (data.get("thread") or [])]
    thread.sort(key=lambda p: p.get("datetime") or "")

    replies = []
    if with_replies:
        collected = {p["id"]: p for p in (data.get("replies") or [])}
        for _ in range(reply_scrolls):
            page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            more = page.evaluate(
                tc.POST_PAGE_EXTRACTION_JS,
                {"focusCode": ref["code"], "focusAuthor": ref["author"]},
            )
            before = len(collected)
            for p in more.get("replies") or []:
                collected.setdefault(p["id"], p)
            if len(collected) == before:
                break
        replies = [tc.normalize_post_metrics(p) for p in collected.values()]
        replies.sort(key=lambda p: p.get("datetime") or "")

    # Shape: focus fields at the top level, with thread/replies nested.
    out = dict(focus)
    out["requested_url"] = ref["url"]
    out["thread"] = thread
    out["replies"] = replies
    return out


def read_posts(refs, with_replies, headed, reply_scrolls):
    creds = tc.load_credentials()
    posts = []
    errors = {}

    tb.require_auth_material()  # raises SessionError if nothing to authenticate with

    with sync_playwright() as p:
        browser, context = tb.new_context(p, headed=headed)
        page = context.new_page()

        tb.ensure_session(context, page, creds)  # raises SessionError on failure

        for ref in refs:
            print(f"  reading post {ref['url']} ...")
            try:
                post = _read_one(page, ref, with_replies, reply_scrolls)
                posts.append(post)
                extra = f" (+{len(post['thread'])} thread, +{len(post['replies'])} replies)" if (
                    post["thread"] or post["replies"]
                ) else ""
                print(f"    -> ok{extra}")
            except Exception as e:  # one bad link shouldn't sink the run
                errors[ref["url"]] = f"{type(e).__name__}: {e}"
                print(f"    -> error: {e}")

        context.close()
        browser.close()

    return tc.assemble_posts_output(posts, requested=len(refs), errors=errors)


def main() -> int:
    ap = argparse.ArgumentParser(description="Read specific Threads posts by their links.")
    ap.add_argument("urls", nargs="*", help="Post URLs/permalinks (space-separated).")
    ap.add_argument("--urls", dest="urls_csv", default=None,
                    help="Comma-separated post URLs (alternative to positional args).")
    ap.add_argument("--with-replies", action="store_true",
                    help="Also capture replies from other accounts (default: off).")
    ap.add_argument("--reply-scrolls", type=int, default=3,
                    help="When --with-replies, how many times to scroll for more (default: 3).")
    ap.add_argument("--headed", action="store_true", help="Show the browser (debugging).")
    ap.add_argument("--output", default=str(tc.SKILL_DIR / "output_threads_posts.json"),
                    help="Output JSON path.")
    args = ap.parse_args()

    refs = tc.load_post_urls(args.urls_csv, positional=args.urls)
    if not refs:
        print("No valid post links. Pass URLs as arguments, use --urls, or fill post_links.json.\n"
              "Expected form: https://www.threads.com/@username/post/SHORTCODE")
        return 1

    print(f"Reading {len(refs)} post(s), with_replies={args.with_replies}")
    try:
        output = read_posts(refs, args.with_replies, args.headed, args.reply_scrolls)
    except tb.SessionError as e:
        print(f"\nSESSION ERROR:\n{e}")
        return 2

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nFetched {output['total_fetched']}/{output['total_requested']} post(s) -> {args.output}")
    if output["errors"]:
        print(f"Errors: {output['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
