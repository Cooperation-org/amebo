---
name: kaizen
description: Fires on the word "kaizen", usually next to a complaint. A subagent finds the root cause of what just went wrong and makes one conservative, general fix in the right place, while the main thread stays on what the person was doing.
triggers:
  - "kaizen"
---

The person said "kaizen" in the middle of doing something else. They are not asking to
discuss it. Do not interview them.

Answer in one line, hand the analysis to a subagent, and go back to their task. In
Claude Code that subagent is a `fork`, which inherits the session and can see what
happened. Anywhere else, put the evidence in the brief; the subagent cannot see the
conversation.

## Find the cause before looking for a fix

Walk back from the symptom to the first wrong step. What the person noticed is usually
downstream of what went wrong.

Every claim needs something quotable: a command and its output, a file and a line, a
row, a log entry. No evidence, no fix. Say the record does not show it and stop. Never
fix from how something reads to you.

Name which of the three it was:
- a rule that was missing
- a rule that was there and wrong
- code that was wrong

Then look for a prior pass on the same cause: `abra --scope claude search "<cause>"`.
The same cause twice means the earlier fix was wrong. Repair that one. Never add a
second note beside it.

## One home per fix

| What was wrong | Where the fix goes |
|---|---|
| A step in a process a skill owns | that skill, editing the line that was wrong |
| A standing rule no skill owns | one line in `/opt/shared/cobox/shared-dev-CLAUDE.md` |
| A tool: abra, amebo code, a script | the code, committed and pushed |
| What amebo knows or may do | the `instances` row: `identity_prompt`, `config.allowed_tools` |
| A fact that was missing | abra |

Change nothing and ask instead for: a data model or schema, auth, the approval gate, a
deploy, a new service, a new dependency. Those are the framework and a person reviews
them. Everything else you fix without asking.

## Make it a fix, not a note

Correcting an existing line beats adding one. Add only when nothing existing covers the
case, and delete whatever the new line replaces.

Before writing, answer both:
1. Would this have prevented what just happened?
2. Does it still read right for a case that has not happened yet?

A rule that matches only this incident's wording is a note, not a fix. Generalize it or
drop it. Three notes patching three phrasings of one cause should have been one rule.

One file, one behavior, confirmed by reading the diff alone. Two causes are two passes;
take the better one.

## Report

One line to the person: what broke, what changed, where. Not the analysis.

Then store the pass so the next one can find it:
`abra store kaizen-<slug> "<evidence, cause, change>" --qualifier "<one line>" --scope claude --cat claude/kaizen --date today`

## In amebo

amebo has no tool that writes to a repo. Do the same analysis, then file one task with
`taiga_create_task` on `core-linkedtrust-amebo-abra`, tag `agent`, holding the quoted
evidence, the file and function, the change in one sentence, and what you are unsure of.
Say plainly that you cannot make the change yourself. Do not offer to stage it or open
a PR. Filing from the record with no complaint attached is `self-improve.md`.
