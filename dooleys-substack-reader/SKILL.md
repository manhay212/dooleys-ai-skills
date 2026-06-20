---
name: dooleys-substack-reader
description: Read posts from Substack newsletters via Substack's public JSON API (no login, no API key). Use this skill to capture the latest posts from monitored Substack profiles within a recent time window (e.g. last 48h) — it resolves a substack @handle to ALL of that author's publications and reads each — OR to read the full content of specific Substack posts you have the links to. Returns posts (title, date, audience, paywall flags, full text as Markdown) as JSON. Reads a configurable account list (accounts.json) or a list of post URLs (post_links.json / CLI). Paid-subscriber posts are flagged (is_paywalled/truncated) since their body is only a teaser when unauthenticated.
version: 1.0.0
category: dooleys
---

# Substack Reader Skill

Reads recent content from **Substack** newsletters. Substack exposes a stable, **unauthenticated
JSON API** for public posts, so this skill makes plain HTTP calls (via `requests`) — **no browser,
no login, no API key**. It is the Substack analogue of `dooleys-twitter-x-reader` (an API-flavor
skill), and unlike `dooleys-threads-reader` it needs **no session capture**.

The skill has **two entry scripts** (sharing `substack_common.py` for pure logic and
`substack_client.py` for HTTP):

| Script | Role | Typical caller |
|--------|------|----------------|
| `substack_reader.py` | Reads recent posts from monitored **profiles** (by `@handle`/publication), within a time window | Agent / cron |
| `substack_posts.py` | Reads **specific posts by their URLs** (full content) | Agent / cron |

## When to Use This Skill

