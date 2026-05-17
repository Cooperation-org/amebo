# Goals / Claw — Go-Live Integration Test Plan

Plan for safely enabling the goals subsystem on the live amebo backend (port 8000, VM 200). The merge of `feature/orgs-goals-claw` into `main` does **not** turn anything on by itself — the system stays inert until an instance gets `goal_mode: "enabled"` AND the scheduler is wired into startup.

The order below is designed so every step is verifiable before the next is taken, and so the live Changemaker integration is monitored at each step.

---

## Phase 0 — Pre-merge sanity (do before merging the PR)

- [ ] Local test suite green: `pytest tests/test_goal_repo.py tests/test_goal_engine.py tests/test_goal_dispatcher.py tests/test_goal_scheduler.py tests/test_goals_api.py tests/test_changemaker_endpoints.py` → 71 passed.
- [ ] Live `/api/embeddings/similarity` and `/api/chat/message` baseline captured (response bodies recorded for diff after each subsequent phase).
- [ ] Confirm `tmp-amebo2-backend` is the right "staging" instance to use, OR spin up a second worktree-based backend on a free port for first-light testing.

## Phase 1 — Merge to main, no behavior change

- [ ] Merge PR #33 → `main`.
- [ ] On VM 200, in the **live working tree** (`/opt/shared/repos/amebo`), do NOT pull yet.
- [ ] In a separate worktree, fetch main and run the full test suite one more time against the live DB.
- [ ] Verify live `/api/embeddings/similarity` unaffected (the DB migration was already applied during development).

**Stop condition:** if anything is unexpected, stop and investigate before the live tree pulls.

## Phase 2 — Pull main into live tree, restart service

This step changes the code the live service runs, but does NOT enable any new feature flag.

- [ ] Snapshot the live DB (or at least `pg_dump -t goals -t goal_events -t organizations -t instances`).
- [ ] `git -C /opt/shared/repos/amebo pull origin main` (will fast-forward through the goals commits + scheduler files; no schema change because migration 009 is already applied).
- [ ] `sudo systemctl restart amebo-backend`.
- [ ] Smoke test in order:
  - [ ] `curl http://localhost:8000/health`
  - [ ] `curl -X POST http://localhost:8000/api/embeddings/similarity -d ...` — compare to Phase 0 baseline.
  - [ ] `curl http://localhost:8000/api/chat/instances/<slug>` — known instance returns name/slug only.
  - [ ] Trigger one end-to-end Changemaker flow from the live app (or the staging app pointed at port 8000).
- [ ] Tail `journalctl -u amebo-backend -f` for 10 minutes during normal traffic; nothing about goals should appear (scheduler still off).

**Stop condition:** any 5xx spike or error log mentioning new modules → roll back to prior `main` and investigate.

## Phase 3 — First goals API call (org-scoped, read-only)

We can hit the goals API without enabling claw mode; reads are safe.

- [ ] Pick a single org (start with a non-Changemaker test org, e.g. a fresh "claw-pilot" org).
- [ ] Mint an API key for that org via existing `/api/auth/api-keys` flow.
- [ ] `curl -H "X-API-Key: ..." http://localhost:8000/api/goals/` → expect `[]`.
- [ ] `curl -H "X-API-Key: ..." -d '{"title":"first goal","trigger_config":{"type":"manual"}}' http://localhost:8000/api/goals/` → expect 201.
- [ ] List, get, events — all 200.

**Stop condition:** anything other than expected JSON. The goals tables are isolated; failure here is contained.

## Phase 4 — Manual dispatch (no scheduler yet)

Still no claw running automatically; we trigger one dispatch by hand.

- [ ] On the same test org, ensure ANTHROPIC_API_KEY env var is set in the systemd unit (already is for amebo-backend).
- [ ] `curl -X POST -H "X-API-Key: ..." http://localhost:8000/api/goals/<id>/dispatch-now`
- [ ] Verify:
  - [ ] Response: `{"status":"completed", ...}` or `{"status":"failed", "error":...}`.
  - [ ] `/api/goals/<id>/events` shows the full audit trail.
  - [ ] Goal row in DB has `completed_at` set.
- [ ] Run a second `dispatch-now` on the same goal → expect `status: "skipped"` ("already completed").

**Stop condition:** dispatcher hangs, never completes, or writes incorrect events. The bounded loop should prevent runaway behavior; if it doesn't, kill the request and investigate.

## Phase 5 — Wire scheduler into FastAPI startup

This is the change that turns the system from "API-only" to "self-running". Land it as a separate small PR after Phase 4 is green.

