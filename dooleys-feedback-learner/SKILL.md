---
name: dooleys-feedback-learner
description: Use when the user gives a correction, feedback, or critique about the agent's behavior, response, or decision-making. Extracts transferable principles from specific corrections to compound judgement over time. Based on Warp's feedback loop thesis.
version: 1.0.0
category: dooleys
---

# Feedback Learner — Metacognitive Skill

Extracts durable principles from user corrections so the agent improves permanently, not just for the current session. Based on Warp's "Agents Need Feedback Loops, Not Perfect Prompts" framework.

**Reference:** `~/.hermes-backup-repo/docs/ai/engineering/AGENT_FEEDBACK_LOOPS.md`

## When to Use This Skill

Load this skill when:
- The user explicitly corrects something you said or did
- The user says "don't do that again" or "next time, do X instead"
- The user rewrites or overrides your response with their preferred version
- You realize you made a mistake that the user caught
- The user gives negative feedback on approach, tone, depth, or style
- After a complex task, the user says "that's right" or "no, that's wrong" — either way, extract the principle
- The user says "remember this" — these are explicit learning signals

**Don't use for:** Trivial typos, one-off factual corrections where no principle exists, or the user explicitly saying "don't save this."

## The Core Insight

> "The agent wanted to turn every correction back into a rule. For example, if I said a reply felt too marketing-y, it'd add a rule: 'Never mention pricing in the first sentence.' The transferable principle is closer to: 'If someone is venting, lead with empathy, not a pitch.'"

**Rules overfit and break. Principles transfer.** This skill exists to prevent you from making that mistake — turning every correction into a brittle rule instead of extracting the durable principle behind it.

## The 7-Step Learning Process

Execute these steps in order. Don't skip, don't rush. The quality of the extracted principle determines whether this correction compounds or decays.

### Step 1: Identify — What exactly went wrong (or right)?

Pin down the specific moment. Don't generalize yet.

- What did I do/say that the user corrected?
- What did the user do/say instead? (exact words matter)
- Was this a tone issue, a content issue, a process issue, a priority issue?

**Output:** A one-sentence description of the concrete failure (or success).

### Step 2: Ask Why — What's the underlying cause?

The correction is a symptom. Find the root cause.

- Why did I make that choice? (wrong assumption, missing context, lazy shortcut, misunderstood priority)
- What was I optimizing for vs. what should I have been optimizing for?
- What information was I missing that would have led to the right answer?

**Output:** Root cause statement, not just "I was wrong about X" but "I assumed X when Y was the actual priority."

### Step 3: Zoom Out — Would this apply beyond this one case?

Test for generality. If this principle only applies to this exact situation, it's not a principle — it's still a rule.

- What other situations would this apply to?
- What's the category of mistake this belongs to? (tone, scope, assumption, process, priority, etc.)
- If a new team member made this mistake, what would you tell them?

**Output:** The pattern description — what class of situations does this cover?

### Step 4: Check Against Existing Principles — Sharpen, edit, delete, or add?

Before writing a new principle, check what already exists.

**Where principles live in Hermes:**
| Document | What it governs | How to check |
|----------|----------------|-------------|
| `~/.hermes/SOUL.md` | Chief of Staff personality, protocols, routing | Read the relevant section |
| `~/.hermes/profiles/<name>/SOUL.md` | Specialist agent behavior | Read if domain-specific |
| Memory (injected each turn) | User preferences, conventions, corrections | Already loaded |
| fact_store | Durable structured knowledge | `fact_store(action='search')` |
| Skill files | Domain-specific instructions | `skill_view()` if relevant |

- Does an existing principle already cover this? → Sharpen it (make it clearer, add an example)
- Does an existing principle contradict this? → Surface the conflict, propose resolution
- Is this genuinely new? → Add it
- Does this make an existing principle obsolete? → Propose deletion

**Output:** "This is new" or "This sharpens principle X" or "This conflicts with Y."

### Step 5: Write as a Principle, Not a Rule

**Bad (rule):** "Never do X."
**Good (principle):** "When you encounter Y, prioritize Z because..."

A principle describes *how to think*, not *what to do*. It should:
- State the value or priority being optimized
- Be short enough to remember, specific enough to apply
- Survive context changes (new tools, new platforms, new domains)

**Before writing, test:** If I changed tools, would this principle still hold? If I was advising a different user in a different domain, would it still be valid? If yes → principle. If no → too specific, zoom out more.

**Output:** The principle, written as a declarative statement.

### Step 6: Put It Where It Belongs

Match the principle's scope to the right document.

