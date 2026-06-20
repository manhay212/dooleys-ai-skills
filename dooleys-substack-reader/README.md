# dooleys-substack-reader

Read posts from **Substack** newsletters via Substack's public JSON API — **no login, no API key,
no browser**. Two functions:

- **`substack_reader.py`** — read the latest posts from monitored profiles within a time window.
  A Substack `@handle` is expanded to **all** of that author's publications.
- **`substack_posts.py`** — read the full content of specific Substack posts by URL.

Output is JSON with each post's title, date, audience/paywall flags, word count, and full text as
Markdown. See `SKILL.md` for the agent-facing contract.

## Why no authentication?

Substack serves public posts through an unauthenticated JSON API, so this is an **API-flavor**
skill (like `dooleys-twitter-x-reader`), not a browser-automation one. Posts restricted to paying
subscribers come back as a teaser; those records are flagged `is_paywalled` + `truncated` rather
than reported as complete.

## Install

```bash
cd dooleys-substack-reader
python3 -m venv .venv && . .venv/bin/activate     # optional but recommended
pip install -r requirements.txt
cp accounts.json.example accounts.json            # pre-filled with the two starter accounts
```

Dependencies: `requests`, `html2text`. No env vars, no credentials.

## Configure

`accounts.json` — profiles/publications to monitor:
```json
{ "accounts": ["cryptohayes", "marcusjin"] }
```
Each entry is either a Substack `@handle` (reads **all** that author's publications) or a specific
`<subdomain>.substack.com` publication. Accepted forms: `cryptohayes`, `@cryptohayes`,
`https://substack.com/@cryptohayes`, `capitalcycle.substack.com`.

`post_links.json` (optional, for `substack_posts.py`) — specific post URLs, used only when none are
passed on the command line.

## Use

```bash
# Latest posts from monitored profiles (default: last 48h)
python3 substack_reader.py
python3 substack_reader.py --within-hours 168            # last 7 days
python3 substack_reader.py --accounts cryptohayes        # ad-hoc override
#   -> output_substack_reader.json

# Full content of specific posts by URL
python3 substack_posts.py https://cryptohayes.substack.com/p/reality-test
python3 substack_posts.py                                # reads post_links.json
#   -> output_substack_posts.json
```

## Testing walkthrough

**1. Unit tests (offline, fast — pure logic in `substack_common.py`):**
```bash
. .venv/bin/activate
python3 tests/test_substack_common.py        # built-in runner, no pytest needed
# or: python3 -m pytest tests/
```
Covers config/URL parsing, profile→publication resolution, time-window filtering, paywall
detection, and HTML→Markdown cleanup. Expect `27/27 passed`.

**2. Live smoke test (hits the real public API):**
```bash
# Use a wide window so you reliably catch posts regardless of timing:
python3 substack_reader.py --within-hours 2160
python3 -c "import json;d=json.load(open('output_substack_reader.json'));print(d['total_posts'],'posts,',list(d['accounts']),'errors:',d['errors'])"

# By-link:
python3 substack_posts.py https://cryptohayes.substack.com/p/reality-test
```
Expect posts from both accounts (with `marcusjin` showing two publications:
`capitalcycle` + `cryptocyclesignal`), `errors: {}`, and clean Markdown in each post's `text`.

**3. Failure paths:**
```bash
python3 substack_reader.py --accounts-file /tmp/nope.json ; echo "rc=$?"   # -> rc=1, no accounts
python3 substack_reader.py --accounts "bad-handle-zzz,cryptohayes" --within-hours 9000
#   -> cryptohayes still read; "bad-handle-zzz" recorded under errors
```

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | Agent-facing instructions + output contract |
| `substack_reader.py` | Entry point: read profiles within a time window |
| `substack_posts.py` | Entry point: read specific posts by URL |
| `substack_client.py` | HTTP transport (the only networked module) |
| `substack_common.py` | Pure, unit-tested logic (parsing, filtering, HTML→Markdown) |
| `tests/test_substack_common.py` | Offline unit tests |
| `accounts.json.example` / `post_links.json.example` | Config templates |
| `requirements.txt` | `requests`, `html2text` |

Generated `output_*.json` and the real `accounts.json` / `post_links.json` are git-ignored.
