# Custom Skills for AI Agents

A modular, self-contained collection of reusable skills that extend AI agent capabilities. Each skill follows the standard SKILL.md framework and includes complete implementation, documentation, and configuration.

## What Are Skills?

Skills are self-contained packages that teach AI agents how to perform specific tasks. Each skill includes:
- **SKILL.md** — Instructions the AI agent reads to understand how to use the skill
- **Working code** — The actual implementation (Python scripts, configs, etc.)
- **Documentation** — Human-readable setup guide (README.md)
- **Configuration templates** — Example credentials and settings files

When an AI agent detects a user request that matches a skill's description, it loads the SKILL.md, follows the instructions, and executes the task.

## Available Skills

| Skill | Description | Version |
|-------|-------------|---------|
| [dooleys-twitter-x-reader](./dooleys-twitter-x-reader/) | Fetch tweets from Twitter/X API v2 — user timelines and home feed | 1.2.0 |
| [dooleys-threads-reader](./dooleys-threads-reader/) | Read Threads (threads.com) posts via Playwright browser automation (no public API) — by account (time-windowed) or by post link (full text + thread + replies), JSON output | 1.1.0 |
| [dooleys-substack-reader](./dooleys-substack-reader/) | Read Substack newsletter posts via Substack's public JSON API (no login/key) — by profile (time-windowed, expands a handle to all its publications) or by post URL (full text as Markdown), JSON output | 1.0.0 |
| [dooleys-market-data](./dooleys-market-data/) | Market-data engine — backfills/updates numeric time-series from free sources (FRED/Yahoo/EIA/CoinGecko/Treasury) into SQLite and returns compact computed summaries (stats/ratio/spread/dashboard). One-shot `daily` routine writes a trustworthy UPDATE_LOG; fetch-result-based health check | 1.3.0 |
| [dooleys-feedback-learner](./dooleys-feedback-learner/) | Metacognitive skill — extracts transferable principles from user corrections (Warp feedback loop thesis) | 1.0.0 |

## Repository Structure

```
dooleys-ai-skills/
├── README.md                        # You are here
├── CLAUDE.md                        # Conventions for building/maintaining skills here
├── dooleys-twitter-x-reader/        # API-based skill (HTTP)
│   ├── SKILL.md                     # AI agent instructions (YAML frontmatter + markdown)
│   ├── README.md                    # Human setup guide
│   ├── twitter.py                   # Main implementation
│   ├── requirements.txt             # Python dependencies
│   ├── handles.json.example         # Example configuration
│   ├── config/
│   │   └── credentials.example.json # Credentials template
│   └── .gitignore
├── dooleys-threads-reader/          # Browser-automation skill (Playwright, no public API)
│   ├── SKILL.md
│   ├── README.md
│   ├── record.py                    # human-run: capture login session + page snapshots
│   ├── threads_reader.py            # automation: read accounts by username, output JSON
│   ├── threads_posts.py             # automation: read posts by link, output JSON
│   ├── threads_browser.py           # shared session/auth helpers
│   ├── threads_common.py            # shared pure logic (unit-tested)
│   ├── tests/                       # offline unit tests
│   ├── accounts.json.example
│   ├── post_links.json.example
│   ├── config/credentials.example.json
│   └── .gitignore
├── dooleys-substack-reader/         # API-based skill (Substack public JSON API, no auth)
│   ├── SKILL.md
│   ├── README.md
│   ├── substack_reader.py           # read profiles within a time window, output JSON
│   ├── substack_posts.py            # read specific posts by URL, output JSON
│   ├── substack_client.py           # HTTP transport (the only networked module)
│   ├── substack_common.py           # shared pure logic (unit-tested)
│   ├── tests/                       # offline unit tests
│   ├── accounts.json.example
│   ├── post_links.json.example
│   ├── requirements.txt
│   └── .gitignore
├── dooleys-market-data/             # API-based engine (FRED/Yahoo/EIA/CoinGecko/Treasury → SQLite)
│   ├── SKILL.md
│   ├── README.md                    # setup + corrected cron wrapper + testing walkthrough
│   ├── market_data.py               # CLI: init/sync-catalog/backfill/update/daily/query/doctor/export
│   ├── db.py                        # SQLite schema init, UPSERTs, query primitives
│   ├── catalog.py                   # load/validate catalog.yaml + sources.yaml → series table
│   ├── summarize.py                 # compact summaries: stats / ratio / spread / dashboard
│   ├── health.py                    # freshness classifier + UPDATE_LOG rendering (unit-tested)
│   ├── sources/                     # one adapter per provider (fred/yahoo/eia/coingecko/treasury)
│   ├── tests/                       # offline unit tests (health, summarize)
│   ├── docs/                        # Phase-0 design docs (architecture/spec/plan)
│   ├── references/source-notes.md   # per-source pitfalls + migration history
│   ├── requirements.txt
│   └── .gitignore                   # excludes the local .db / snapshots / secrets
└── dooleys-{future-skill}/          # Pattern for new skills
```