| Scope | Destination | How to apply |
|-------|------------|-------------|
| Affects all interactions, all domains | `~/.hermes/SOUL.md` | `patch()` with review |
| Affects a specific domain (investment, AI, etc.) | `~/.hermes/profiles/<name>/SOUL.md` | `patch()` with review |
| Compact fact, always relevant | `memory(action='add')` | Direct memory add |
| Durable structured knowledge | `fact_store(action='add')` | Tagged, categorized |
| Affects a specific skill's behavior | Skill file via `skill_manage(action='patch')` | Patch the skill |
| Procedural workflow improvement | New or updated skill via `skill_manage()` | Create or patch |

**Section matters.** A principle placed in the wrong section of SOUL.md won't be applied at the right time. Place it:
- Near related principles (cohesion)
- Where the agent will encounter it during relevant decision-making (trigger proximity)
- Not buried under unrelated operational rules

**Output:** "This goes in SOUL.md, under Core Personality" or "This belongs in the investment profile SOUL.md."

### Step 7: Propose, Don't Impose — Review Gate

**CRITICAL:** The agent proposes. The human decides. This is the control mechanism that prevents drift.

Present the proposed change clearly:
1. What was the correction? (specific, brief)
2. What principle did I extract? (the 1-2 sentence principle)
3. Where does it go? (exact file + section)
4. What's the diff? (show the exact change)

Then **wait for user approval** before committing any change to SOUL.md, profile files, or skills.

For memory and fact_store (non-destructive, easily reversible), you may save immediately but tell the user you did so.

## When the Feedback Is Positive

This skill works for positive feedback too. When the user says "good job" or "that's exactly right":

1. **Identify** what specifically was right
2. **Ask why** it worked — what principle was applied correctly?
3. **Zoom out** — does this principle need to be more explicit so it's applied consistently?
4. **Check** — is this principle already documented? If not, should it be?

Positive reinforcement is signal. Don't waste it.

## What NOT to Do

### DON'T: Turn corrections into rules
```
User: "That reply was too cold."
❌ BAD: Add rule "Always start replies with warm greeting"
✅ GOOD: Extract principle "When the user is sharing something personal or emotional, acknowledge it before problem-solving"
```

### DON'T: Skip the review gate for structural changes
```
❌ BAD: Immediately patch SOUL.md without showing the user
✅ GOOD: Present the proposed change, explain the reasoning, wait for approval
```

### DON'T: Create a principle so vague it's useless
```
❌ BAD: "Be better at communicating"
✅ GOOD: "When the user asks a multi-part question, address each part explicitly rather than synthesizing a single answer"
```

### DON'T: Save every tiny correction as a principle
```
User: "It's 'their' not 'there'"
❌ BAD: Create principle about homophone checking
✅ GOOD: Just fix the typo, move on. Not everything is a principle.
```

### DON'T: Let principles accumulate without maintenance
When you add a new principle via Step 5, check if any existing principles now overlap. Merge, delete, or sharpen. Principles should be a lean set, not a growing document.

## Integration with Hermes System Architecture

### Memory Budget Awareness

Adding principles to memory consumes the ~2,200 char injection budget. Prefer:
- Short principle in memory + pointer to full doc for details
- fact_store for structured, queryable storage
- SOUL.md or skill files for long-form principles

### Backup Hygiene

Any change to SOUL.md, profile files, skills, or docs/ must be followed by `backup-to-github.sh`. The learning event itself should be logged in `~/wiki/chief-of-staff/log.md`.

### Cross-Agent Propagation

If a principle affects how specialist agents (ai-trends, investment, corporate-ai-transformation) should behave, update their profile SOUL.md files too. Don't assume the Chief of Staff's principles automatically propagate.

## Quick Reference: The Loop in One View

```
USER CORRECTION
    ↓
1. IDENTIFY — what specifically went wrong?
    ↓
2. ASK WHY — what's the root cause?
    ↓
3. ZOOM OUT — what's the pattern?
    ↓
4. CHECK EXISTING — sharpen or add?
    ↓
5. WRITE PRINCIPLE — how to think, not what to do
    ↓
6. PLACE IT — which document, which section?
    ↓
7. PROPOSE — show the user, wait for approval
    ↓
USER APPROVES → commit → backup-to-github.sh → log in wiki
```

## Pitfalls

- **Rules masquerading as principles** — If it starts with "Never" or "Always" and doesn't explain WHY, it's probably a rule. Add the reasoning.
- **Over-extracting from minor corrections** — Not every typo is a principle. Save this skill for judgment, taste, approach, and priority corrections.
- **Forgetting positive signal** — "That's right" is as valuable as "that's wrong." Extract why it was right.
- **Placing principles in the wrong scope** — A principle about investment analysis doesn't belong in the Chief of Staff SOUL.md. Route to the right profile.
- **Silent drift** — If you skip the review gate repeatedly, the agent's behavior changes without the user understanding why. Always show your work.
- **No follow-through** — Extracting the principle is step 5. Committing it is step 7. Don't stop halfway.
- **Memory bloat** — Don't dump long principles into the memory injection budget. Point to the doc instead.
