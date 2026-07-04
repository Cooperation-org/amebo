---
name: make-task
description: Create a task/ticket that can be picked up cold — actionable links pinned at the very top, all context embedded or linked. Use when turning a request, thread, issue, or decision into a Taiga/marten task.
triggers:
  - "make a task"
  - "create a ticket"
  - "put this on my board"
  - "add a task"
  - "turn this into a task"
  - "make a story"
---

## When to use
Any time you're creating a task/ticket/story (Taiga/marten) — a direct "make a task for X", or turning an email, thread, issue, or decision into something someone picks up later.

## What to do
Write it so a person OR an agent can open it cold and act without asking a single question. The rule that matters: **actionable links go at the very top, as full clickable URLs.** Everything else supports that.

Structure the description in this order:
1. **DO NEXT** — the concrete next actions, each with the full URL/path it needs (source issue/PR/email/thread, any draft file, the exact command). It's the first thing the reader sees; no scrolling to find what to click.
2. **CONTEXT / DOCS** — links to background: project MAIN.md, working docs, live endpoints, sample data. Linked or embedded — never "ask me."
3. **GOAL** — one or two lines on why, so priority is clear.

Other non-obvious calls:
- Every reference is a real link or path, never "see the doc about X." Local file → give the `~/path`. URL → paste the whole URL (Taiga renders it clickable).
- Write DO-NEXT steps concretely enough that an agent could execute them (name the tool/command, the branch, the file).
- Create it with `mcp-taiga create <project> "<subject>" -d "<description>"` (project is required). If it should sit at the top of the list, say so in the body — the CLI can't set priority order.
- Subject line = the action, not the topic ("Post reply to #684, then open registry MR" beats "UNTP stuff").

## Output
A Taiga story whose body reads top-to-bottom: DO NEXT (links) → CONTEXT (links) → GOAL. Return the story ref and its marten URL (`https://marten.linkedtrust.us/board?story=<N>`).

## Don't
- Don't bury links in prose or below the fold — actionable links lead.
- Don't reference a file or issue without its path/URL.
- Don't leave context "in your head" or in a past chat — put it in the ticket or link it.
- Don't create the task until the DO-NEXT links block is complete.
