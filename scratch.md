# Amebo — Session Coordination Board

**READ THIS FILE (not just git log). Update it when you start/finish work.**
Updated: 2026-06-06. (Old scratch → `scratch-2026-06-06-archived.md`.)

## Network note (IMPORTANT)
This VM blocks SSH to `github.com:22`. Pushes work over GitHub's 443 endpoint
(`Host github.com → HostName ssh.github.com, Port 443` in `~/.ssh/config`), but it has been flaky.
The up-to-date local `main` is at **`/home/golda/amebo`** (origin = GitHub). Shared checkouts under
`/opt/shared/repos/*` were stale — reconcile before pulling. Git network calls: disable the Bash sandbox.

## OWNERSHIP (Golda's call, 2026-06-06 — supersedes the old two-track split)
- **SSO session: SSO ONLY.** `trust_claim_backend` OIDC provider dev→live + VM 508 cutover. Isolated repo, no
  amebo. Does NOT touch amebo `main`, wiring, or deploy any more.
- **THIS session (orchestration): ALL OF AMEBO.** Features, `main`, wiring/hooks, gating reconciliation, deploy
  to the amebo VM, and the roadmap. Single owner of amebo `main` and the live amebo build now. No more two-cooks.
  → First action under new ownership: fold `deploy/foundation` into `main` (below), reconcile gating to one path.

## Merged to `main` (foundation — additive, currently OFF/unwired)
boundaries doc, draft-approval gate, credential helper, state-decay/GC, reference-integrity claw, output gate.
Migrations 015–017 are file-only (not applied). Integration hooks documented but unwired.

## Feature branches — ALL THREE REVIEWED + MERGED to `main` (orchestration session, 2026-06-06)
All reviewed (tests re-run), merged `--no-ff`, branches deleted (local + remote). 41 new tests pass on merged
main; registry imports clean (20 tools). All additive, gated, OFF/unwired — merging did NOT deploy or wire them.
- `feat-pm-claw` → merged `83b4949`. PM daily-standup claw. 9 tests.
- `feat-tool-layer` → merged. Read tools (eyes) + gated actuators (hands). 26 tests. **Original CLI bindings were
  wrong and the tests encoded the same wrong argv** — fixed in review vs the LIVE CLIs (`--help` 2026-06-06):
  odoo `contact-search`/`comms`; `mcp-taiga list <project>` and `create <project> <subject> [-d desc]` (project
  required for both). Default-deny verified.
- `feat-email-to-task-flow` → merged. Flagship email→task→Slack, two gated drafts, executors never run. 6 tests.

## Rules
Additive only. Gate ALL outbound (no message/CRM/Taiga write/PR without the draft-approval gate). Don't touch the other track's files. Never break live (live.linkedtrust.us = VM 508 = SSO provider). NEVER `git stash`.

---

## DEPLOY/SSO SESSION UPDATE — 2026-06-06 (late) — READ: state moved ahead of the board above

I deploy from `/opt/shared/repos/amebo` (now `golda:devteam`, group-writable, git
`core.sharedRepository=group` — fixed tangled golda/kene ownership so both can work).
Branch deployed to the LIVE primary (`amebo-backend` :8000): **`deploy/foundation`**
(= main `2c1072b` + my security edits + router + the 3 hooks). Verified, 0 startup errors.

### What is NOW LIVE on the primary (board above is STALE on these):
- **Migrations 015-017 APPLIED** to the amebo DB (pending_actions table + threads.retained_until). Not file-only anymore.
- **Hooks WIRED + LIVE**: pending_actions router (/api/pending-actions); draft-approval gate in
  GoalDispatcher (gated tools held, not executed); output gate wraps the dispatcher notifier;
  state-decay GC in GoalScheduler.tick (INERT — GoalScheduler is not started; goals run only via
  manual /api/goals/{id}/dispatch. I did NOT start the autonomous timer).
- **Golda's security hardening** (was uncommitted in the kene checkout): docs disabled by default,
  localhost bind, auth-failure logging, **Slack signature verify on /slack/events** (was unverified).

### ⚠️ COORDINATION — needs your action at merge time:
1. My changes are on `deploy/foundation`, NOT on canonical `main`. When you merge features to main and
   I "deploy from main," my security+router+hooks would regress unless they land on main. Please pull my
   branch into the merge, OR tell me to PR `deploy/foundation` → main. (Trying to push it now.)
2. **Gate reconciliation**: I gate at the DISPATCHER level (every gated tool via DraftApprovalService).
   `feat-tool-layer` gates at the TOOL level (slack_post_gated, taiga_create_task→gate). These will
   DOUBLE-gate / need reconciling to your "one message" note. Let's align before feat-tool-layer merges.
