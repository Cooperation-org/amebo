# Hermes Patterns and Amebo Gaps

Analysis of [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
(v0.14, ~17k tests, ~1900 files) compared to amebo as of `main` @ `285a190`
(PR #33 merged 2026-05-27). Goal: identify patterns amebo should adopt,
patterns amebo deliberately doesn't need, and the concrete gaps before
amebo can credibly run as a multi-channel coordination tool.

This is a discussion doc, not a plan. Open questions at the bottom.

---

## Mental model: self, friends, home

The components stop being confusing once you name them this way.

- **Abra is the self.** It holds identity, names, relationships, hot
  tags — your knowledge of your world. Persistent. *You*. Not a
  database, not a tool, *the seat of personhood* for the system.
- **Friends are other selves you can ask for help.** They have their own
  expertise, their own memory, their own boundaries. They summarize for
  you instead of dumping their internals. **Amebo is a friend** — a
  friendly claw that can act on behalf of an org. The calendar is a
  friend. LinkedClaims is a friend. A delegate-spawned specialist is,
  briefly, a friend.
- **The dashboard is the home.** Not an admin panel — the *face* the
  self presents to itself and the world. Arranged like a room. Some
  people want a wall of photos of contacts; some want a calendar grid;
  some want a journal of recent claw actions; some want a map; some
  want a list of "what's hot this week". The shape follows the person.

The dashboard is **AI-customizable verbally**. "Show me my MTC stuff
bigger." "Make the right side photos of people I've talked to recently."
"Hide everything from before March." The user shapes their home through
conversation. Some users may never open the dashboard at all — for them
"home" is the morning email digest, the Telegram pin, the ambient wall
display. The data layer is the same abra/friends backbone; only the
*surface* changes.

What falls out of this framing:

- The agentic loop is "the self deciding which friend to ask next".
  Same shape as tool-use, friendlier language for nontechnical users.
- The delegate pattern is "asking a specialist friend". They go away,
  do work, summarize. Your context stays clean.
- LinkedClaims fits naturally: friends vouch for friends. The audit
  trail *is* a graph of asks and answers.
- The dashboard does not live inside amebo. Amebo is multi-tenant org
  infrastructure; the dashboard is intimate and personal. Different
  mental categories.

This framing should drive naming when we write user copy. "Tool
registry" → "friends". "Delegate" → "ask <friend>". "Audit log" →
"what I asked, what was said back, what I did".

---

## Three components, separate concerns

```
                  [ Home / Dashboard ]
            customizable surface, AI-arranged,
            "looks like you" — photos, grid,
            journal, map, digest, wall display.
                    ▲
                    │  reads + commands
                    │
              [ Abra — the Self ]
       names, relationships, hot tags, identity,
       memory. Persistent personhood. Holds the
       data the home surfaces.
                    ▲
                    │  asks friends
                    ▼
   ┌──────┬──────────┬─────────┬──────────┬──────────┐
   │amebo │ taiga    │ odoo    │ calendar │ linked-  │  ...
   │(claw)│ (tasks)  │ (CRM)   │          │ claims   │
   └──────┴──────────┴─────────┴──────────┴──────────┘
       friends, each encapsulated. Each summarizes
       for the self instead of dumping internals.
```

- **Home/Dashboard** — separate repo, separate process. Its only job is
  to be the user's customizable face on their world. Talks to abra
  primarily; talks to friends through abra when it can. Probably
  someone's evening project — could even start as a single SvelteKit
  page with hard-coded widgets, then grow voice-rearrangement.
- **Abra (the Self)** — already exists. Becomes more central in this
  framing. Needs a clean query surface so the home and the friends can
  both reason from it. The `abra-lib` PyPI package extraction
  (`ABRA_INTEGRATION.md`) is the right direction.
- **Amebo (a friend)** — multi-tenant claw. Stops trying to be the
  center. Exposes a clean API. Hermes patterns in the rest of this doc
  apply *to amebo as a friend*, not to the whole system.

This doc focuses on amebo from here on. Home and abra deserve their own
docs.

---

## TL;DR

Amebo's kernel (agentic loop, conversation manager, goal scheduler,
channel contract, org-scoped credentials) already matches Hermes shape.
What's missing is mostly *plumbing around the edges* — long-running channel
daemons, subagent isolation, scheduled job ergonomics, multi-model
routing, and a visible view over the audit trail (which should be **Taiga**,
not a new in-house board).

The biggest *new* idea worth importing: **delegate-as-primitive** for
every non-trivial tool. The biggest *new* capability not yet documented:
**multi-model routing** (judgement about which model to use for which job)
and **LinkedClaims as two-way audit**.

---

## Start here (iterative — what to use this week)

This doc covers a lot. The goal is *to start using amebo*, not to build
everything first. Suggested first-week sequence:

1. **Pick one goal on one org**, fire it from the existing scheduler.
   Watch `goal_events`. Find what's awkward.
2. **Add `web_search` and `http_fetch`** from POWERS_PLAN Phase A — that
   alone makes most goals usable.
3. **Publish goal-event summaries to Taiga** as tickets. Reuse `mcp-taiga`.
   That IS the dashboard — no new code, the team already lives there.
4. **Add one second channel** (email or Telegram). Just one. Validate the
   gateway pattern on something real before generalizing.
5. **Add model routing** — pick model per goal/tool, not globally.

Everything else in this doc is groundwork for what comes after.

---

## What amebo already has that matches Hermes

| Amebo has | Hermes equivalent | Status |
|---|---|---|
| `qa_service._generate_with_thread_context` agentic loop | `run_agent.py AIAgent` | Equivalent shape |
| `ConversationManager` (cache-pinned prefix + compaction + 24h GC) | `agent/context_compressor.py` + session DB | Equivalent shape |
| `GoalScheduler` 60s tick, cron/event/manual triggers | `cron/scheduler.py` 60s tick | Equivalent shape |
| `channels/` contract (`InboundEnvelope` / `OutboundAction`) | `gateway/platforms/base.py` | Same abstraction |
| `goals` + `goal_events` audit | `hermes_state.py SessionDB` + `cron/jobs.py` | Same shape, ours is more structured |
| `prompts/skills/*.md` markdown skills | `skills/<topic>/<name>/SKILL.md` | Same convention, see "Skill format alignment" below |
| `instance.config.allowed_tools` per-deployment gating | Hermes per-toolset gating | Same shape |
| `org_credentials` + `CredentialResolver` + connect-link OAuth flow | (Hermes is single-user, no equivalent) | **Amebo is ahead** |
| Abra (typed bindings + scopes + hot tags) | (Hermes uses Honcho dialectic user-modeling) | **Different shape, ours is better for orgs** |

---

## Hermes patterns to import (with concrete fit)

### 1. Long-running channel daemons (not just HTTP routes)

**Hermes shape:** `gateway/run.py` is one process holding live connections
for Telegram (long-poll), Email (IMAP), Discord (websocket), Slack
(socket-mode), Signal, Matrix, SMS, WhatsApp, etc. ~20 adapters,
all inheriting `gateway/platforms/base.py`. Each adapter:

- holds its own connection / poll loop
- normalizes inbound to a common envelope
- formats outbound natively (Slack blocks vs email HTML vs SMS text)
- handles its own backoff and reconnect

**Amebo today:** `channels/` contract is *route-based* — Slack and web
arrive as HTTP requests. That's fine for webhook-style channels. It's
**not** enough for:
- Email (IMAP poll)
- Telegram (long-poll, no public webhook)
- Signal / SMS (Twilio webhook is fine; CLI bridges aren't)
- Bluesky DMs (poll or subscription)

**Where it fits:** new module `backend/src/gateway/`, parallel to
`channels/`. Same `InboundEnvelope` contract on the way in, but a
long-running asyncio process per adapter. `gateway/run.py` boots them
all; each one calls `dispatch.handle_envelope()` exactly like web/slack
routes do today. Reuse, don't replace.

**Specifically borrow from Hermes:**
- `gateway/platforms/base.py` connection lifecycle (connect / disconnect /
  reconnect with backoff)
- `gateway/platforms/email.py` IMAP idle pattern
- `gateway/platforms/telegram.py` long-poll loop

Skip everything in `gateway/run.py` related to per-session AIAgent caching
— amebo already has `ConversationManager`.

---

### 2. Delegate-as-primitive (subagents with isolated context)

**Hermes shape:** `tools/delegate_tool.py` spawns child AIAgent instances
with:
- fresh conversation (no parent history)
- own task id (own filesystem cache, own approvals)
- restricted toolset (configurable, with `DELEGATE_BLOCKED_TOOLS` always
  stripped — no recursive delegation, no `memory`, no `clarify`, no
  cross-platform side effects)
- focused system prompt = parent goal + extracted context
- batch mode for parallel subagents via `ThreadPoolExecutor`

Parent only sees the call site and the summarized result. Children's
intermediate tool calls and reasoning never enter parent context.

**Amebo today:** the `POWERS_PLAN` `claude_code` tool is described as a
one-off "spawn Claude Code in a worktree". That's a narrow use of a
general pattern.

**Where it fits:** generalize `claude_code` to `delegate_tool` in
`tools/registry.py`. Any tool that needs a *bounded second loop* (heavy
research, multi-step web scraping, batch outreach drafting) becomes a
delegation. The parent agent never blows its context budget on the
intermediate steps.

This is also the right shape for the **interrogation skill**: a user
asks "what did the claw do for goal X last week?" — the dispatcher
delegates to a subagent with read-only `goals`/`goal_events` access,
gets a clean summary back, parent doesn't drown in 200 event rows.

**Specifically borrow:**
- `DELEGATE_BLOCKED_TOOLS` frozenset pattern (define amebo's own)
- `ThreadPoolExecutor` parallel batch with parent-blocked-until-all-done
- Subagent approval callback indirection (children share parent's HITL
  callback so writes still surface for approval)

---

### 3. Cron features beyond what `GoalScheduler` has today

**Hermes shape:** `cron/scheduler.py` + `cron/jobs.py` ships several
ergonomics that turn cron from "fires a goal" into "useful automation":

| Feature | What it does | Amebo equivalent |
|---|---|---|
| `--script` pre-processing | Python script runs *before* the agent; stdout becomes context. Mechanical fetch / diff / compute on the cheap, agent does only reasoning. | Not in `GoalScheduler`. |
| `[SILENT]` reply pattern | If agent output starts with `[SILENT]`, no notification fires. Lets monitors run hourly without spam. | Not in `GoalScheduler`. |
| Per-job skill chaining (`--skills "arxiv,obsidian"`) | Load specific skills only for this job; keeps prompts small. | Skills are per-instance, not per-job. |
| Per-job delivery target (`--deliver slack:Cxxx`, `--deliver email:foo@bar`, `--deliver telegram:42`) | Each job picks its destination at invoke time, not at config time. | `notify_channel` is per-goal but not per-fire. |
| File-locked tick | `~/.hermes/cron/.tick.lock` so overlapping ticks are safe | `GoalScheduler` already runs in-process; safe today but matters when amebo scales to multiple workers. |

**Where it fits:** extend `goals` schema with optional `pre_script_path`,
`silent_pattern_enabled`, and migrate `notify_channel` to support
multiple comma-separated targets. None of these break v1; all are
additive.

The `[SILENT]` pattern in particular unlocks low-noise monitoring goals
("check the MAIN.md links weekly; only notify if something broke")
without flooding admins.

---

### 4. Webhook subscription model for event triggers

**Hermes shape:** `hermes webhook subscribe <name> --events "pull_request"
--prompt "..." --deliver slack`. Each subscription:
- gets a unique HMAC-signed URL
- maps payload fields into the prompt via templates (`{pull_request.user.login}`)
- runs as a one-shot job on receipt

**Amebo today:** `ORGS_GOALS_CLAW.md` Open Question #3 says event triggers
are "handled elsewhere" — and the elsewhere doesn't exist. Today only
cron and manual triggers actually fire.

**Where it fits:** new route `POST /api/orgs/{org_id}/webhooks/{slug}`
with HMAC verification, maps to a goal with `trigger_config: {type:
"event", event: "<slug>"}`. Listener record stored in a `webhook_subs`
table: `(org_id, slug, secret, target_goal_id, template, last_fired_at)`.

Concrete use cases this unlocks:
- GitHub PR opened → run a "PR review" goal
- Taiga ticket moves to "ready for review" → notify the right channel
- Inbound email with subject prefix → spawn a triage goal
- linkedtrust.us new claim about an org → enrich org context

---

### 5. Use Taiga, don't build a kanban

Hermes ships its own `plugins/kanban/` dispatcher+worker board. **We
should not.** The team already lives in Taiga via `mcp-taiga`. Building
a parallel board would split attention and create another thing nobody
checks.

Instead, the intents view is **Taiga tickets created from goal events**:

- claw starts a goal → opens a Taiga ticket with the goal title, links
  back to amebo's goal id
- each `goal_events` row of interest (`blocked_on_credential`,
  `awaiting_approval`, `failed`) posts a comment on the ticket
- completion closes the ticket with a summary

Implementation: a tiny adapter in `services/intent_publisher.py` that
listens to goal-event writes and pushes to Taiga via the existing tool.
Per-org config: `taiga_project_id` (None = no publishing). That's the
whole intents dashboard.

For the rare case where amebo needs an internal queue (approval
gating, draft-pending-send), use a simple status field on `goals` —
not a new noun, not a new view.

---

### 6. Skill format alignment (so we can reuse Hermes skills directly)

**Hermes shape:** `skills/<topic>/<name>/SKILL.md` with strict YAML
frontmatter:

```yaml
---
name: linear
description: "Linear: manage issues, projects, teams via GraphQL + curl."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
prerequisites:
  env_vars: [LINEAR_API_KEY]
  commands: [curl]
metadata:
  hermes:
    tags: [Linear, Project Management, Issues, GraphQL, API, Productivity]
---
```

Plus optional `scripts/` directory next to it. The whole skill is one
folder; the agent loads it lazily based on context.

**Amebo today:** `prompts/skills/*.md` has the *concept* but probably not
this exact spec. Aligning means we can drop in Hermes's existing skills
(Linear, Notion, Airtable, GitHub, Email, Google-workspace) with
minimal adaptation.

**Where it fits:** standardize on the Hermes frontmatter spec for new
skills. Migrate existing ones in a separate pass. Add `prerequisites`
matching to the dispatcher so a skill that needs `LINEAR_API_KEY` for an
org without a Linear credential is filtered before being offered to the
model.

---

## Genuinely new (not in any amebo doc yet)

### Multi-model routing — judgement, not just config

Hermes lets you pick a model per cron job, per skill, per delegate. We
need the same — different jobs deserve different models on cost, latency,
and reasoning quality. Most useful models are Anthropic-SDK-compatible
or Chat-Completions-shaped, so this is mostly a routing layer, not a
provider abstraction.

**Routing dimensions amebo cares about:**

| Dimension | Example |
|---|---|
| Cost ceiling | "this goal must cost < $0.05 → DeepSeek or Haiku" |
| Reasoning depth | "this is multi-step outreach planning → Opus" |
| Latency need | "user is waiting in chat → Sonnet/Haiku, not Opus" |
| Privacy / locality | "this org requires self-hosted → local model only" |
| Tool-use quality | "this calls 8 tools in a loop → Claude (best tool-use today)" |

**Shape:** add `model_routing` to instance config (default policy) and
allow override per goal (`goal.config.model = "haiku"`) or per delegate
call (`delegate(task, model="opus")`). A small `routing.py` picks a
concrete model+provider from the policy, falls back if first choice
fails or is over-budget.

**Provider-side: stay on Anthropic SDK shape.** Most models we care
about (Claude, OpenRouter-routed everything, Anthropic-compatible
proxies like LiteLLM) speak it. For the few that need Chat-Completions
(direct OpenAI, DeepSeek native, local llama.cpp servers), wrap them
behind a thin `chat_completions_to_anthropic` adapter. One adapter file,
not a full abstraction layer.

**Why amebo (not the LLM provider) holds conversation state:**

| Provider | Server-side conversation memory |
|---|---|
| OpenAI | Yes — Responses API `previous_response_id`; legacy Assistants threads |
| Anthropic | No threads. Memory tool (beta) for model-curated facts; prompt caching for cost |
| Gemini | `cachedContent` for caching, no threads |
| DeepSeek / Qwen / Kimi / GLM / MiniMax | Stateless message arrays |

Amebo's `ConversationManager` already gives the cost benefits via
caching. Using a provider's server-side threads would tie org data to a
vendor account and break LinkedClaims auditability. Stay
client-managed.

---

### LinkedClaims integration — both directions

User flagged the prior chat lacked context for abra, amebo, and
LinkedClaims. The first two are already first-class in amebo. LinkedClaims
isn't — not in `ARCHITECTURE.md`, `ORGS_GOALS_CLAW.md`, or `POWERS_PLAN.md`.

**Read direction (enrich answers):** when amebo encounters a name or
project in a thread/document, query `live.linkedtrust.us` for claims about
that entity. Surface trust evidence in the answer. Example:

> Q: what do we know about Vineeth from 5CentsCDN?
> A: <abra context> + Trust signal: 2 attestations on
> live.linkedtrust.us from <issuer A>, <issuer B> about delivering
> on-time CDN migrations. No negative claims.

Adapter goes in `tools/linkedclaims_read.py`, called as another knowledge
skill alongside abra.

**Write direction (audit-as-claims):** every meaningful claw action
produces a LinkedClaim. "amebo (acting for org X) sent email to person Y
about topic Z at time T". The claim is signed by amebo (DID) and stored
on the trust graph. This makes amebo's audit trail:
- portable (any verifier can read it)
- verifiable (signature chain)
- queryable from outside amebo (Changemaker and other consumers can ask
  the trust graph "what has amebo done for this org?")

Adapter goes in `tools/linkedclaims_write.py`, called from
`goal_events` writer as a side-effect.

**Why this matters more than it looks:** amebo's claw acts on behalf of
orgs. Activists, nonprofits, and small businesses won't fully trust an
autonomous agent unless its actions are auditable *outside* the agent's
own database. LinkedClaims gives that without building a separate audit
service.

---

## Component map (for the user's framing)

| User's piece | What it is in amebo | Status |
|---|---|---|
| **abra** — understand local names | `binding_repo.py` → `AmeboStore` subclass of `AbraStore` (per `ABRA_INTEGRATION.md`) | Built, migration to abra-lib in progress |
| **amebo** — claw agent that does things | `GoalDispatcher` + `qa_service._generate_with_thread_context` | Built |
| **intents dashboard** | Not yet — see "Intents as a first-class table" above | **Gap** |
| **Marten / Taiga** | `mcp-taiga` tool, already in instance `allowed_tools` | Built |
| **Odoo / CRM** | `odoo-cli` tool, already in instance `allowed_tools` | Built |
| **Email + all comms channels** | `channels/` contract is route-based; long-running adapters missing | **Gap** (see Hermes pattern #1) |
| **Componentize** | Per-instance `allowed_tools` + planned MCP integration in `POWERS_PLAN` | Architecturally sound; just needs the tools added |
| **LinkedClaims** | Not yet integrated | **Gap** (see "LinkedClaims integration" above) |

---

## Patterns to deliberately NOT import from Hermes

- **Their model abstraction layer** (`agent/anthropic_adapter.py`,
  `bedrock_adapter.py`, etc.). Amebo standardizes on Anthropic SDK;
  multi-provider would be churn for no current value.
- **SQLite session DB + FTS5.** Amebo's `threads` in Postgres + abra
  pgvector already covers cross-session search. SQLite would be a step
  back.
- **TUI and ACP adapter** (`ui-tui/`, `acp_adapter/`). Amebo isn't trying
  to be a developer CLI.
- **Plugin marketplace.** `plugins/` is overkill for amebo's scope.
  Per-instance `allowed_tools` is the right granularity.
- **Honcho dialectic user modeling.** Amebo has abra. Different shape,
  better for orgs.

---

## Open questions for the team

1. **Gateway daemon vs continuing route-based:** is anyone planning to
   ship email-inbound or Telegram before EOQ? If yes, the gateway pattern
   needs to land first. If no, route-based stays fine until then.
2. **Intents table — additive or refactor:** add `intents` alongside
   `goal_events` (additive, cheap), or refactor `goal_events` into
   `(intents, intent_steps)` (cleaner, schema migration)?
3. **LinkedClaims write direction:** does amebo sign claims with its own
   DID, or with the org's DID (and amebo is just the actor)? The latter
   matches "amebo acts for the org" but requires per-org DID management.
4. **Skill format migration:** rename `prompts/skills/` to `skills/` and
   adopt Hermes frontmatter spec, so we can pull in their Linear / Notion
   / Google-workspace skills directly?
5. **Delegate primitive timing:** is this v1.x (alongside the
   `claude_code` tool in `POWERS_PLAN`), or v2 after the rest of the
   power tools land?

---

## Method note

Hermes repo cloned to `/tmp/hermes-agent` at HEAD on 2026-05-27.
Files referenced are valid as of that commit; URLs in this doc are not
permalinks. Amebo state read at `main` @ `285a190`.

The Claude.ai share linked in the original conversation
(`/share/406cec3a-...`) could not be retrieved unauthenticated; this
analysis was written from current repo state plus the cited Hermes source.

---

*Prepared on the `docs/hermes-patterns` branch. Not yet reviewed.*
