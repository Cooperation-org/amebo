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

### Amebo as a code-touching agent — gaps

Architecture supports it (tool registry, instance config, claw pattern are the right shape), but the tools and the sandbox are missing.

Needed if we ever want amebo to write code on behalf of an org:

1. **Repo-scoped tools** in `backend/src/tools/registry.py`:
   - `repo.read_file(path)`, `repo.list_files(glob)`
   - `repo.edit_file(path, old, new)`, `repo.write_file(path, content)`
   - `repo.run_tests()` (bounded, sandboxed)
   - `repo.commit(message)`, `repo.push(branch)` — gated on approval
2. **Per-org git repo manager** — wired up to the GitHub-org-per-amebo-org model from the amebo-summary. Credential management via GitHub App or fine-grained tokens.
3. **Per-dispatch sandbox** — `git worktree add` per goal so concurrent dispatches don't fight; clean up on completion.
4. **Bash/exec tool with strict sandboxing** — biggest security surface. Probably warrants its own VM or container per org.
5. **Mandatory human-in-the-loop on push/merge** — same gate as the nontechnical-org draft-approval flow above. Auto-push is not allowed in v1 even if we add the rest.
6. **Cost ceiling per goal / per org** — Claude Code limits its own runaway; a code-touching claw must too.

Realistic framing: turning amebo into a coding agent is essentially building a Claude-Code-clone scoped to an org. That's a project, not a feature. Track as a separate initiative — don't try to retrofit onto v1.
