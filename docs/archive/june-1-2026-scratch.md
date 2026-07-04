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

**Status:** first slice landed and tested. Migration 013 applied to the `amebo`
DB (additive; existing tables untouched). `tests/test_coding_orchestration.py`
passes (4/4): per-thread session, seq ordering, Postgres one-in-flight
serialization, model routing, end-to-end stub flow. Tests self-clean (no residue).

Added `src/coding/runner.py` (`CodingRunner`: asyncio start/stop + tick loop,
mirrors `GoalScheduler`) and `tests/test_coding_unit.py` (12 unit tests, no DB,
in-memory fakes). Coding tests: 16/16 pass. Full suite still collects (242).

Added HTTP route `src/api/routes/coding.py` (POST `/api/coding/message`,
GET `/api/coding/sessions/{id}/jobs`), **flag-gated** in `src/api/main.py` behind
`CODING_ENABLED` (default false, mirrors `DEV_AUTH_ENABLED`) and auth-protected
via `get_current_user`. With the flag OFF the route is absent and the app is
unchanged (verified). `tests/test_coding_route.py` (6 tests, no DB) covers run/
no-run/hint/validation/list/auth. Coding tests now 22/22.

**Not done yet:** real `AgentSdkCodingWorker` (auth + SDK session/worktree run;
subscription Agent SDK credits land 2026-06-15). Starting `CodingRunner` at app
startup. `amebo-backend.service` is unchanged and the flag is OFF in prod, so
nothing here executes there.

---

## 2026-06-05 — REVIEW REQUESTED: email→CRM poller

Design doc: `docs/email-poller-architecture.md`. Please review/comment before code.

Summary: send/BCC email to one inbox (amebo2019@gmail.com); poller files it.
Separation of concerns is the hard rule — amebo polls, Odoo + abra each work
independently, resolver is pluggable (`OdooResolver` default = To: → contact;
`AbraResolver` later). Plus-alias routing (+crm/+project/+task/+rag), resolution
order (reply-headers → To:/Cc → body token → dead-letter), idempotency on
Message-ID. MVP = `+crm` → To: match → `odoo-cli log` to chatter; rest stubbed.
Open questions for reviewers at the bottom of the doc.
