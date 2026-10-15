---
name: design-one-pager
description: When requirements are being discussed for something with a data model, show the current models and the proposed design on one page the owner can react to, and refine it each round. Use when someone says "show me the design", "visualize the models", "one page I can give feedback on", or is talking through requirements for a system.
---

## When to use
Requirements talk for anything with records and relations (an Odoo addon, an app, a pipeline).
The page is the shared object; the conversation refines it.

## What goes on the page
- **The chain:** each model as a box, left to right in the order the work flows. Mark each box
  in the code now / proposed / other system linked by URL. Model name, the few fields that
  matter, its relations in one line.
- **The rules** that bind the models (what must add up, what never blocks a person).
- **One look:** a mock of the at-a-glance view the owner asked for. Example data labelled as
  example, taken from a document they pointed to.
- **Where it plugs in:** sign-in, components, other systems.
- **Two to five options or questions, never more.** Sixteen things is not reviewable. Numbered,
  so they can answer "2: milestones". Lead with the user stories, not the model.

## How
- Read the code and the requirements doc first. "In the code now" means read in the code.
- One static HTML file in the project's repo (`docs/design.html`), copied to
  `/var/www/demos/<slug>-design/`, registered in cobox `app-registry.md`. Never a claude.ai
  artifact.
- Render at 390px and desktop (review-as-a-human), then commit, push, give the URL.
- Each round of feedback: update the same file, same URL. Answered questions move into the
  chain or the rules. Requirements the owner states go into the requirements doc in their words.
