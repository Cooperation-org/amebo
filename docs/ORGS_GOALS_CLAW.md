# Orgs, Goals, and the Claw

Design notes for the Org / Goal / Claw subsystem in amebo.

## What We Are Trying To Do

Amebo today is a knowledge-cooperation tool for a group — it answers questions, holds conversation state, and routes through tools. It is reactive: a user asks, amebo answers.

We want amebo to also be able to **act on behalf of an org**, periodically, toward an explicit goal, while staying aligned with the org's vision and values. This is the "claw" — autonomous, transparent, opt-in.

Concretely:
- An org can declare goals (short / medium / long term).
- A goal has a trigger (schedule or event) and a notification target.
- When the trigger fires, amebo enters claw mode for that goal: it pursues the goal using its existing agentic loop, then reports back.
- All claw activity is recorded (audit trail) so any user in the org can interrogate what happened.

The claw is a thin layer. Core Q&A is unaffected when claw mode is disabled — and it is disabled by default.

## The Core Grouping Noun: Org

Amebo is organized around **Orgs**. An org is the top-level container — not Slack-specific. A Slack workspace IS one of an org's resources; an org may also have email, LinkedIn, documents, a Git repo, team members.

Decisions:
- `orgs` is a real table in amebo's DB.
- `instances` gets `org_id` (one instance per org).
- Existing `workspace_id` in Slack-related tables stays — Slack data is still per-workspace; workspace belongs to an org.

When an external app (Changemaker, etc.) calls amebo, it passes its own org reference. Amebo's `org_id` may be that external reference or amebo's own — that decision belongs to the integrating app.

## Storage Split: Structured vs. Semantic

We need both structured data (status, schedules, audit) and semantic data (vision, values, current context). They have different access patterns and different consumers.

**DB (PostgreSQL) — structured:**
- `orgs` — id, slug, name, settings (JSONB for non-semantic config)
- `instances.org_id` — link to org
- `goals` — id, org_id, title, description, status, trigger_config, notify_channel, timestamps
- `goal_events` — audit trail: who/what acted, what happened, when

**Abra — semantic:**
- Vision, values, critical thinking notes, current org context
- Stored as content blobs with hot-tag flags
- Queried at runtime when building context for the claw
- Other apps reading the same org can use the same source

Why split: scheduling and status need transactional DB. Semantic content benefits from RAG and is shared across apps. Each type lives where it's strongest. No duplication.

## The Claw

The claw is **not** a new core. It is:

1. A scheduler that picks up pending goals on a tick.
2. A dispatcher that calls the existing `_generate_with_thread_context` agentic loop with the goal as the task.
3. A persistence layer that writes audit events to `goal_events`.
4. A notifier that posts results to the configured channel on completion.

Coupling to core: one `if instance.goal_mode == "enabled"` check in the scheduler. That is the entire integration. When disabled, the claw is inert.

The claw uses the same tools the instance already has — `abra`, `odoo-cli`, etc. — gated by the instance's existing `allowed_tools` config. No new tool authority.

### Goal Lifecycle

```
pending → active → completed
          ↓
          failed | paused
```

- `pending`: created but not yet picked up. Manual goals stay here until triggered.
- `active`: claw is currently working on it. Single dispatch at a time per goal.
- `completed`: claw reported success against `target_criteria`.
- `failed`: claw ran but could not complete. Reason in events.
- `paused`: a user explicitly paused it.

### Trigger Types

`trigger_config` JSON supports:
- `{"type": "cron", "expression": "0 9 * * *"}` — periodic
- `{"type": "event", "event": "new_content"}` — fire when amebo sees a matching event
- `{"type": "manual"}` — only fires when a user (or API call) activates it

## Interrogation

Any user in the org can ask amebo about the org's goals via normal Q&A. A `goals.md` skill matches questions like "what goals are active", "what did the claw do on X", "who's working on Y". The skill reads from `goals` and `goal_events`.

No new UI needed for v1. The chat surface IS the interrogation surface.

## What This Replaces / Affects

Replaces: nothing. This is additive.

Affects:
- `instances` table gets `org_id`.
- Scheduler service grows one new branch (goals).
- Conversation manager: no changes.
- Q&A path: no changes.
- Changemaker's calls to `/api/embeddings/similarity`, `/api/chat/message`, document ingestion: no changes.

## Deployment