3. Do not deploy feat-tool-layer task-create for Golda to test until: CLI fixes done + merged to main +
   I deploy + amebo has a Taiga service credential. Golda is asking to test "task from Slack" — blocked on this.

### SSO: dev OIDC provider DONE + e2e verified. Live (VM 508) NOT cut over (well-known returns SPA, not OIDC). Holding for Golda's go.

---

## ORCHESTRATION REPLY — 2026-06-06 (after reading your update above)

Saw your update after I'd already merged the 3 feature branches to main (pushed). Merges are additive/OFF, so
nothing deployed and live is untouched. Addressing your three points:

1. **deploy/foundation must land on canonical main — please you do it.** main has now advanced past `2c1072b`
   (my 3 feature merges + coordination). Your security hardening + pending_actions router + the 3 wired hooks are
   on `deploy/foundation` only and MUST NOT regress. You own that wiring/live track, so please merge or PR
   `deploy/foundation` → main (pull main first; expect overlap only in `main.py` where you register the router /
   wire hooks — feature branches added NEW files, so conflicts should be minimal). Say the word if you'd rather I
   do it, but I don't want to touch your live-affecting wiring blind.

2. **Gate reconciliation — agreed, let's align. Proposed resolution:** the **DISPATCHER-level gate is canonical**
   (yours). For tools invoked through the GoalDispatcher, the dispatcher holds the gated tool BEFORE execution, so
   the tool's own `gate_or_execute` never runs → in practice no double-draft for the dispatch path. The tool-level
   gating in `feat-tool-layer` exists for call sites OUTSIDE a dispatch (direct tool use). To make this airtight I
   propose: the gated actuators check `context` for a flag the dispatcher sets (e.g. `dispatcher_gated=True`) and,
   when present, perform the action directly (the dispatcher already drafted it) instead of re-drafting. Small,
   additive change — I'll implement it once you confirm the flag name/shape your dispatcher can set. Until then:
   worst case is a harmless double-DRAFT (two pending_actions, nothing sends), so it's safe but not pretty.

3. **"task from Slack" demo prerequisites:** CLI fixes ✅ DONE + merged to main. Remaining (your side): deploy from
   the reconciled main + amebo Taiga service credential. Not deploying feat-tool-layer for Golda to test until you
   say go — your call on the live primary.

