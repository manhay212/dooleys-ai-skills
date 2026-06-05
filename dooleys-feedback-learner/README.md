# dooleys-feedback-learner

A metacognitive skill that extracts durable principles from user feedback. Based on Warp's "Agents Need Feedback Loops, Not Perfect Prompts" framework.

## What It Does

When the user corrects the agent, this skill prevents the natural failure mode of turning every correction into a brittle rule. Instead, it follows a 7-step process to extract the *principle* behind the correction — something that transfers to new situations and compounds over time.

## How It Works

1. **Identify** — what specifically went wrong?
2. **Ask Why** — what's the root cause?
3. **Zoom Out** — what's the pattern beyond this one case?
4. **Check Existing** — sharpen existing principles or add new ones?
5. **Write Principle** — describe *how to think*, not *what to do*
6. **Place It** — which governing document does it belong in?
7. **Propose** — show the user, wait for approval before committing

The agent proposes. The human decides. This is the control mechanism.

## Why It Matters

Without this skill, corrections accumulate as rules:

> **Bad (rule):** "Never mention pricing in the first sentence."
> **Good (principle):** "If someone is venting, lead with empathy, not a pitch."

Rules overfit and break when context changes. Principles transfer. Every correction that becomes a principle pays dividends forever.

## Installation

### For Hermes Agent

```bash
# Clone the dooleys-ai-skills repo
git clone https://github.com/manhay212/dooleys-ai-skills.git ~/.hermes/custom-skills

# Symlink into skills directory
mkdir -p ~/.hermes/skills/dooleys
ln -sfn ~/.hermes/custom-skills/dooleys-feedback-learner ~/.hermes/skills/dooleys/feedback-learner

# Reload skills in your agent chat: /restart
```

No API keys or configuration needed. This is a pure process skill — the agent executes the steps mentally.

### For Other AI Agents

Copy the `dooleys-feedback-learner/` folder to your agent's skills directory. The agent will auto-discover it from the SKILL.md frontmatter.

## When It Activates

The agent loads this skill when:
- The user explicitly corrects something
- The user says "don't do that again" or "next time, do X"
- The user rewrites or overrides a response
- The user gives negative or positive feedback on approach/tone/depth

It does NOT activate for trivial typos or one-off factual corrections.

## Reference

Based on "Agents Need Feedback Loops, Not Perfect Prompts" by Petra Donka (Warp, May 14, 2026).
Full analysis saved in the Hermes knowledge base.
