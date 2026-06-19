#!/usr/bin/env python3
"""record.py — the demo / session capturer for dooleys-threads-reader.

Threads has no public API and aggressively flags bot logins, so instead of teaching
the automation to fight the login flow we let a human do it once, by hand, in a real
visible browser. This script:

  1. Opens a visible Chromium window at threads.com (reusing any saved session).
  2. Lets you log in and navigate freely while it waits on the terminal.
  3. On ENTER, dumps the current page into recordings/NN_<label>/ as:
       - page.html        (raw rendered HTML)
       - elements.json    (a structured selector/element map: posts, timestamps,
                            search inputs, links — what Claude needs to author selectors)
       - screenshot.png   (visual reference)
  4. On 'q' + ENTER (or closing the browser), saves the authenticated session to
     storage_state.json — which threads_reader.py then reuses headlessly.

Usage:
    python3 record.py                 # full session: log in, navigate, snapshot, save session
    python3 record.py --no-snapshots  # just capture/refresh the session (login only)
    python3 record.py --url https://www.threads.com/search   # start at a specific page

The snapshots are scratch artifacts for selector authoring — delete recordings/ when done
(it is git-ignored and may contain handles you searched).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import threads_common as tc

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit(
        "Playwright is not installed. Run:\n"
        "  pip install -r requirements.txt\n"
        "  python -m playwright install chromium"
    )


# JS that builds the structured element map saved as elements.json. Deliberately broad:
# it surfaces the handful of selectors that matter for this skill so they can be eyeballed.
ELEMENT_MAP_JS = r"""
() => {
  const trim = s => (s || '').trim();
  const map = { url: location.href, title: document.title, captured_at: new Date().toISOString() };

  map.inputs = [...document.querySelectorAll('input, textarea, [contenteditable="true"]')].map(i => ({
    tag: i.tagName.toLowerCase(),
    type: i.getAttribute('type'),
    placeholder: i.getAttribute('placeholder'),
    autocomplete: i.getAttribute('autocomplete'),
    ariaLabel: i.getAttribute('aria-label'),
  }));

  map.buttons = [...new Set([...document.querySelectorAll('button, [role="button"]')]
    .map(b => trim(b.innerText)).filter(t => t && t.length < 40))].slice(0, 40);

  map.accountLinks = [...new Set([...document.querySelectorAll('a[href^="/@"]')]
    .map(a => a.getAttribute('href')).filter(h => h && !h.includes('/post/')))].slice(0, 30);

  map.postLinks = [...new Set([...document.querySelectorAll('a[href*="/post/"]')]
    .map(a => a.getAttribute('href')))].slice(0, 30);

  map.pressableContainers = document.querySelectorAll('[data-pressable-container]').length;

  map.times = [...document.querySelectorAll('time')].slice(0, 15).map(t => ({
    datetime: t.getAttribute('datetime'),
    title: t.getAttribute('title'),
    text: trim(t.innerText),
    permalink: t.closest('a') ? t.closest('a').getAttribute('href') : null,
  }));

  map.svgAriaLabels = [...new Set([...document.querySelectorAll('svg[aria-label]')]
    .map(s => s.getAttribute('aria-label')))].slice(0, 40);

  map.loginWall = !!document.querySelector('input[autocomplete="username"]');
  return map;
}
"""


def _snapshot(page, index: int, label: str) -> Path:
    """Persist HTML + element map + screenshot for the current page."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label) or "page"
    out_dir = tc.RECORDINGS_DIR / f"{index:02d}_{safe}"
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "page.html").write_text(page.content(), encoding="utf-8")

    element_map = page.evaluate(ELEMENT_MAP_JS)
    (out_dir / "elements.json").write_text(json.dumps(element_map, indent=2), encoding="utf-8")

    try:
        page.screenshot(path=str(out_dir / "screenshot.png"), full_page=False)
    except Exception as e:  # screenshots are best-effort
        print(f"  (screenshot skipped: {e})")

    return out_dir


def run(start_url: str, snapshots: bool) -> int:
    tc.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    storage_arg = str(tc.STORAGE_STATE_PATH) if tc.STORAGE_STATE_PATH.exists() else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            storage_state=storage_arg,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded")

        print("\n" + "=" * 70)
        print("Threads recorder is open. Log in and navigate by hand in the browser.")
        if snapshots:
            print("In THIS terminal:")
            print("  • type a label + ENTER  -> snapshot the current page to recordings/")
            print("  • just ENTER            -> snapshot with an auto label")
        print("  • type 'q' + ENTER       -> save session to storage_state.json and quit")
        print("=" * 70 + "\n")

        index = 1
        while True:
            try:
                raw = input("snapshot label (or 'q' to finish) > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if raw.lower() in {"q", "quit", "exit"}:
                break
            if not snapshots:
                print("  (snapshots disabled; type 'q' to finish)")
                continue
            label = raw or f"snapshot_{datetime.now(timezone.utc).strftime('%H%M%S')}"
            try:
                out_dir = _snapshot(page, index, label)
                print(f"  saved -> {out_dir.relative_to(tc.SKILL_DIR)}")
                index += 1
            except Exception as e:
                print(f"  snapshot failed: {e} (is the browser still open?)")

        # Persist the authenticated session for the reader.
        try:
            context.storage_state(path=str(tc.STORAGE_STATE_PATH))
            print(f"\nSession saved -> {tc.STORAGE_STATE_PATH.relative_to(tc.SKILL_DIR)}")
        except Exception as e:
            print(f"\nCould not save session (browser may have been closed): {e}")
            return 1
        finally:
            try:
                context.close()
                browser.close()
            except Exception:
                pass

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Record a Threads session + page snapshots.")
    ap.add_argument("--url", default=tc.LOGIN_URL, help="Starting URL (default: the login page).")
    ap.add_argument("--no-snapshots", action="store_true",
                    help="Only capture/refresh the login session; skip page snapshots.")
    args = ap.parse_args()
    return run(args.url, snapshots=not args.no_snapshots)


if __name__ == "__main__":
    sys.exit(main())