- [ ] Add an `on_event("startup")` hook in `main.py` that creates and starts `GoalScheduler`. Add an `on_event("shutdown")` hook to call `.stop()`.
- [ ] Gate it on env: `if os.getenv("AMEBO_GOAL_SCHEDULER", "off") == "on": ...`. Default OFF.
- [ ] Deploy with the flag still OFF. Verify `amebo-backend` starts, logs do NOT mention `GoalScheduler started`.

## Phase 6 — Enable scheduler in dev/staging environment

- [ ] Set `AMEBO_GOAL_SCHEDULER=on` for the `tmp-amebo2-backend` service (or a clone) — NOT for `amebo-backend` yet.
- [ ] Restart that instance.
- [ ] Confirm `GoalScheduler started (tick=60s)` appears once in its logs.
- [ ] Confirm `_enabled_org_ids()` returns `[]` because no instance has `goal_mode: "enabled"` yet — tick is a no-op.
- [ ] Watch for an hour; no errors, no DB writes.

## Phase 7 — First opt-in instance

- [ ] On the test org's instance, `UPDATE instances SET config = config || '{"goal_mode":"enabled"}'::jsonb WHERE slug = '<test-instance>';`
- [ ] Create a goal with `trigger_config: {"type":"manual"}` on that org.
- [ ] Wait a tick. Manual goals don't fire, so nothing should happen.
- [ ] Create a goal with `trigger_config: {"type":"cron","expression":"*/2 * * * *"}`.
- [ ] Wait 2–3 minutes. Confirm:
  - [ ] One dispatch event appears in goal_events.
  - [ ] `completed_at` is set.
  - [ ] Logs show one `dispatched` count from `tick()`.
  - [ ] No effect on `amebo-backend` (port 8000) — Changemaker still healthy.

## Phase 8 — Promote to live amebo-backend

Only after Phase 7 has been stable for at least 24 hours.

- [ ] Set `AMEBO_GOAL_SCHEDULER=on` on `amebo-backend`. Restart.
- [ ] No instances on live amebo-backend should have `goal_mode: "enabled"` yet — scheduler runs but has no work.
- [ ] Watch journal for a full day. Confirm:
  - [ ] No goal-system errors.
  - [ ] No regression in `/api/embeddings/similarity`, `/api/chat/message`, document ingestion (compare against Phase 0 baseline).
  - [ ] Changemaker app reports normal behavior to users.

## Phase 9 — Real org opts in

The first real org (Changemaker, RTV, etc.) is enabled by request, not by default.

- [ ] Discuss with the org owner what their first goal should be — start with a low-stakes goal (e.g. "post a daily check-in summary").
- [ ] Set `goal_mode: "enabled"` on their instance.
- [ ] Create the goal with `notify_channel` pointing to a channel the team monitors.
- [ ] Watch the first dispatch closely; share the resulting message with the team for sanity-check before any larger rollout.

---

## Rollback

At any phase, the rollback is one of:

- **Phase 1–2** (code only, no flag): `git -C /opt/shared/repos/amebo checkout <previous main>` and restart service. DB tables are additive — leaving them in place is fine.
- **Phase 5–8** (scheduler running): set `AMEBO_GOAL_SCHEDULER=off`, restart. No DB changes needed.
- **Phase 9** (org opted in): `UPDATE instances SET config = config - 'goal_mode' WHERE id = ...`. Scheduler immediately stops scanning that org on its next tick. Any in-flight dispatch completes normally (no abort).

The goals tables themselves are never dropped during rollback. They are inert when nothing is enabled.

## Monitoring during live phases

- `journalctl -u amebo-backend -f | grep -iE 'goal|claw|dispatch'` — anything goal-related in the logs.
- `SELECT status, count(*) FROM goals GROUP BY status;` — quick health view.
- `SELECT goal_id, action, created_at FROM goal_events ORDER BY created_at DESC LIMIT 20;` — recent activity.
- Existing changemaker integration monitoring (whatever that is today) — must remain green throughout.

## Open questions before Phase 9

These should be resolved before any real org's goal goes live:

1. **Notification channel adapters.** v1 uses a logger fallback. Slack / email / etc. adapters are pluggable but not yet implemented; if a real org needs `notify_channel: "slack:..."` to work, that adapter has to land first.
2. **Tool integration.** v1's dispatcher does a single Claude call with no tools. If the goal needs real action (post to Slack, query abra, edit a doc), tool plumbing has to be wired into `_run_agentic_loop`.
3. **Human-in-the-loop drafts.** For nontechnical orgs, the design says drafts should be reviewed before sending. v1 does not have this flow.
