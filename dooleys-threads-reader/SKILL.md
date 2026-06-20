---
name: dooleys-threads-reader
description: Read posts from Threads (threads.com) via browser automation. Use this skill to capture what specific Threads users posted in a recent time window (e.g. the last 24/48h) by username, OR to read the full content of specific Threads posts you have the links to. Threads has no public API, so this drives a headless Chromium with Playwright, reusing a human-captured login session. Returns posts (text, timestamps, metrics, links, media) as JSON. Reads a configurable username list (accounts.json) or a list of post URLs (post_links.json / CLI). Includes a companion 'record' script for capturing the login session and page snapshots.
version: 1.1.0
category: dooleys
required_environment_variables:
  - THREADS_USERNAME
  - THREADS_PASSWORD
---

# Threads Reader Skill

Reads recent content from Threads (Meta's `threads.com`) accounts. Because Threads has **no
public/official API** for reading, this skill performs **browser automation** with Playwright
(headless Chromium) instead of HTTP API calls. It is the Threads analogue of
`dooleys-twitter-x-reader`, but the transport is a real browser.

The skill has **three scripts** (sharing `threads_common.py` for pure logic and
`threads_browser.py` for session/auth):

| Script | Role | Who runs it |
|--------|------|-------------|
| `record.py` | Captures the authenticated login **session** (and optional page snapshots) | **Human**, by hand, in a visible browser |
| `threads_reader.py` | Reads recent posts from **accounts** (by username), outputs JSON | Agent / cron, headless |
| `threads_posts.py` | Reads **specific posts by their links** (full text + thread + optional replies), outputs JSON | Agent / cron, headless |

## When to Use This Skill

Use **`threads_reader.py`** (by username) when:
- You need recent posts from specific Threads users (defined in `accounts.json` or via `--accounts`)
- You want everything an account posted in the last N hours (originals + reposts; replies excluded)

Use **`threads_posts.py`** (by link) when:
- You already have one or more post URLs and want their **full content** (the profile feed truncates
  long posts and Threads' infinite scroll only serves ~7-10 posts per profile before stalling, so
  the by-link reader is how you reach older/specific posts and get untruncated text)
- You want a post's author **thread continuation**, and optionally the **replies** under it

Either way you get structured JSON for downstream processing/briefings.

Do **not** use this for Twitter/X — use `dooleys-twitter-x-reader` (which has a real API).

## Prerequisites

- Python 3.8+
- Playwright + a Chromium build: `pip install -r requirements.txt && python -m playwright install chromium`
- A **captured login session** (`storage_state.json`) produced by `record.py` (one-time, by hand).
  This is required because Threads/Instagram flags automated logins; a human logs in once.
- Optionally `THREADS_USERNAME` / `THREADS_PASSWORD` for an automatic headless re-login fallback
  when the saved session expires.

## Authentication Model (important)

Auth precedence at read time:
1. **`storage_state.json`** (the saved session from `record.py`) — primary, most reliable.
2. If that session is dead **and** credentials exist (`THREADS_USERNAME`/`THREADS_PASSWORD` in
   env, or `config/credentials.json`), the reader attempts **one** headless re-login.
3. If a **2FA / security checkpoint** appears, the reader **aborts with a clear message** telling
   the user to re-run `record.py` (it never loops on a challenge).

Credentials are loaded **env-first, file-fallback** (same pattern as `dooleys-twitter-x-reader`).

## Setup

### For Hermes Agent (recommended)

1. Skill auto-discovered from `~/.hermes/skills/dooleys/`.
2. Install the browser once on the host:
   ```bash
   cd ~/.hermes/skills/dooleys/threads-reader   # (the symlinked skill dir)
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
3. Add credentials to `~/.hermes/.env` (used only for the re-login fallback):
   ```bash
   THREADS_USERNAME=your_threads_username_or_email
   THREADS_PASSWORD=your_threads_password
   ```
4. **Capture the session by hand** (needs a display — run on the laptop's desktop, not over a
   headless SSH session):
   ```bash
   python3 record.py
   # Log in in the browser window (clear any 2FA), then type 'q' + ENTER to save the session.
   ```
5. `/restart` the gateway to pick up env vars.

### Standalone

```bash
pip install -r requirements.txt
python -m playwright install chromium
cp config/credentials.example.json config/credentials.json   # optional (fallback re-login)
cp accounts.json.example accounts.json                        # then edit the usernames
python3 record.py                                             # capture session (one-time)
```

## Configuration

### accounts.json — which accounts to read
```json
{
  "usernames": ["zuck", "mosseri", "someaccount"]
}
```
Usernames are normalized (the leading `@` and whitespace are stripped). You can also override
the file per-run with `--accounts zuck,mosseri`.

### post_links.json — which posts to read by link (for threads_posts.py)
```json
{
  "urls": [
    "https://www.threads.com/@zuck/post/DZpPDXbCeTt",
    "https://www.threads.com/@mosseri/post/SHORTCODE"
  ]
}
```
Used only when no URLs are passed on the command line (CLI args take priority). Each entry must be
a full post permalink of the form `https://www.threads.com/@username/post/SHORTCODE`.

### config/credentials.json — fallback re-login only (env vars preferred)
```json
{
  "username": "YOUR_THREADS_USERNAME_OR_EMAIL",
  "password": "YOUR_THREADS_PASSWORD"
}
```

## Instructions for AI Agent

### Function 1: threads_reader.py — read accounts (the main function)

**Purpose:** Capture recent posts from the configured Threads accounts and write JSON.

**Preconditions:**
- `storage_state.json` exists (from `record.py`), OR credentials are set for a re-login fallback.
- `accounts.json` exists (or pass `--accounts`).

**Steps the script performs:**
1. Resolve usernames (`--accounts` CSV overrides `accounts.json`).
2. Launch headless Chromium, load `storage_state.json`, open `threads.com`, confirm login
   (re-login fallback if needed; abort cleanly on 2FA).
3. For each username: navigate via **Search** (`/search?q=USER`) and open the matching profile
   result (falls back to the direct `/@USER` URL if the search result link isn't found).
4. Scroll the profile collecting **originals + reposts** (replies are excluded — Threads keeps
   them on a separate tab). Read each post's timestamp from `<time datetime>` and **stop scrolling
   once posts fall outside the `--within-hours` window** (the feed is reverse-chronological).
5. Write `output_threads_reader.json`. One failing account is recorded under `errors` and does
   not abort the run.

**Command:**
```bash
python3 threads_reader.py --within-hours 24
python3 threads_reader.py --accounts zuck,mosseri --within-hours 48
python3 threads_reader.py --nav-mode direct        # skip Search, go straight to /@user
python3 threads_reader.py --headed                 # show the browser (debugging)
```

**Flags:** `--within-hours` (default 24), `--accounts a,b,c`, `--nav-mode {search,direct}`
(default `search`), `--headed`, `--max-scrolls` (default 25), `--output PATH`.

**Exit codes:** `0` success · `1` no accounts configured · `2` session error (run `record.py`).

### Function 2: threads_posts.py — read posts by link

**Purpose:** Read the full content of one or more specific Threads posts you have the links to.
Use this to get **untruncated** text, reach posts older than the ~7-10 the profile feed serves, and
capture an author's **thread continuation** (and optionally replies).

**Preconditions:**
- `storage_state.json` exists (from `record.py`), OR credentials are set for a re-login fallback.
- One or more post URLs supplied (positional args, `--urls`, or `post_links.json`).

**Steps the script performs:**
1. Resolve post links (CLI positional args and/or `--urls` CSV take priority; else `post_links.json`).
   Each link is parsed into `{author, code, url}`; invalid links are skipped, duplicates removed.
2. Launch headless Chromium, load the session, confirm login (re-login fallback; abort on 2FA).
3. For each link: open the permalink page and classify every post on it into:
   - **focus** — the requested post (matched by shortcode), with full untruncated text;
   - **thread** — subsequent posts by the *same author* (their connected continuation);
   - **replies** — posts by *other* authors (captured only with `--with-replies`).
4. Write `output_threads_posts.json`. One failing link is recorded under `errors`; the run continues.

**Command:**
```bash
python3 threads_posts.py https://www.threads.com/@zuck/post/DZpPDXbCeTt
python3 threads_posts.py --urls "https://www.threads.com/@a/post/AAA,https://www.threads.com/@b/post/BBB"
python3 threads_posts.py                      # read post_links.json
python3 threads_posts.py URL --with-replies   # also capture replies from others
```

**Flags:** positional `urls`, `--urls a,b`, `--with-replies` (default off), `--reply-scrolls`
(default 3), `--headed`, `--output PATH`.

**Exit codes:** `0` success · `1` no valid links · `2` session error (run `record.py`).

### Function 3: record.py — capture session / snapshots (human-run, one-time)

**Purpose:** Let a human log in once in a visible browser and save the session the reader reuses.
Also dumps page snapshots (HTML + element map + screenshot) for authoring/repairing selectors.

**Command:**
```bash
python3 record.py                 # full: log in, navigate, optionally snapshot, save session
python3 record.py --no-snapshots  # only capture/refresh the session
python3 record.py --url https://www.threads.com/search   # start elsewhere
```

In the terminal: type a label + ENTER to snapshot the current page into `recordings/`; type
`q` + ENTER to save `storage_state.json` and quit. **`recordings/` is scratch — delete it when
done** (git-ignored; may contain handles you searched).

## Output Format

### threads_reader.py → `output_threads_reader.json`
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

### threads_posts.py → `output_threads_posts.json`
```json
{
  "timestamp": "2026-06-20T02:00:00+00:00",
  "total_requested": 2,
  "total_fetched": 2,
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
Each post carries the same fields as a reader post, plus `requested_url`, a `thread` array (the
author's connected continuation), and a `replies` array (other accounts' replies; populated only
with `--with-replies`).

**Field notes (both outputs):**
- `is_repost` — true when the post's author differs from the profile owner, or a repost/pinned banner is present.
- `metrics` — parsed integers; `metrics_raw` — the original strings (`"17.6K"`).
- `links` — external URLs in the post (Threads' `l.threads.com` redirects are decoded to the real URL).
- `truncated` — true if a "… more" expander was present. The profile feed truncates long posts;
  reading the same post via `threads_posts.py` returns the full text.
- `media` — coarse flags (`"image"`, `"video"`) detected on the card.

## Selectors (verified via live DOM recon — keep in sync if Threads changes)

- **Login:** username `input[autocomplete="username"]`, password `input[autocomplete="current-password"]`, submit = the "Log in" button.
- **Logged-out check:** the page carries the username input and/or a `a[href*="/login"]` link
  (plus a "Continue with Instagram" button). Logged-in pages have none of these. (Don't rely on the
  username input alone — public pages omit it even when logged out.)
- **Search:** `GET /search?q=USER` → result links are `a[href^="/@"]`; click `a[href="/@USER"]`.
- **Post card:** `[data-pressable-container]`; permalink `a[href*="/post/"]` (id = the shortcode after `/post/`); timestamp `time[datetime]`; author `a[href^="/@"]`; metrics via `svg[aria-label="Like|Comment|Repost|Share"]` → `closest('[role="button"]')` text; body via `[dir="auto"]` spans (excluding links, time, and metric buttons); external links via `a[href]` (decoding `l.threads.com?u=` redirects).
- **Permalink page:** the focused post is the container whose shortcode matches the URL; other
  same-author containers are the thread continuation; the rest are replies.

If Threads changes its DOM, re-run `record.py`, snapshot the search/profile/post pages, and update
the extraction JS (`POST_EXTRACTION_JS`, `POST_PAGE_EXTRACTION_JS`) / selectors in `threads_common.py`.

## Error Handling

- **No session and no credentials** → exit 2 with instructions to run `record.py`.
- **Expired session, no creds** → exit 2 (run `record.py`).
- **2FA / checkpoint on re-login** → exit 2 (run `record.py` to clear it by hand).
- **A single account fails** (private, renamed, no posts) → captured in `errors`, run continues.

## Notes & Limits

- **Headless on a server:** the reader runs headless and is cron-friendly. `record.py` needs a
  real display (run it on the laptop desktop), because a human must log in.
- **Bot detection:** reusing a saved session is far more robust than logging in each run. If you
  start seeing checkpoints, re-capture the session with `record.py`.
- **Rate/volume:** scrolling is throttled (~2s between scrolls) and capped by `--max-scrolls`.
  Keep account lists modest and windows reasonable to stay unobtrusive.
- **Profile feed is shallow:** Threads' infinite scroll serves only ~7-10 posts per profile before
  it stalls, and it truncates long posts. To reach older/specific posts or get full text, collect
  their links and use `threads_posts.py`.
- **Replies:** excluded from the username reader (they live on the profile's "Replies" tab). The
  by-link reader can include them with `--with-replies`.
