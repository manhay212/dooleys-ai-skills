# CLAUDE.md — `dooleys-ai-skills` (custom skills for the Hermes agent)

This repo holds **self-contained, reusable skills** for Man Hay Hong's Hermes agent (and any
agent supporting the `SKILL.md` framework). **Claude builds and maintains skills directly in this
repo** — unlike the architect workspace (`~/Documents/AI/Claude/`) where Claude only writes plans
for the Hermes agent to execute. Here, Claude clones, codes, **tests**, and pushes.

Read this before creating or editing any skill.

---

## What a skill is

A folder `dooleys-{skill-name}/` that is everything an agent needs to perform one task:
- **`SKILL.md`** — AI-agent instructions. YAML frontmatter (`name`, `description`, `version`,
  `category: dooleys`, optional `required_environment_variables`) + when-to-use + step-by-step +
  config + output format. The `description` is how the agent discovers the skill — make it precise.
- **`README.md`** — human setup + **a testing walkthrough**.
- **Working code** — Python, with the entry point at the skill root (e.g. `twitter.py`,
  `threads_reader.py`). Keep files focused; factor shared logic into a `{skill}_common.py`.
- **`requirements.txt`**, **`config/credentials.example.json`** (+ any `*.example` config),
  **`.gitignore`**.
- **`tests/`** — offline unit tests for the pure logic (encouraged; see threads-reader).

## Two flavors of skill

1. **API-based** — a public HTTP API exists. Reference: `dooleys-twitter-x-reader` (direct
   `requests` calls, no SDK).
2. **Browser-automation** — *no* public API; drive a real browser with **Playwright**. Reference:
   `dooleys-threads-reader`. Pattern: a human-run **`record.py`** captures a login session
   (`storage_state.json`) + page snapshots for selector authoring, and a headless reader reuses
   that session. Prefer **reusing a saved session** over logging in every run (avoids bot
   detection / 2FA loops); fall back to credential re-login, and **abort cleanly on a 2FA/
   checkpoint** rather than looping.

## Non-negotiable conventions

- **Golden naming:** folders `kebab-case` (`dooleys-{skill-name}`), markdown files
  `UPPER_SNAKE_CASE.md` is the architect-repo rule; **in this repo follow the existing local
  convention** — `SKILL.md` / `README.md` at skill root (that's what the agent loader expects).
- **Env-first, file-fallback credentials.** Check environment variables first
  (`SKILL_THING_TOKEN`), then `config/credentials.json`. Declare env vars in `SKILL.md`
  `required_environment_variables`. For Hermes, creds live in `~/.hermes/.env`.
- **Never commit secrets or session state.** `.gitignore` must exclude `config/credentials.json`,
  any `storage_state.json`, `output_*.json`, scratch dirs (`recordings/`), and `__pycache__/`.
  Ship `*.example` templates instead.
- **Self-contained, no cross-skill imports.** Each folder runs on its own.
- **JSON output** to `output_{function}.json` at the skill root, with a top-level `timestamp`.
- **Per-item error isolation** for batch operations (one bad account/handle → record under
  `errors`, keep going).
- **Test before pushing.** At minimum: unit tests for pure logic pass; the failure/no-config path
  exits cleanly; and for scrapers, a live smoke test against public data confirms selectors.

## Workflow for a new skill (what Claude does here)

1. **Read** this file + the closest reference skill (API → twitter-x-reader; browser → threads-reader).
2. **Brainstorm/design** with the user; confirm genuine forks (auth model, scope, output).
3. **Recon** if browser-based: inspect the live DOM (Playwright MCP) to author *real* selectors,
   recorded in `SKILL.md` under a "Selectors" section.
4. **Build** with shared logic in `{skill}_common.py`; **TDD** the pure parts.
5. **Test** (unit + failure path + live smoke); clean up generated artifacts.
6. **Document** `SKILL.md` (agent) and `README.md` (human + testing walkthrough).
7. **Update repo `README.md`** (skills table + structure).
8. **Commit & push.** GitHub is authenticated via `gh auth login`. **You may push net-new skill
   folders straight to `main`** (you aren't touching other skills). Stage explicit paths
   (`git add dooleys-{skill}/ README.md CLAUDE.md`), never `git add -A`. **Do not modify other
   skills' folders** without the user's say-so.

## Environment notes

- **GitHub:** authenticated via `gh` — clone/push without extra setup.
- **Playwright (browser skills):** install with `pip install -r requirements.txt` then
  `python -m playwright install chromium`. For local dev/recon, a Playwright MCP server is also
  available to Claude. Skills must run **standalone** on the host (headless), independent of MCP.
- **Python** 3.8+ (host has 3.12).

## Skills here

- **dooleys-twitter-x-reader** — Twitter/X API v2 reader (API flavor; the reference for HTTP skills).
- **dooleys-threads-reader** — Threads reader via Playwright (browser flavor; the reference for
  no-API scraping; `record.py` + `threads_reader.py`).
- **dooleys-market-data** — market-data ingestion engine (numbers → SQLite from free sources).
- **dooleys-feedback-learner** — metacognitive skill extracting principles from user corrections.
