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
