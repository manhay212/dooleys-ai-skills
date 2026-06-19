# dooleys-threads-reader

Read recent posts from **Threads** (`threads.com`) accounts via **browser automation**.

Threads has no public read API, so this skill drives a headless **Chromium** browser with
**Playwright**, reusing a login session you capture once by hand. It's the Threads counterpart to
`dooleys-twitter-x-reader` — same config/output conventions, different transport (a real browser
instead of HTTP API calls).

## How it works — two scripts

```
record.py            you log in once in a visible browser  ──>  storage_state.json (saved session)
   │                 (also dumps page snapshots for selector work)
   ▼
threads_reader.py    headless: reads each account in accounts.json,  ──>  output_threads_reader.json
                     scrolls within a time window, returns JSON
```

- **`record.py`** — *human-run, one-time.* Opens a visible Chrome, you log in (clearing any 2FA),
  and it saves the authenticated session. Optionally snapshots pages (HTML + element map +
  screenshot) so selectors can be authored/repaired.
- **`threads_reader.py`** — *the automation.* Reuses the saved session, reads recent posts
  (originals + reposts; replies excluded) from your configured accounts, and writes JSON. Headless
  and cron-friendly.

## Features

- ✅ Reads any list of public Threads accounts (config-driven via `accounts.json`)
- ✅ Time-window parameter (`--within-hours`, e.g. last 24/48h) with reverse-chronological early-stop
- ✅ Saved-session auth (robust) + optional `.env` credential re-login fallback
- ✅ Aborts cleanly on 2FA/checkpoints instead of looping
- ✅ Extracts text, timestamp, permalink, author, repost flag, engagement metrics, media flags
- ✅ Per-account error isolation (one bad account doesn't sink the run)
- ✅ JSON output, env-first / file-fallback config (matches the Twitter skill)

## Installation

```bash
pip install -r requirements.txt
python -m playwright install chromium   # one-time: downloads the Chromium build
```

> The `python -m playwright install chromium` step is required — Playwright ships the driver but
> not the browser binary.

## Configuration

### 1. Accounts to read
```bash
cp accounts.json.example accounts.json
```
```json
{
  "usernames": ["zuck", "mosseri", "someaccount"]
}
```
(Leave off the `@`. You can also override per-run: `--accounts zuck,mosseri`.)

### 2. Credentials — optional, for the re-login fallback only

The reader prefers the saved session. Credentials are only used to re-login automatically if that
session expires. Provide them either way:

**Option A — environment variables (preferred; for Hermes use `~/.hermes/.env`):**
```bash
export THREADS_USERNAME=your_threads_username_or_email
export THREADS_PASSWORD=your_threads_password
```

**Option B — config file (standalone):**
```bash
cp config/credentials.example.json config/credentials.json
# edit it with your username/password
```

### 3. Capture the login session (one-time, by hand)
```bash
python3 record.py
```
Log in inside the browser window that opens (clear any 2FA prompt). Then return to the terminal and
type `q` + ENTER. This writes `storage_state.json`, which the reader reuses. Re-run this whenever the
session expires (typically weeks) or if you start hitting security checkpoints.

## Usage

```bash
# Read all accounts in accounts.json from the last 24 hours
python3 threads_reader.py --within-hours 24

# Specific accounts, last 48 hours
python3 threads_reader.py --accounts zuck,mosseri --within-hours 48

# Watch it run (visible browser) for debugging
python3 threads_reader.py --headed

# Skip the Search UI and go straight to /@user (more robust if search DOM shifts)
python3 threads_reader.py --nav-mode direct
```

Output is written to `output_threads_reader.json`.

---

## Testing — how to verify it works

The build ships with tests at three levels. Items marked **(no login)** work without your Threads
account; the last one needs your captured session.

### 1. Unit tests — pure logic, offline (no browser, no login)
```bash
python3 tests/test_threads_common.py
# or, if you have pytest: python3 -m pytest tests/ -q
```
Expected: `11/11 passed`. Covers username/URL normalization, count parsing (`"17.6K"`→`17600`),
time-window math, account/credential loading, and output assembly.

### 2. Session-error path — confirms graceful failure (no login)
With no `storage_state.json` and no credentials set:
```bash
env -u THREADS_USERNAME -u THREADS_PASSWORD python3 threads_reader.py --accounts zuck
```
Expected: a clear `SESSION ERROR` telling you to run `record.py`, and exit code `2`
(check with `echo $?`). This proves it won't hang or crash when unconfigured.

### 3. Live extraction smoke test — real scraping against a public profile (no login)
Public profiles render without login, so you can validate the scraping core before wiring up your
account. Save this as `smoke_test.py` and run it:
```python
import sys, json
sys.path.insert(0, ".")
import threads_common as tc, threads_reader as tr
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(user_agent=tr.USER_AGENT, viewport={"width": 1280, "height": 1600})
    page = ctx.new_page()
    tr._open_profile(page, "zuck", "direct")
    posts = tr._scrape_profile(page, "zuck", tc.compute_cutoff(within_hours=24 * 365), max_scrolls=2)
    print(f"scraped {len(posts)} posts")
    print(json.dumps(posts[0], indent=2, ensure_ascii=False) if posts else "no posts")
    ctx.close(); b.close()
```
```bash
python3 smoke_test.py
```
Expected: a couple dozen posts, each with `text`, `datetime`, `metrics`, `url`. If you get `0`
posts, Threads may have changed its DOM — re-run `record.py`, snapshot a profile, and update the
selectors in `threads_common.py` (see the "Selectors" section of `SKILL.md`).

### 4. Full end-to-end — your account, the real thing (needs login)
```bash
python3 record.py                                   # log in by hand, save the session
cp accounts.json.example accounts.json              # edit with accounts you care about
python3 threads_reader.py --within-hours 48 --headed
cat output_threads_reader.json
```
`--headed` lets you watch it search each account and scroll. Once happy, drop `--headed` for
unattended/cron runs.

---

## Output Format

```json
{
  "timestamp": "2026-06-19T14:00:00+00:00",
  "within_hours": 24,
  "cutoff": "2026-06-18T14:00:00+00:00",
  "total_accounts": 2,
  "total_posts": 7,
  "accounts": {
    "zuck": {
      "username": "zuck",
      "post_count": 1,
      "posts": [
        {
          "id": "DZpPDXbCeTt",
          "url": "https://www.threads.com/@zuck/post/DZpPDXbCeTt",
          "author": "zuck",
          "datetime": "2026-06-16T10:59:56.000Z",
          "is_repost": false,
          "text": "500M monthly actives on Threads in less than 3 years...",
          "metrics": { "like": 17600, "comment": 4700, "repost": 846, "share": 479 },
          "metrics_raw": { "like": "17.6K", "comment": "4.7K", "repost": "846", "share": "479" },
          "media": ["image"],
          "truncated": false
        }
      ]
    }
  },
  "errors": {}
}
```

## File Structure

```
dooleys-threads-reader/
├── SKILL.md                       # AI-agent instructions
├── README.md                      # this file
├── requirements.txt               # playwright
├── record.py                      # ① session/snapshot recorder (human-run)
├── threads_reader.py              # ② the automation (headless)
├── threads_common.py              # shared logic: config, time math, extraction JS
├── accounts.json.example          # template list of usernames
├── config/
│   └── credentials.example.json   # credentials template (fallback re-login)
├── tests/
│   └── test_threads_common.py     # offline unit tests
├── .gitignore
│
│  # generated / never committed:
├── storage_state.json             # saved session (from record.py)
├── recordings/                    # scratch page snapshots (from record.py)
└── output_threads_reader.json     # run output
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `SESSION ERROR ... No saved session` | Run `python3 record.py` to capture a session. |
| `2FA/security checkpoint` message | Run `python3 record.py` and clear the challenge by hand. |
| Smoke test scrapes `0` posts | Threads DOM likely changed — re-snapshot via `record.py` and update selectors in `threads_common.py`. |
| `record.py` errors about no display | It needs a desktop session; run it on the laptop's screen, not headless SSH. |
| One account shows up under `errors` | It may be private, renamed, or have no recent posts — the run continues for the others. |
| Browser missing | `python -m playwright install chromium`. |

## Security

- **Never commit** `storage_state.json` (it's a live session), `config/credentials.json`, or
  `recordings/` — all are in `.gitignore`.
- The saved session grants account access; treat `storage_state.json` like a password.
- Use a window/account list that keeps usage modest and unobtrusive.

## Dependencies

- **playwright** (>=1.40) + a Chromium build (`python -m playwright install chromium`).

## Changelog

### 1.0.0
- Initial release: `record.py` (session + snapshot capture) and `threads_reader.py`
  (search-driven, time-windowed reader). Saved-session auth with `.env` re-login fallback,
  per-account error isolation, JSON output, offline unit tests.
