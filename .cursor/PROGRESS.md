# Project Progress Tracker

One concise block per skill. Source of truth is the repo + root `CLAUDE.md`; this is a log.

## Skills

- **dooleys-twitter-x-reader** — Twitter/X API v2 reader (user tweets, home timeline, by-id).
  - Status: built (v1.2.0).
  - Notes: API flavor; direct `requests` (no SDK); env-first creds; reference for HTTP skills.

- **dooleys-threads-reader** — Threads (threads.com) reader via Playwright (no public API).
  - Status: built (v1.0.0), 2026-06-19.
  - Notes: Browser flavor. Two scripts — `record.py` (human-run: captures `storage_state.json`
    session + page snapshots) and `threads_reader.py` (headless: search each account in
    `accounts.json`, scrape originals+reposts within `--within-hours`, output JSON). Shared logic
    in `threads_common.py` (unit-tested, 11 tests). Selectors verified via live DOM recon and
    documented in `SKILL.md`. Auth = saved session + `.env` re-login fallback, aborts on 2FA.
    Tested: unit tests, no-session error path, live smoke scrape of a public profile.
    Reference for no-API browser-automation skills.

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
