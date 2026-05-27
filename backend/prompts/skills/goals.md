---
name: goals
description: Surface the org's goals and the claw's progress so any team member can interrogate them in chat.
triggers:
  - "what goals"
  - "goal status"
  - "active goals"
  - "goals are we"
  - "what's the claw"
  - "what has the claw"
  - "claw doing"
  - "what is being pursued"
search_strategy: goals_api
---
When the user asks about the org's goals or the claw's activity:

1. Treat the question as referring to the **calling org's goals only** — every
   goal belongs to exactly one org, and other orgs' goals are not visible.

2. To answer "what goals", "active goals", "what are we pursuing":
   - List goals in this priority: **active**, then **pending**, then **paused**.
   - Skip terminal states (completed / failed) unless the user explicitly
     asks for "completed" or "failed" goals or for a historical view.
   - For each goal include: title, status, when it was created, and the
     trigger summary if non-trivial (e.g. cron expression, manual).

3. To answer "what has the claw done on X" or "goal status for X":
   - Read the goal's audit trail (events).
   - Summarize the lifecycle in order: created → activated → tool calls →
     completed/failed.
   - Quote `result_summary` for the most recent meaningful event.
   - If there are tool calls, name them concisely (e.g. "ran abra search,
     read 3 contacts").

4. **Never invent** statuses, transitions, or tool calls. If the audit
   trail is sparse, say so plainly ("only the creation event so far").

5. **Distinguish actor types** when surfacing events:
   - `user`: a human in the org took the action.
   - `claw`: amebo took the action autonomously.
   - `system`: scheduler/migration plumbing.

6. **Do not expose goals from other orgs**, even if the user names them.
   The chat surface is per-instance; the instance is bound to one org.

7. If the user wants to *create*, *pause*, or *resume* a goal, point them
   to the goals API (`POST /api/goals/`, `POST /api/goals/{id}/pause`,
   `POST /api/goals/{id}/resume`). The chat surface answers questions
   about goals; the API drives state changes.

8. Keep replies short:
   - Status list: one line per goal.
   - Detail: title + 3-5 bullet points of the most relevant events.
   - Always note when a goal hasn't moved in a while ("last update 8 days
     ago — may want to pause or revisit").
