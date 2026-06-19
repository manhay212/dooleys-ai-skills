---
name: research-fallback-methods
description: Fallback research techniques when primary web search engines (Google, Bing, DuckDuckGo) are blocked, rate-limited, or returning no results. Use when web_search, browser, or curl-based search approaches fail.
version: 1.0.0
category: dooleys
---

# Research Fallback Methods

When primary search engines block automated queries (increasingly common in 2026), use structured data APIs and direct source access as fallbacks. This skill documents proven techniques.

## When to Use

- `web_search` returns empty or junk results
- `browser_navigate` to Google/Bing hits CAPTCHA or Cloudflare challenges
- DuckDuckGo lite/API returns empty
- curl-based search scraping returns JavaScript shells with no content
- The research target involves **organizational personnel, leadership changes, corporate governance, or entity facts** (where Wikipedia/Wikidata excel)
- You've failed 3+ web search attempts and need a different approach

## Technique 1: Wikipedia API for Organizational Change Tracking

Wikipedia's MediaWiki API is rarely blocked and provides rich structured data for tracking personnel changes at organizations.

### Core API endpoints

```
# Get current page content (infobox + body)
https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles={PAGE_TITLE}&rvslots=main&rvprop=content&format=json&rvlimit=1

# Get page revision history (timestamps, users, edit comments)
https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles={PAGE_TITLE}&rvlimit=50&rvprop=timestamp|comment|user&format=json

# Get page content at a specific point in time (bisect when a change happened)
https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles={PAGE_TITLE}&rvlimit=1&rvstart={TIMESTAMP}&rvslots=main&rvprop=content&format=json
```

### Bisection workflow for "when did X leave?"

1. **Get current page content** — extract infobox fields (chief1_name, chief2_name, etc.)
2. **If target person is absent**, get revision history with comments
3. **Identify candidate revisions** where management changes likely occurred (look for edit comments with "update", "grammar", blank comments by organizational accounts)
4. **Bisect**: fetch content at each candidate revision timestamp using `rvstart={TIMESTAMP}`
5. **Pinpoint the revision** where the target name disappeared and replacement appeared

### Python parsing pattern

```python
import sys, json

d = json.load(sys.stdin)
pages = d.get('query', {}).get('pages', {})
for pid, page in pages.items():
    for rev in page.get('revisions', []):
        content = rev.get('slots', {}).get('main', {}).get('*', '')
        for line in content.split('\n'):
            if any(w in line.lower() for w in ['chief', 'deputy', 'executive']):
                print(line.strip())
```

### Key advantages

- **No authentication required** — Wikipedia API is fully open
- **Revision timestamps** give you a precise timeline of when changes were recorded
- **Infobox data** is semi-structured and easy to parse
- **Works when Google/Bing/DuckDuckGo all block you** — this was proven in a session where all three major search engines returned empty or JavaScript-only responses

### Limitations

- Only covers entities with Wikipedia pages
- Infobox completeness varies (not all organizations list all executives)
- Revision timestamps reflect when Wikipedia was edited, not necessarily the exact date of the real-world change (but usually close)
- Some organizational pages use templates that are harder to parse

## Pitfalls

- **rvstart is a "at or before" filter**, not an exact match. When bisecting, revisions at the exact timestamp may not be returned if they're slightly before it. Use generous timestamp windows.
- **Wikipedia infoboxes may not list all deputies**. An organization might have multiple deputy directors but Wikipedia may only list one. Use this for confirming someone HAS left (absence from infobox), not for confirming they're the ONLY one in a role.
- **Revision comments can be misleading**. A "typo fix" edit might actually be when personnel changes were added (as happened with the HKTDC page — a "clean up, typo(s) fixed" edit was when Jenny Koo was added).
- **Don't confuse Wikipedia absence with real-world absence**. Always corroborate with at least one other source if possible.

## References

- `references/wikipedia-api-revision-tracking.md` — Detailed reproduction recipe from the 2026-06-19 HKTDC fact-check session, including full bisection workflow, parsing snippets, and a table of every search method that failed vs. what worked