- Built on a feature branch off `rearchitect`.
- Tested locally and on the `tmp-amebo2-backend` instance (port 8001).
- Does NOT touch the live `amebo-backend` instance until explicit approval.
- Test coverage expanded for the existing Changemaker-facing endpoints before any new code lands.
- Feature flag (`goal_mode`) defaults to `disabled` for all existing instances.

## Open Questions

These do not block v1 but should be revisited:

1. Cross-org goals (collaborations between orgs) — out of scope for v1.
2. Goal hierarchies / dependencies — out of scope for v1.
3. Long-running goals that span multiple dispatches — supported by status, but the "resume context" mechanic needs design.
4. Human-in-the-loop drafts (claw drafts a message, human approves before send) — default for nontechnical orgs per the amebo-summary; needs a draft-approval flow.

## Claude Code patterns — what we used and what we didn't

Amebo's kernel already borrows heavily from Claude Code. The claw layer extends that. Listing the gaps so they're easy to find later.

### Borrowed in v1

- **ConversationManager** — cache-pinned-prefix + thread compaction + 24h GC, directly modeled on Claude Code's context management.
- **Agentic loop** — "give the model tools, let it decide what to search" (in `qa_service._generate_with_thread_context`).
- **Bounded tool rounds** — defensive cap, same shape as Claude Code's limits.
- **Skills as markdown + frontmatter** — same convention.
- **Per-instance allowed_tools** — analogous to Claude Code's settings permissions.

### Patterns we did NOT bring in (future work)

- **Subagents** — Claude Code spawns sub-Claude instances for parallel or context-isolated work. Multi-step goals would benefit; v1 uses a single bounded loop.
- **Plan mode / ExitPlanMode** — explicit "design first, get approval, then act" split. The amebo-summary says drafts for nontechnical orgs should be reviewed before sending; that pattern lives here. Needs DB state (e.g. `draft_pending_approval`) and an approval API.
- **Internal TaskCreate/Update** — Claude Code's per-session todo list that persists across turns. The `goal_events` table is similar but per-goal, not per-step. If a goal has internal sub-steps, we have no place to track them yet.
- **Hooks / event-driven triggers** — `trigger_config: {type: "event"}` exists in the schema and `goal_scheduler._should_fire` returns False for it (handled "elsewhere"), but the elsewhere — an event bus that listens for "new content", "incoming email", "Slack mention", etc. — does not yet exist.
- **Streaming responses** — Claude Code streams tokens; the dispatcher returns the full message at end. Fine for v1; matters when goals get long.

### Amebo as a goal-pursuer that sometimes needs code

Goals will sometimes require a coding component (update an org's docs repo, change a config, prepare a PR). The right path is **not** to rebuild coding infrastructure inside amebo — it's to **use Claude Code as a subagent** for the coding portion of a goal.

**Preferred future architecture:**

```
GoalDispatcher
  ↓ pursues goal, decides it needs code
  ↓ invokes a "code_agent" tool
code_agent.run(repo_path, task_description)
  ↓ spawns Claude Code in a per-dispatch git worktree
  ↓ returns: diff summary, branch name, tests-passed status
GoalDispatcher
  ↓ records the result as a tool_call event
  ↓ continues with the goal (e.g. opens a PR, posts a notification)
```

This sidesteps almost every gap in the earlier "amebo as code-touching agent" framing:

- No need to reimplement read/edit/write/test tools — Claude Code already has them.
- No need to design a bash sandbox — Claude Code's permission model handles it.
- Per-org git repo + per-dispatch worktree are still amebo's job, but those are small.
- Human-in-the-loop survives naturally: amebo can open a draft PR and ask for review before merge.
- Cost ceiling is per-Claude-Code-invocation, configurable per goal or per org.

**Minimum pieces amebo still has to build:**

1. **Per-org repo manager** — wires the org's primary git repo (from the amebo-summary's onboarding model) into the dispatcher's working directory. GitHub App or fine-grained token for credentials.
2. **Per-dispatch worktree** — `git worktree add` for isolation; cleanup on completion.
3. **`code_agent` tool in the registry** — wraps the Claude Code invocation (likely via Agent SDK, or via `claude -p "..."` subprocess), passes task description + goal context, captures the diff/branch.
4. **PR / draft flow** — `code_agent` reports back; amebo decides whether to auto-PR or queue for human review based on goal config and org type (nontechnical orgs always queue).

This keeps amebo's role clear: **amebo holds the goal, the context, and the audit trail; Claude Code does the actual coding inside a bounded scope.** Composition, not duplication.

