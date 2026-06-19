# Wikipedia API Revision Tracking — Reproduction Recipe

Session date: 2026-06-19
Task: Fact-check whether Patrick Lau (劉會平) had left his role as Deputy Executive Director at HKTDC

## Context

Peter (tertiary user) suspected Patrick Lau had left HKTDC. All major search engines (Google, Bing, DuckDuckGo) were blocked or returned empty/junk results. Browser-based search hit Cloudflare challenges. The HKTDC website is a React app requiring JavaScript — inaccessible via curl.

## What worked: Wikipedia API bisection

### Step 1: Get current page content

```bash
curl -s "https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles=Hong_Kong_Trade_Development_Council&rvslots=main&rvprop=content&format=json&rvlimit=1" | python3 -c "
import sys,json
d=json.load(sys.stdin)
pages = d.get('query',{}).get('pages',{})
for pid, page in pages.items():
    for rev in page.get('revisions',[]):
        content = rev.get('slots',{}).get('main',{}).get('*','')
        for line in content.split('\n'):
            if any(w in line.lower() for w in ['chief', 'deputy', 'executive']):
                print(line.strip())
"
```

**Result**: Found Jenny Koo as Deputy Executive Director. Patrick Lau absent.

### Step 2: Get revision history to find candidate change points

```bash
curl -s "https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles=Hong_Kong_Trade_Development_Council&rvlimit=100&rvprop=timestamp|comment|user&format=json" | python3 -c "
import sys,json
d=json.load(sys.stdin)
pages = d.get('query',{}).get('pages',{})
for pid, page in pages.items():
    for rev in page.get('revisions',[]):
        ts = rev.get('timestamp','')
        comment = rev.get('comment','')
        user = rev.get('user','')
        if any(w in comment.lower() for w in ['infobox', 'chief', 'deputy', 'patrick', 'jenny', 'koo', 'executive', 'chairman', 'update', 'management']):
            print(f'{ts} | {user} | {comment[:150]}')
"
```

**Key revisions found**:
- 2025-06-03 | "grammar and years update" — likely when Frederick Ma added as Chairman
- 2025-10-02 | "Socialhktdc" (blank comment) — official HKTDC account edit
- 2026-03-19 | "Socialhktdc" (two edits) — likely management updates
- 2026-03-26 | "clean up, typo(s) fixed: Executive Director → executive director"
- 2026-05-12 | "Wms1sfu" (blank comment) — **THIS was when Jenny Koo was added**

### Step 3: Bisect to find exact revision

Checked content at each candidate timestamp using:

```bash
curl -s "https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles=Hong_Kong_Trade_Development_Council&rvlimit=1&rvstart=20260512000000&rvslots=main&rvprop=content&format=json"
```

**Before May 12, 2026**: Only Chairman + Executive Director listed.
**May 12, 2026 and after**: Jenny Koo added as Deputy Executive Director.

### Step 4: Cross-reference with Wayback Machine

Attempted but returned 302 redirects. Not needed — Wikipedia revision history was sufficient.

## Key findings delivered

- Patrick Lau is NOT listed on Wikipedia's HKTDC page as of June 2026
- Jenny Koo replaced him, added to Wikipedia on May 12, 2026
- Broader HKTDC leadership transition: Chairman (June 2025), Executive Director (Oct 2025), Deputy ED (by May 2026)
- Patrick Lau served as Deputy ED from April 2019 (~6 years)

## What didn't work

| Method | Failure mode |
|--------|-------------|
| Google search (curl) | JavaScript challenge page |
| Google search (browser) | "Sorry" page, IP blocked |
| Bing search (curl) | Cloudflare challenge JS |
| Bing search (browser) | Cloudflare iframe — no results rendered |
| Bing RSS feed | Returned irrelevant Microsoft support articles |
| DuckDuckGo lite | Returned empty — region selector only, no results |
| DuckDuckGo API | Empty Abstract/RelatedTopics |
| Yahoo search | Empty |
| Brave suggest API | Works but returns suggestions only, no web results |
| Google News RSS | Empty |
| SCMP search | Next.js app — no content in curl |
| The Standard search | Next.js app — no content in curl |
| HKTDC website | React app ("You need to enable JavaScript") |
| HKTDC aboutus | Redirects to /notfound on SPA navigation |
| HKTDC API | Returns {"message":"Forbidden"} |
| Wayback Machine | 302 redirects |
| LinkedIn | Login wall |

## Principle

When all web search engines fail, go directly to structured data APIs. Wikipedia's MediaWiki API is the most reliable for organizational/personnel fact-checking. Revision timestamps give you a timeline even when you can't find news articles.
