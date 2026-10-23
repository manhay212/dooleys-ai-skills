# dooleys-security-audit

Vendored copy of Cloudflare's [`security-audit-skill`](https://github.com/cloudflare/security-audit-skill) — a coding-agent skill for multi-phase security audits with independently verified, machine-readable findings.

- **Upstream:** https://github.com/cloudflare/security-audit-skill
- **License:** MIT (see `LICENSE`)
- **Provenance:** NOT authored by us — vendored as-is. Only SKILL.md frontmatter gained `version` + `category`, plus a one-line provenance note at the top of the body. Every other file is an exact upstream copy.

## What it does

Six-phase audit: reconnaissance → coverage-led hunting → candidate validation → structured output (`findings.json` vs `report-schema.json`) → independent record verification → target-neutral reporting (`REPORT.md`, `FINDINGS-DETAIL.md`, `NEEDS-VALIDATION.md`).

Key files:
- `SKILL.md` — setup, core principles, platform terminology, workflow overview, anti-patterns
- `RECONNAISSANCE.md`, `HUNTING.md`, `ATTACK-CLASSES.md`, `VALIDATION-AND-REPORTING.md` — the core phases
- `AI-AND-LLM.md`, `WEB-PROTOCOL-AND-AUTH.md`, `CLIENT-SIDE.md`, `CLOUD-AND-DEPLOYMENT.md`, `SUPPLY-CHAIN-AND-RELEASE.md`, `MEMORY-SAFETY-AND-BINARY.md`, `PROTOCOLS-RPC-AND-MESSAGING.md`, `RESOURCE-EXHAUSTION-AND-AVAILABILITY.md`, `DATA-ISOLATION-AND-LIFECYCLE.md`, `DESKTOP-MOBILE-AND-LOCAL-IPC.md` — attack-class hunting prompts per target surface
- `report-schema.json` + `validate-findings.cjs` + `validate-coverage-ledger.cjs` — machine-readable output schema + zero-dependency Node.js validators

## Usage

Guidance mode by default (security questions, focused reviews, methodology, triage). Full audit mode only on explicit "audit/pen-test this codebase" requests. Full audit requires a coding agent with tool use + parallel sub-agents and an OS-enforced sandbox (no external network, allowlisted env, resource limits, scratch-only writes).

## Updating

```bash
git clone --depth 1 https://github.com/cloudflare/security-audit-skill /tmp/sas
cp -r /tmp/sas/skills/security-audit/. ~/.hermes/custom-skills/dooleys-security-audit/
cp /tmp/sas/LICENSE ~/.hermes/custom-skills/dooleys-security-audit/LICENSE
```

Then re-apply the frontmatter `version`/`category` fields and the provenance note to `SKILL.md`.
