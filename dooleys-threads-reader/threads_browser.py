"""Shared Playwright browser/session helpers for dooleys-threads-reader.

Both `threads_reader.py` (profile feeds) and `threads_posts.py` (post permalinks) need the
same things: a Chromium context wired to the saved session, a logged-in check, and a
session-ensure step with a credential re-login fallback that aborts cleanly on 2FA. They
live here so there's one implementation.

`threads_common.py` stays browser-free (fast offline unit tests); this module is the
Playwright-dependent layer.
"""
from __future__ import annotations

import sys
from typing import Optional

import threads_common as tc

try:
    from playwright.sync_api import TimeoutError as PWTimeout
except ImportError:
    sys.exit(
        "Playwright is not installed. Run:\n"
        "  pip install -r requirements.txt\n"
        "  python -m playwright install chromium"
    )

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class SessionError(RuntimeError):
    """Raised when we cannot establish an authenticated session."""


def require_auth_material() -> None:
    """Fail early (before launching a browser) if there's no way to authenticate."""
    creds = tc.load_credentials()
    if not tc.STORAGE_STATE_PATH.exists() and not (creds["username"] and creds["password"]):
        raise SessionError(
            "No saved session (storage_state.json) and no credentials found.\n"
            "Fix: run `python3 record.py` to log in once and capture a session,\n"
            "or set THREADS_USERNAME / THREADS_PASSWORD."
        )


def new_context(playwright, headed: bool = False, viewport: Optional[dict] = None):
    """Launch a Chromium browser + context wired to the saved session (if any)."""
    storage_arg = str(tc.STORAGE_STATE_PATH) if tc.STORAGE_STATE_PATH.exists() else None
    browser = playwright.chromium.launch(headless=not headed)
    context = browser.new_context(
        storage_state=storage_arg,
        viewport=viewport or {"width": 1280, "height": 1600},
        user_agent=USER_AGENT,
    )
    return browser, context


def is_logged_in(page) -> bool:
    """Detect auth state reliably.

    Logged-OUT pages carry a login affordance — the username input (on /login) and/or a
    link to `/login` plus a "Continue with Instagram" button (on home/profile pages).
    Logged-in pages have none of these. (The username-input-only check used to false-
    positive on public pages, which don't force the form.)
    """
    try:
        logged_out = (
            page.locator('input[autocomplete="username"]').count() > 0
            or page.locator('a[href*="/login"]').count() > 0
        )
        return not logged_out
    except Exception:
        return False


def attempt_login(page, creds: dict) -> None:
    """Best-effort headless re-login. Raises SessionError on challenge/failure."""
    if not creds.get("username") or not creds.get("password"):
        raise SessionError(
            "Saved session is invalid/expired and no credentials are available to re-login.\n"
            "Fix: run `python3 record.py` to log in by hand and refresh storage_state.json,\n"
            "or set THREADS_USERNAME / THREADS_PASSWORD (in ~/.hermes/.env or config/credentials.json)."
        )

    page.goto(tc.LOGIN_URL, wait_until="domcontentloaded")
    try:
        page.fill('input[autocomplete="username"]', creds["username"], timeout=15000)
        page.fill('input[autocomplete="current-password"]', creds["password"], timeout=15000)
        # The visible submit is a button labelled "Log in".
        page.get_by_role("button", name="Log in").first.click(timeout=15000)
    except PWTimeout as e:
        raise SessionError(f"Login form did not behave as expected: {e}")

    page.wait_for_timeout(6000)

    url = page.url.lower()
    if any(k in url for k in ("challenge", "checkpoint", "two_factor", "2fa")):
        raise SessionError(
            "Threads presented a 2FA/security checkpoint that automation cannot clear.\n"
            "Fix: run `python3 record.py`, clear the challenge by hand, and it will save a fresh session."
        )
    if not is_logged_in(page):
        raise SessionError(
            "Login did not succeed (still logged out). Credentials may be wrong, or a challenge appeared.\n"
            "Fix: run `python3 record.py` to log in by hand."
        )


def ensure_session(context, page, creds: dict) -> None:
    """Confirm we're logged in; re-login from creds if not. Persists a refreshed session."""
    page.goto(tc.THREADS_BASE, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    if is_logged_in(page):
        return
    print("  session not active -> attempting re-login from credentials...")
    attempt_login(page, creds)
    try:
        context.storage_state(path=str(tc.STORAGE_STATE_PATH))
        print("  re-login OK; refreshed storage_state.json")
    except Exception:
        pass


def wait_for_feed(page, timeout: int = 15000) -> None:
    """Wait for the JS-rendered post containers to appear. Tolerant of zero-post pages."""
    try:
        page.wait_for_selector("[data-pressable-container]", timeout=timeout)
    except PWTimeout:
        pass
    page.wait_for_timeout(1500)
