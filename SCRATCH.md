# SCRATCH — cross-session coordination

Living note so concurrent Claude/dev sessions working in this shared directory
don't go at cross purposes. Append your own section; don't delete others'.

---

## 2026-06-01 — coding-agent orchestration (branch `shared/coding-orchestration`)

**Who:** golda's session.

**What:** Adding an event-driven coding-agent orchestration layer on top of the
Claude Agent SDK. Design doc:
`/opt/shared/projects/Active/amebo/coding-agent-orchestration.md`.

**Reusing what already exists** (not rebuilding): the channel contract
(`src/channels/contract.py`), `dispatch.py`, Slack/web adapters, and the
source-agnostic `threads` table + `ThreadRepo`. A coding session attaches to a
`threads.id`.

**New, additive surface only** (no edits to existing request paths, nothing
wired into the live `dispatch.py` → `QAService` path):
- `backend/migrations/013_coding_orchestration.sql` — new tables only
  (`coding_sessions`, `coding_jobs`). Additive, `CREATE TABLE IF NOT EXISTS`.
  Rollback: `DROP TABLE coding_jobs, coding_sessions;`
- `backend/src/db/repositories/coding_session_repo.py`,
  `coding_job_repo.py` — new repos.
- `backend/src/coding/` — new package: models, model router, worktree manager,
  worker interface + stub, Postgres-serialized work queue, orchestrator.

**Safety:** intention thread = one coding session; per-session serialization via
Postgres advisory lock so concurrent inputs to one thread can't race. The real
Claude Agent SDK worker is behind an interface and stubbed for now (subscription
Agent SDK credits land 2026-06-15; API-key auth before that). Nothing here runs
in `amebo-backend.service` yet.

**Status:** in progress. Committing frequently to this branch.