Skills come in two flavors: **API-based** (a public HTTP API exists — e.g. twitter-x-reader, and
substack-reader which uses Substack's unauthenticated JSON API) and **browser-automation** (no API,
drive a real browser with Playwright — e.g. threads-reader, which pairs a human-run `record.py`
session-capturer with headless readers that work by account or by link).

## How to Use a Skill

### Option 1: With an AI Agent (Recommended)

Skills are auto-discovered when placed in your agent's skills directory. The agent will load the skill when it detects a matching user request.

**For Hermes Agent:**
```bash
# Clone this repo
git clone https://github.com/manhay212/dooleys-ai-skills.git ~/.hermes/custom-skills

# Symlink skills into the skills directory
mkdir -p ~/.hermes/skills/dooleys
for skill_dir in ~/.hermes/custom-skills/dooleys-*/; do
    skill_name=$(basename "$skill_dir")
    short_name=$(echo "$skill_name" | sed 's/^dooleys-//')
    [ -f "$skill_dir/SKILL.md" ] && ln -sfn "$skill_dir" ~/.hermes/skills/dooleys/"$short_name"
done

# Add API keys to ~/.hermes/.env (see skill's README for required keys)
# Reload skills in your agent chat: /reload-skills
```

**For other agents:** Check your agent's documentation for custom skills support. Most agents that support the SKILL.md framework will auto-discover skills placed in their skills directory.

### Option 2: Standalone Use

Each skill can be used independently without an AI agent:

```bash
cd dooleys-twitter-x-reader
pip install -r requirements.txt
cp config/credentials.example.json config/credentials.json
# Edit config/credentials.json with your API keys
python twitter.py get_users_tweets
```

### API Keys

Skills that need API keys support two methods:

1. **Environment variables** (preferred for agent integration):
   ```bash
   export SKILL_API_KEY=your_key
   ```

2. **Config file** (for standalone use):
   ```bash
   cp config/credentials.example.json config/credentials.json
   # Edit with your keys
   ```

Skills check environment variables first, then fall back to config files. This ensures compatibility with both agent-based and standalone workflows.

## Creating a New Skill

See the [dooleys-twitter-x-reader](./dooleys-twitter-x-reader/) skill as a reference implementation.

### Skill Folder Template

```
dooleys-{skill-name}/
├── SKILL.md                    # Required: AI agent instructions
├── README.md                   # Required: Human setup guide
├── {implementation files}      # Your code
├── requirements.txt            # Python dependencies (if applicable)
├── config/
│   └── credentials.example.json # Credentials template (if API keys needed)
├── handles.json.example        # Example config files (if applicable)
└── .gitignore                  # Exclude credentials and output files
```

### SKILL.md Format

Every skill MUST have a valid SKILL.md with YAML frontmatter:

```yaml
---
name: dooleys-{skill-name}
description: Clear description of when to use this skill. This determines how agents discover it.
version: 1.0.0
category: dooleys
required_environment_variables:   # Optional: list env vars the skill needs
  - API_KEY_NAME
---
```

### Key Principles

- **Self-contained** — Each skill folder has everything needed to run
- **No cross-dependencies** — Skills don't depend on each other
- **Portable** — Works with any AI agent that supports SKILL.md
- **Secure** — Credentials never committed (use `.gitignore` and `.example` files)
- **Documented** — Both AI-readable (SKILL.md) and human-readable (README.md)

## Security

- **Never commit credentials** — All `credentials.json` files are in `.gitignore`
- **Use example files** — Provide `credentials.example.json` templates
- **Environment variables** — Preferred over config files for agent integration
- **Rotate tokens** — If keys are exposed, revoke and regenerate from provider portals

## License

This project is intended for personal use. Skills may be shared and adapted freely.

## Contributing

1. Create a new folder following the `dooleys-{skill-name}` pattern
2. Implement working code
3. Write SKILL.md with clear AI agent instructions
4. Write README.md with human setup guide
5. Add `.gitignore` for any generated/credential files
6. Test end-to-end
7. Push and create a pull request
