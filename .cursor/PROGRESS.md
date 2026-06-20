# Project Progress Tracker

One concise block per skill. Source of truth is the repo + root `CLAUDE.md`; this is a log.

## Skills

- **dooleys-twitter-x-reader** — Twitter/X API v2 reader (user tweets, home timeline, by-id).
  - Status: built (v1.2.0).
  - Notes: API flavor; direct `requests` (no SDK); env-first creds; reference for HTTP skills.

- **dooleys-threads-reader** — Threads (threads.com) reader via Playwright (no public API).
  - Status: built v1.0.0 (2026-06-19); v1.1.0 by-link reader added (2026-06-20).
  - Notes: Browser flavor. Scripts — `record.py` (human-run: captures `storage_state.json` session
    + page snapshots), `threads_reader.py` (headless: search each account in `accounts.json`,
    scrape originals+reposts within `--within-hours`), and `threads_posts.py` (headless: read
    specific posts by link — full untruncated text + author thread + optional `--with-replies`).
    Shared: `threads_browser.py` (session/auth), `threads_common.py` (pure logic, 18 unit tests).
    Auth = saved session + `.env` re-login fallback; hardened logged-in check (login-link signal)
    so expiry triggers re-login; aborts on 2FA. Adds `links` (decoded `l.threads.com` redirects)
    per post. Selectors verified via live DOM recon, documented in `SKILL.md`. Tested: unit,
    no-session error path, live smoke (profile + by-link), and authenticated end-to-end (both
    readers). Reference for no-API browser-automation skills.

- **dooleys-market-data** — market-data ingestion engine (numbers → SQLite from free sources).
  - Status: built.
  - Notes: FRED/Stooq/EIA/CoinGecko/Treasury/Yahoo source adapters.

- **dooleys-feedback-learner** — extracts transferable principles from user corrections.
  - Status: built (v1.0.0).

## Conventions snapshot

- Entry points at the skill folder root (no `src/index.py`).
- Env-first / file-fallback credentials; never commit secrets or session state.
- Test before pushing; push net-new skill folders to `main`; don't touch other skills' folders.
- See `.cursor/rules/` and repo-root `CLAUDE.md` for the full guide.
