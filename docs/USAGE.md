# Using amebo — what works today

*Practical guide as of 2026-07-05. Everything below is built + tested (627 unit tests, 5/5 live e2e). Things marked **needs deploy** require an `amebo-backend` restart to go live — that's your call.*

## The four ways to talk to it

### 1. In Slack (the main one)
`@amebo …` in a channel or thread, or the slash commands:
- **`@amebo <question>`** — it searches where the answer lives (CRM, Taiga, project docs, abra) and answers. It speaks little, points to things.
- **`@amebo` + a request** ("follow up with Acme by Friday", "who's working on the badge embed?") — it uses tools, and for anything outbound (a task, a message, a CRM write) it **drafts** the action and holds it for your approval. Nothing hits the world until you approve.
- **`/task <project> <subject…> due:YYYY-MM-DD [assign:user] [cash:N]`** — create a Taiga task immediately, as amebo (human-issued, no AI, no gate). Due date required, must not be in the past.
- **`/ask`, `/askall`** — Q&A.

You approve its drafts via the pending-actions surface (`/api/pending-actions`) — approve → it executes as amebo.

### 2. Set goals (claws) — it works them over time
Give it a goal ("line up 3 co-op partners to try the demo this week"). It:
- **iterates across dispatches** — remembers what it tried, re-checks the live tools before acting (doesn't repeat itself),
- **asks you and waits** when it hits a decision only you can make (`ask_user`), resuming when you reply,
- **pings you** (Slack DM, resolved to your handle) when a human step is needed,
- **pauses + alerts** if it fails or hits its budget — never silently,
- gives a **weekly recap** of what moved / what's blocked / what needs you.
All outbound stays gated. Goals run via `/api/goals/{id}/dispatch` (or the scheduler when enabled).

### 3. Web chat (authenticated) — `POST /api/chat/message`
Send an SSO bearer token; the org is resolved from your login. Full capabilities.

### 4. Embed a read-only chat anywhere — `POST /api/chat/public` **(needs deploy)**
```json
{ "message": "what is this project?", "instance_slug": "whatscookin" }
```
No login. Answers from the instance's knowledge, **never executes anything** (zero tools, T0). Opt an instance in first: set `config.public_chat: true` on the instance (off by default → 404). Safe to put behind a public page.

## What it can actually do (tools, all outbound gated)
- **CRM (Odoo):** search contacts · read a contact's history · **set a next step** (`crm_schedule` — the pipeline-hygiene fix) · tag · log-contacted.
- **Taiga:** list · **create / update / comment / close** tasks.
- **Projects:** read + edit a project's `MAIN.md` (in the org's repo, path-guarded).
- **Knowledge (abra):** search · look up a person/org, scoped to the org.
- **Skills:** *"file this as a skill under raise the voices: …"* → stored **verbatim** in that org's repo, usable whenever amebo acts for that org.
- **Slack:** post / DM a person (resolved to their handle), gated.

## Multi-org (the new capability)
- One amebo can serve many orgs. An action's org is resolved per message: explicit *"under <org>"* → thread pin → channel default → your sole membership → it asks.
- **Onboard a new org with zero code:** `org_provisioning.provision_org(slug, name, context_repo=…, instance_id=…, members=[…])`, then drop an `org.yaml` in the org's repo + its secrets in the credential store.
- **Isolation is enforced:** an org with no config is *refused* its tools — it can never fall back to another org's credentials (verified live: org 2 can't see linkedtrust's CRM).

## To make the newest capabilities live
The running backend predates today's commits. To use the new tools + `/api/chat/public` + the goal-loop upgrades, **restart `amebo-backend`** (your call — `LEGACY_ENV_ORG_ID=1` is already set, so linkedtrust's tools keep working and other orgs fail closed).

## Before opening `/public` to the internet
Per-IP rate limiting is the one remaining guard (opt-in + no-knowledge-leak + max-length are done). Keep it behind an authenticated proxy, or add the rate limit first.

## Two things still needing you (not code)
- **Slack two-way**: to talk *back* to amebo in Slack it needs the app's event-subscription/scopes (a Slack-admin change on your side).
- **Provision RTV / CivicWorks for real**: supply their creds; then `provision_org` + seed their `org.yaml`. That's the acceptance test that the layer is generic.
