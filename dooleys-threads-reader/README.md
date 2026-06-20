# dooleys-threads-reader

Read posts from **Threads** (`threads.com`) via **browser automation** — by **account** (recent
posts in a time window) or by **link** (the full content of specific posts you already have URLs for).

Threads has no public read API, so this skill drives a headless **Chromium** browser with
**Playwright**, reusing a login session you capture once by hand. It's the Threads counterpart to
`dooleys-twitter-x-reader` — same config/output conventions, different transport (a real browser
instead of HTTP API calls).

## How it works — three scripts

```
record.py            you log in once in a visible browser  ──>  storage_state.json (saved session)
   │                 (also dumps page snapshots for selector work)
   ├──────────────┐
   ▼              ▼
threads_reader.py  threads_posts.py
reads accounts by  reads specific posts by
username, within   their links (full text +
a time window      thread + optional replies)
   │              │
   ▼              ▼
output_threads_    output_threads_posts.json
reader.json
```

- **`record.py`** — *human-run, one-time.* Opens a visible Chrome, you log in (clearing any 2FA),
  and it saves the authenticated session. Optionally snapshots pages (HTML + element map +
  screenshot) so selectors can be authored/repaired.
- **`threads_reader.py`** — *automation, by username.* Reuses the saved session, reads recent posts
  (originals + reposts; replies excluded) from your configured accounts within a time window.
- **`threads_posts.py`** — *automation, by link.* Given one or many post URLs, reads each post's
  **full untruncated text**, the author's **thread continuation**, and (optionally) **replies**.
  This is how you reach posts beyond the ~7-10 the profile feed serves before infinite scroll stalls.

(Both automations share `threads_browser.py` for session/auth and `threads_common.py` for pure logic.)

## Features