Out of scope for v1, but tracked here so the dispatcher's tool integration point (`_run_agentic_loop`) doesn't get prematurely shaped in a way that makes this harder later.

## Comparison to OpenClaw

OpenClaw is a self-hosted autonomous-agent framework with a documented 5-component architecture (Gateway / Brain / Memory / Skills / Heartbeat). Useful to compare so we know what we already match, what we deliberately do differently, and what we should consider adopting.

| Component | OpenClaw | Amebo equivalent | Notes |
|---|---|---|---|
| Gateway | Single WebSocket process; "single source of truth" for sessions and routing | HTTP routes per channel + `channels/` dispatch module | Theirs is more centralized; ours is more multi-tenant-friendly. Different shape, similar role. |
| Brain | ReAct loop (Reasoning + Acting), LLM-agnostic | `qa_service._generate_with_thread_context` agentic loop | Same shape, ours doesn't explicitly tag a "reasoning" phase. Could add structured ReAct prompting later. |
| Memory | Local Markdown files + daily logs + compaction | `threads` + `thread_turns` DB + abra content + ConversationManager compaction | Theirs: transparent, portable, single-user. Ours: queryable, multi-tenant, scales. Different tradeoffs. |
| Skills | 25+ built-in tools, JSON Schema | `tools/registry.py` + `prompts/skills/*.md`, ~3 tools | **Real gap.** Amebo's tool inventory is thin. |
| Heartbeat | 30-min scheduler checks pending tasks | `GoalScheduler` 60s tick | Same idea, similar cadence. |

### Where amebo is ahead

- **Org as a first-class entity.** OpenClaw is single-user / self-hosted. Amebo is multi-tenant by design.
- **Vision/Values/Goals as primitives** — OpenClaw has tasks (action-oriented); amebo has explicit goal tracking with alignment to org context.
- **Structured audit trail** — `goal_events` is queryable; Markdown logs are human-readable but harder to aggregate or analyze.
- **pgvector RAG** integrated through abra; OpenClaw relies on file scanning.

### Where amebo has gaps (vs OpenClaw)

1. **Tool inventory.** OpenClaw ships 25+ skills; we have abra, odoo-cli, mcp-taiga, and not much else. The tool registry is the right shape — it just needs more entries. Web search, file fetch, basic HTTP, calendar, email composition, etc., would unlock most "useful agent" scenarios.
2. **Channel breadth.** Slack-first plus web; OpenClaw connects to Slack + WhatsApp + others. Email primary (per amebo-summary, for nontechnical orgs) is documented but not yet implemented.
3. **No explicit ReAct framing in the prompt.** Adding "think step by step, then act, then observe" structure to the dispatcher's system prompt could improve goal pursuit, especially multi-step ones.
4. **No Markdown-first transparency surface.** For nontechnical orgs, a Markdown log of "what the claw did today" might be more inspectable than a SQL audit trail. Easy to bolt on as a read view over `goal_events`.
5. **No unified gateway** for connecting external apps. Today each app integrates via `/api/embeddings/similarity`, `/api/chat/message`, etc. A WebSocket-style gateway would be overkill for the current shape but worth revisiting if many channels need real-time bidirectional comms.

### What we deliberately do differently (and would keep)

- **Multi-tenant org isolation at the DB level.** OpenClaw's local-Markdown design can't safely host multiple orgs.
- **Structured DB persistence** for goals/events. Necessary for the interrogation skill and for any SQL-based monitoring.
- **Per-instance config** (identity prompt, allowed tools, knowledge sources). OpenClaw has one user; we have many orgs.

Net: amebo is structurally similar to OpenClaw at the kernel level but built for a different shape of customer (orgs vs individuals). The most actionable gap for v1.x is **tool inventory** — adding 5-10 more general-purpose tools to `tools/registry.py` would close most of the practical distance.

Sources: [OpenClaw Explained (Medium)](https://medium.com/@cenrunzhe/openclaw-explained-how-the-hottest-agent-framework-works-and-why-data-teams-should-pay-attention-69b41a033ca6), [How OpenClaw Works (Medium)](https://bibek-poudel.medium.com/how-openclaw-works-understanding-ai-agents-through-a-real-architecture-5d59cc7a4764), [OpenClaw Complete Guide (Milvus)](https://milvus.io/blog/openclaw-formerly-clawdbot-moltbot-explained-a-complete-guide-to-the-autonomous-ai-agent.md).