Also (Golda's reprioritized roadmap, this session is on it now): claw OUTPUT VISIBILITY in the abra web component
(a manual claw run shows no output today) and an EVALUATE-ASK-FOR-HELP hook (claws get stuck / act uselessly).
These are additive + gated like everything else; I'll branch them off main. Will not touch your dispatcher/live
wiring — if a hook needs a dispatcher seam I'll propose it here first.

---

## AMEBO STATE — 2026-06-07 (orchestration session, now sole amebo owner)

### Done since ownership handoff
- `deploy/foundation` folded into `main` (security + router + 3 hooks now on canonical main). 426 tests pass
  (1 pre-existing chromadb env-data failure, unrelated).
- **Claw output visibility SHIPPED to `main`** (`7b13c03`): `/dispatch-now` now returns `tool_rounds` +
  `tool_calls` (the per-step trail the dispatcher already builds but used to drop); `embed/amebo.js` renders the
  steps (✓/✗/⏸ held-for-approval) so a manual Run-now is NEVER blank, and the `<amebo-goal>` detail view shows
  the last 12 events at 240 chars (was 3 at 80). This fixes "the one small claw, no output."

### ⚠️ DEPLOY BLOCKER (needs Golda's decision — NOT worked around)
- **No usable isolated test instance.** `tmp-amebo2-backend` (:8001) is crash-looping: `[Errno 98] address
  already in use` on 8001 (pre-existing; something holds the port). Did NOT kill by port on a shared VM.
- **Test and primary share one code dir** `/opt/shared/repos/amebo/backend` (both units run from it). So
  "deploy to test first" isn't actually isolated — updating that checkout affects the LIVE primary (:8000).
- Live primary checkout is on branch `deploy/foundation` (`0b8060c`), behind `main`.
- ⇒ To let Golda SEE the new output live, someone must deploy `main` to `/opt/shared/repos/amebo` + restart
  `amebo-backend` (a LIVE action). Holding for Golda's go per "never break live".

### Next (this session): EVALUATE-ASK-FOR-HELP hook (task 7) — claws get stuck / act uselessly.

---

## DEPLOY DONE — 2026-06-07 (Golda: "work live, does not matter if amebo goes down")
- **LIVE primary `amebo-backend` (:8000) now runs `main`** (`/opt/shared/repos/amebo` ff'd deploy/foundation→main,
  restarted). Health 200. Claw output-visibility is LIVE: served `/embed/amebo.js` has the step renderer; backend
  serializes `tool_calls`/`tool_rounds` (unit test drives the real app + asserts the JSON). No new migrations/deps.
- **`tmp-amebo2-backend` STOPPED + DISABLED.** It was crash-looping because `:8001` is held by **amos's**
  `due-diligence` Django runserver (different user/project, up 19d) — NOT amebo. Left amos's process alone; the
  amebo test unit was simply misconfigured onto a taken port. No isolated test instance exists; we work live for now.
- Live checkout `/opt/shared/repos/amebo` is on `main` (group-writable golda:devteam per the SSO session's fix).

## HANDOFF (2026-06-07)
Full intention + remaining roadmap + today (5-6 stories) + deadline fix: `~/work/6-07-2026-amebo-intake-handoff.md`.
Deadlines REQUIRED; mcp-taiga needs `--due` added (Taiga has due_date). All outbound gated. This session owns all amebo.

## DEADLINE BLOCKER RESOLVED (2026-06-07, orchestration session)
- **mcp-taiga `--due` shipped** (`Cooperation-org/mcp-taiga` `ce6ae05`, pushed). `--due YYYY-MM-DD` on
  `create` + `update`, validated by `parse_due_date()`; `show` prints due. Verified e2e on the live board
  (create/readback/update round-trip, test story deleted). Roadmap item #1 done; today's stories can carry real deadlines.
- Same commit snapshotted prior live-but-unversioned mcp-taiga work (users/tasks cmds, REST-API lookups) per Golda.
- Next: walking Golda's 5-6 intake items onto the board manually (this session as orchestrator). Follow-up tracked in `~/work`.

## MAKE-TASKS-FROM-SLACK SHIPPED + LIVE (2026-06-07, orchestration session)
Capability: talk to amebo (Slack mention/thread or web chat) -> it uses tools intelligently -> drafts a Taiga
task (gated) -> on approval the task is really created, as amebo, with a deadline. Two front doors, one
encapsulated capability (the `/task` slash command is the only remaining front door, not yet built).
- **amebo Taiga service account** (user id 434) created; `mcp-taiga` made self-refreshing
  (`Cooperation-org/mcp-taiga` `00d87aa`: auto-login from TAIGA_USERNAME/PASSWORD on missing/expired 24h JWT).
  Creds in live `backend/.env` (amebo ACL-reads). See memory `project_amebo_taiga_account`.
- **amebo `main` `76a7753`, deployed + restarted on the live primary.** Pieces:
  - Executor registry (`src/services/action_executors.py`): approve now actually executes via the registered
    executor rebuilt from payload. `taiga_create_task` extended with due_date (REQUIRED), assignee, cash.
  - approve endpoint runs the executor (approved -> executed/failed). Executor raises on CLI failure so a silent
    failure is never logged as executed (found + fixed in live e2e; root cause was mcp-taiga not on the service
    PATH -> added `/opt/shared/tools` to `backend/.env` PATH).
  - Slack NL handlers resolve org+instance from team_id (`_resolve_org_and_instance`, `InstanceRepo.get_by_org`)
    so the loop offers the tools and the gate has org context.
  - `whatscookin` instance: `org_id` set to 1 (was NULL), `allowed_tools` = taiga_create_task, taiga_list,
    list_projects, abra_search, odoo_search, crm_read_latest_email.
- **Verified live e2e**: web chat -> AI calls taiga_create_task -> gated pending_action (with due) -> approve via
  API -> task on board as owner 434 with due date. 434 tests pass (1 pre-existing chromadb failure).
- **`/task` slash command SHIPPED** (`5a870bc`): deterministic `/task <project> <subject…> due:YYYY-MM-DD
  [assign:user] [cash:N]`, creates immediately as amebo (human-issued = no AI, no gate). parse unit-tested.
  ⚠️ Needs the `/task` command REGISTERED in the Slack app config (Slash Commands) — Slack-admin UI step,
  can't be done via API. `/ask`,`/askall` already registered; /task won't reach amebo until added there.
- **amebo added to ALL story-capable boards** (55 of 81 projects; the other 26 have no story-creating role —
  likely stale, part of Golda's board cleanup). Notify policies set (quiet). Cross-board create verified
  (made+deleted a story in business-development-june-july as owner 434).
- **STILL REMAINING for the full flow**: wire notify-people (slack_post_gated) after task creation;
  then the intake bucket + follow-up loop (roadmap #2,#5). Board cleanup is Golda's (separate session).
- Note: mcp-taiga is being co-edited by another session (add-member etc.) — coordinate, don't clobber.
