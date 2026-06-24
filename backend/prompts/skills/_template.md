<!--
SKILL TEMPLATE — ignored by the loader (filename starts with "_").

HOW TO DRAFT A SKILL FROM WHAT THE USER SAID (instructions for the drafting model):
The user will often explain at length and think out loud. Do NOT transcribe it.
Distill it into a SHORT skill: their real intent plus the few things you would
otherwise get wrong. Specifically:
  1. Find the GOAL — what should happen when this skill fires, in one sentence.
  2. Find WHEN it applies — the situations/phrasings that should pull it in.
  3. Capture only the NON-OBVIOUS decisions: which tools/sources to prefer (and
     order), judgment calls, edge cases, and hard "don'ts". Drop anything a smart
     teammate would already know — don't pad with micro-steps.
  4. Write a SHARP `description` — that single line is what the model reads to
     decide whether to load this skill, so make it say what it does AND when.
  5. Keep the whole thing short and skimmable. Then DELETE these comments.

To create the real skill: copy this file to prompts/skills/<name>.md and fill it.
-->
---
name: <kebab-case-name>
description: <one sharp sentence — what this does and when to use it>
# triggers: optional; only the legacy fallback path uses them. The description
# drives selection now. Add a few only if you want guaranteed keyword pulls:
# triggers:
#   - "a phrase that should trigger this"
---

## When to use
<one or two lines: the situations / questions where this skill applies>

## What to do
<the goal in plain language, then 2–5 bullets ONLY for the non-obvious parts:
which tools/sources to prefer and in what order, key judgment calls, edge cases.
No keystroke-level steps. Numbered list only if order genuinely matters.>

## Output
<the shape of the answer you want: e.g. "short bulleted list", "one line per item
with who + when", "lead with the answer, then cite sources". Keep it brief.>

## Don't
<things to avoid: e.g. "don't guess if a tool returns nothing — say so plainly",
"no marketing fluff", "read-only — never create or change records">