Use **`substack_reader.py`** (by profile) when:
- You want the latest posts from specific Substack authors (defined in `accounts.json` or `--accounts`)
- You want everything they published in the last N hours (across **all** of an author's publications)

Use **`substack_posts.py`** (by link) when:
- You already have one or more Substack post URLs and want their **full content**

Either way you get structured JSON for downstream processing/briefings.

Do **not** use this for Twitter/X (use `dooleys-twitter-x-reader`) or Threads (use
`dooleys-threads-reader`).

## Authentication Model

**None.** All endpoints used are public and unauthenticated. The trade-off: posts restricted to
paying subscribers (`audience` ≠ `everyone`) come back as a **teaser**. The skill detects this and
sets `is_paywalled: true` and `truncated: true` on the record rather than pretending the text is
complete. Both currently-configured accounts post free content.

## How It Works (endpoints, all GET, no auth)

1. **Profile → publications:** `https://substack.com/api/v1/user/<handle>/public_profile`
   → author name + every publication they write (`primaryPublication` + `publicationUsers[]`).
   A handle can map to **multiple** publications (e.g. `marcusjin` → `capitalcycle` **and**
   `cryptocyclesignal`); the reader reads them all.
2. **List posts:** `https://<subdomain>.substack.com/api/v1/posts?limit=<n>` → newest-first list.
3. **Full post:** `https://<subdomain>.substack.com/api/v1/posts/<slug>` → authoritative
   `body_html`, converted to Markdown.

## Setup

### For Hermes Agent (recommended)
1. Skill auto-discovered from `~/.hermes/skills/dooleys/`.
2. Install dependencies once on the host:
   ```bash
   cd ~/.hermes/skills/dooleys/substack-reader   # (the symlinked skill dir)
   pip install -r requirements.txt
   ```
3. Create `accounts.json` (copy the example, which is pre-filled with the two starter accounts):
   ```bash
   cp accounts.json.example accounts.json
   ```
   No credentials or env vars are required.

### Standalone
```bash
pip install -r requirements.txt
cp accounts.json.example accounts.json      # edit the accounts you want to monitor
python3 substack_reader.py --within-hours 48
```

## Configuration

### accounts.json — which profiles/publications to read
```json
{
  "accounts": [
    "cryptohayes",
    "marcusjin"
  ]
}
```
Each entry is one of:
- a bare **@handle** — `"cryptohayes"`, `"@cryptohayes"`, or `"https://substack.com/@cryptohayes"`
  → reads **all** publications that author writes;
- a **specific publication** — `"capitalcycle.substack.com"` or
  `"https://capitalcycle.substack.com"` → reads only that one publication.

Override per-run with `--accounts cryptohayes,marcusjin`.

### post_links.json — which posts to read by URL (for substack_posts.py)
```json
{
  "urls": [
    "https://cryptohayes.substack.com/p/reality-test"
  ]
}
```
Used only when no URLs are passed on the command line (CLI args take priority). Each entry must be
a full post permalink of the form `https://<subdomain>.substack.com/p/<slug>`.

## Instructions for AI Agent

### Function 1: substack_reader.py — read profiles (the main function)

**Purpose:** Capture recent posts from the configured Substack accounts and write JSON.

**Preconditions:** `accounts.json` exists (or pass `--accounts`). No auth needed.

**Steps the script performs:**
1. Resolve accounts (`--accounts` CSV overrides `accounts.json`).
2. For each account: if it's a publication, use it directly; if it's a handle, fetch the
   public profile and expand to **all** its publications.
3. For each publication: list recent posts, keep those within `--within-hours`, and fetch each
   kept post's full content. Convert `body_html` → Markdown.
4. Write `output_substack_reader.json`. A failing account → recorded under `errors`; a failing
   single publication → under that account's `publication_errors`; the run continues.

**Command:**
```bash
python3 substack_reader.py                          # accounts.json, last 48h
python3 substack_reader.py --within-hours 168       # last 7 days
python3 substack_reader.py --accounts cryptohayes,marcusjin
python3 substack_reader.py --list-limit 20          # scan deeper per publication
```

**Flags:** `--within-hours` (default 48), `--accounts a,b`, `--accounts-file PATH`,
`--list-limit` (default 12; how many recent posts to scan per publication before windowing),
`--output PATH`.

**Exit codes:** `0` success · `1` no accounts configured · `2` fatal error before any account ran.

### Function 2: substack_posts.py — read posts by URL

**Purpose:** Read the full content of one or more specific Substack posts you have the links to.

**Preconditions:** One or more post URLs (positional args, `--urls`, or `post_links.json`).

**Steps the script performs:**
1. Resolve + de-duplicate URLs (CLI positional and/or `--urls` take priority; else `post_links.json`).
   Each is parsed into `{subdomain, slug}`; non-post URLs are skipped.
2. For each: fetch the full post and build a record (with `requested_url`).
3. Write `output_substack_posts.json`. One failing URL → recorded under `errors`; the run continues.

**Command:**
```bash
python3 substack_posts.py https://cryptohayes.substack.com/p/reality-test
python3 substack_posts.py --urls "https://a.substack.com/p/x,https://b.substack.com/p/y"
python3 substack_posts.py                      # read post_links.json
```

**Flags:** positional `urls`, `--urls a,b`, `--links-file PATH`, `--output PATH`.

**Exit codes:** `0` success · `1` no valid post URLs.

## Output Format

### substack_reader.py → `output_substack_reader.json`
```json
{
  "timestamp": "2026-06-20T14:00:00+00:00",
  "within_hours": 48.0,
  "cutoff": "2026-06-18T14:00:00+00:00",
  "total_accounts": 2,
  "total_posts": 1,
  "accounts": {
    "marcusjin": {
      "handle": "marcusjin",
      "name": "Marcus Jin",
      "publications": [
        {"subdomain": "capitalcycle", "name": "資本週期"},
        {"subdomain": "cryptocyclesignal", "name": "加密市場週期訊號"}
      ],
      "post_count": 1,
      "posts": [
        {
          "id": 168...,
          "title": "SPX 站上 7500 ...",
          "subtitle": "...",
          "url": "https://capitalcycle.substack.com/p/spx-7500",
          "publication": "capitalcycle",
          "slug": "spx-7500",
          "post_date": "2026-06-17T13:00:46.272Z",
          "audience": "everyone",
          "is_paywalled": false,
          "truncated": false,
          "word_count": 900,
          "text": "## ... full post as Markdown ..."
        }
      ]
    }
  },
  "errors": {}
}
```

### substack_posts.py → `output_substack_posts.json`
```json
{
  "timestamp": "2026-06-20T02:00:00+00:00",
  "total_requested": 1,
  "total_fetched": 1,
  "posts": [
    { "...same fields as a reader post...": "...", "requested_url": "https://.../p/slug" }
  ],
  "errors": {}
}
```

**Field notes:**
- `audience` — `"everyone"` for free posts; other values (e.g. `"only_paid"`) mean paid-tier.
- `is_paywalled` — true when `audience` ≠ `everyone`.
- `truncated` — true when the API returned only a teaser (`should_show_paywall`); the `text` is then
  partial. For free posts both flags are false and `text` is the complete article.
- `text` — `body_html` converted to Markdown (links kept, images dropped, blank lines collapsed).
- `word_count` — word count of `text` (useful to gauge real vs. teaser content).
- `publications` — every publication the handle authors (primary first); the reader reads them all.

## Error Handling

- **No accounts configured** (missing `accounts.json`, no `--accounts`) → exit 1 with a message.
- **A single account fails** (unknown handle, profile disabled) → captured in top-level `errors`,
  run continues.
- **A single publication fails** within a multi-publication account → captured in that account's
  `publication_errors`, the other publications still read.
- **A single post URL is invalid/unfetchable** (`substack_posts.py`) → captured in `errors`,
  run continues; if *no* URL is valid → exit 1.
- **Transient HTTP** (429/5xx) → retried with backoff; persistent 4xx → surfaced as the error.

## API Notes & Limits (keep in sync if Substack changes)

- This is Substack's **unofficial** JSON API (no published contract). The three endpoints above
  have been stable and are widely used, but could change; if listings/content stop parsing, verify
  the JSON shape (`primaryPublication.subdomain`, `publicationUsers[].publication`, post `slug` /
  `body_html` / `audience` / `should_show_paywall`) and update `substack_common.py`.
- **Custom-domain publications:** resolution here relies on the `<subdomain>.substack.com` host.
  Publications served only on a custom domain (no substack subdomain) are out of scope for now.
- **Volume:** `--list-limit` caps how many recent posts are scanned per publication before the time
  window is applied; keep account lists and windows modest to stay unobtrusive.
- **Full content:** the reader fetches each in-window post's single-post endpoint for the
  authoritative body (the list endpoint usually includes `body_html` too, used as a fallback).