- ✅ Read by account (config-driven via `accounts.json`) **or** by post link (`post_links.json` / CLI)
- ✅ Time-window parameter (`--within-hours`, e.g. last 24/48h) with reverse-chronological early-stop
- ✅ By-link reader returns full untruncated text + author thread + optional replies (`--with-replies`)
- ✅ Saved-session auth (robust) + optional `.env` credential re-login fallback
- ✅ Reliable logged-in detection (re-logs in on expiry) and clean abort on 2FA/checkpoints
- ✅ Extracts text, timestamp, permalink, author, repost flag, metrics, external links, media flags
- ✅ Per-item error isolation (one bad account/link doesn't sink the run)
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

### 1b. Post links to read (optional, for `threads_posts.py`)
```bash
cp post_links.json.example post_links.json
```
```json
{
  "urls": [
    "https://www.threads.com/@zuck/post/DZpPDXbCeTt",
    "https://www.threads.com/@mosseri/post/SHORTCODE"
  ]
}
```
(Only used when you don't pass URLs on the command line — CLI args take priority.)

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

### Read accounts by username (`threads_reader.py`)
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
Output → `output_threads_reader.json`.

### Read specific posts by link (`threads_posts.py`)
```bash
# One or more post URLs as arguments
python3 threads_posts.py https://www.threads.com/@zuck/post/DZpPDXbCeTt

# Many at once via --urls (comma-separated)
python3 threads_posts.py --urls "https://www.threads.com/@a/post/AAA,https://www.threads.com/@b/post/BBB"

# Read the list from post_links.json
python3 threads_posts.py

# Also capture replies from other accounts (default: off)
python3 threads_posts.py https://www.threads.com/@zuck/post/DZpPDXbCeTt --with-replies
```
Output → `output_threads_posts.json`. Each post includes full untruncated text, the author's
`thread` continuation, external `links`, and (with `--with-replies`) a `replies` array.

**Why by-link?** Threads' infinite scroll only serves ~7-10 posts per profile before it stops, and
the profile feed truncates long posts. Collect the links you care about and read them directly here.

---

## Testing — how to verify it works

The build ships with tests at three levels. Items marked **(no login)** work without your Threads
account; the last one needs your captured session.

### 1. Unit tests — pure logic, offline (no browser, no login)
```bash
python3 tests/test_threads_common.py
# or, if you have pytest: python3 -m pytest tests/ -q
```
Expected: `18/18 passed`. Covers username/URL normalization, count parsing (`"17.6K"`→`17600`),
time-window math, account/credential loading, **post-link parsing & dedup**, metric normalization,
and both output shapes.

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

### 4. By-link smoke test — read a specific public post (no login)
```python
import sys, json
sys.path.insert(0, ".")
import threads_common as tc, threads_posts as tp, threads_browser as tb
from playwright.sync_api import sync_playwright

ref = tc.parse_post_ref("https://www.threads.com/@zuck/post/DZaExc0ESvs")
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(user_agent=tb.USER_AGENT, viewport={"width": 1280, "height": 1600})
    page = ctx.new_page()
    out = tp._read_one(page, ref, with_replies=False, reply_scrolls=0)
    print("text length:", len(out["text"]), "| links:", out["links"])
    ctx.close(); b.close()
```
Expected: the full post text (longer than the truncated profile-feed version) and any external links.

### 5. Full end-to-end — your account, the real thing (needs login)
```bash
python3 record.py                                   # log in by hand, save the session

# by account:
cp accounts.json.example accounts.json              # edit with accounts you care about
python3 threads_reader.py --within-hours 48 --headed
cat output_threads_reader.json

# by link:
python3 threads_posts.py https://www.threads.com/@zuck/post/DZpPDXbCeTt --headed
cat output_threads_posts.json
```
`--headed` lets you watch it run. Once happy, drop `--headed` for unattended/cron runs.

---

## Output Format

### `output_threads_reader.json` (by account)
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
          "links": [],
          "media": ["image"],
          "truncated": false
        }
      ]
    }
  },
  "errors": {}
}
```

### `output_threads_posts.json` (by link)
```json
{
  "timestamp": "2026-06-20T02:00:00+00:00",
  "total_requested": 1,
  "total_fetched": 1,
  "posts": [
    {
      "id": "DZaExc0ESvs",
      "url": "https://www.threads.com/@zuck/post/DZaExc0ESvs",
      "requested_url": "https://www.threads.com/@zuck/post/DZaExc0ESvs",
      "author": "zuck",
      "datetime": "2026-06-10T13:41:30.000Z",
      "is_repost": false,
      "text": "Interesting Biohub conversation ... (full, untruncated)",
      "links": ["https://open.spotify.com/episode/2bufgHVuFxdBr6vKUkItdg"],
      "metrics": { "like": 680, "comment": 252, "repost": 68, "share": 22 },
      "metrics_raw": { "like": "680", "comment": "252", "repost": "68", "share": "22" },
      "media": [],
      "truncated": false,
      "thread": [],
      "replies": []
    }
  ],
  "errors": {}
}
```
Each by-link post adds `requested_url`, `thread` (author's connected continuation), and `replies`
(other accounts — populated only with `--with-replies`).

## File Structure

```
dooleys-threads-reader/
├── SKILL.md                       # AI-agent instructions
├── README.md                      # this file
├── requirements.txt               # playwright
├── record.py                      # session/snapshot recorder (human-run)
├── threads_reader.py              # automation: read accounts by username (headless)
├── threads_posts.py               # automation: read posts by link (headless)
├── threads_browser.py             # shared Playwright session/auth helpers
├── threads_common.py              # shared pure logic: config, time math, parsing, extraction JS
├── accounts.json.example          # template list of usernames
├── post_links.json.example        # template list of post URLs
├── config/
│   └── credentials.example.json   # credentials template (fallback re-login)
├── tests/
│   └── test_threads_common.py     # offline unit tests
├── .gitignore
│
│  # generated / personal — never committed:
├── accounts.json                  # your tracked usernames
├── post_links.json                # your post URLs
├── storage_state.json             # saved session (from record.py)
├── recordings/                    # scratch page snapshots (from record.py)
├── output_threads_reader.json     # by-account run output
└── output_threads_posts.json      # by-link run output
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

### 1.1.0
- New **`threads_posts.py`** — read specific posts by link: full untruncated text, author thread
  continuation, external links, and optional replies (`--with-replies`). Solves the profile feed's
  ~7-10-post infinite-scroll cap and long-post truncation.
- Refactored shared session/auth into **`threads_browser.py`** (used by both readers).
- **Hardened logged-in detection** (login-link signal) so an expired session reliably triggers
  re-login instead of silently reading public-only data.
- Added `links` (external URLs, with `l.threads.com` redirects decoded) to every post.
- `.gitignore` now also excludes personal `accounts.json` / `post_links.json`. Unit tests: 18.

### 1.0.0
- Initial release: `record.py` (session + snapshot capture) and `threads_reader.py`
  (search-driven, time-windowed reader). Saved-session auth with `.env` re-login fallback,
  per-account error isolation, JSON output, offline unit tests.
