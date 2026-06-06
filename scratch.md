# Amebo — Session Coordination Board

**READ THIS FILE (not just git log). Update it when you start/finish work.**
Updated: 2026-06-06. (Old scratch → `scratch-2026-06-06-archived.md`.)

## Network note (IMPORTANT)
This VM blocks SSH to `github.com:22`. Pushes work over GitHub's 443 endpoint
(`Host github.com → HostName ssh.github.com, Port 443` in `~/.ssh/config`), but it has been flaky.
The up-to-date local `main` is at **`/home/golda/amebo`** (origin = GitHub). Shared checkouts under
`/opt/shared/repos/*` were stale — reconcile before pulling. Git network calls: disable the Bash sandbox.

## Two tracks — do not collide
- **AUTH/SSO session:** OIDC provider dev→live + deployment. Spec: `~/work/6-06-2026-ITERATION-HANDOFF.md`.
  Deploys feature branches that land in `main`; does NOT build features.
- **ORCHESTRATION (features) session:** builds additive, gated feature branches; merges to `main`.

## Merged to `main` (foundation — additive, currently OFF/unwired)
boundaries doc, draft-approval gate, credential helper, state-decay/GC, reference-integrity claw, output gate.
Migrations 015–017 are file-only (not applied). Integration hooks documented but unwired.

## Feature branches — CRITICAL REVIEW underway (orchestration session, 2026-06-06)
All three pushed to origin. STATUS:
- `feat-pm-claw` — PUSHED (`f87c60a`). REVIEWED ✅ APPROVE. 9 tests pass (re-run). Tests assert the real
  invariants (executor never runs, send gated + deferred, quiet no-op, org-scoping). One follow-up to note at
  wire time: approval-gate send and output-gate digest are two draft paths that must reconcile to one message.
- `feat-tool-layer` — PUSHED (`aecd5bb`). REVIEW FOUND CLI-BINDING BUGS — FIXING before merge (do NOT deploy yet).
  Design/gating correct (default-deny verified; read tools FREE; actuators gated). But 4 CLI bindings were wrong
  vs the LIVE CLIs (confirmed via `--help` 2026-06-06), and the tests encoded the same wrong argv so "passing"
  meant nothing. Corrections (editing in `/home/golda/amebo-tools`, will amend branch + force-push):
    * odoo_search:  `search contacts` → `contact-search <query>` (CLI has no leads search; dropped model param)
    * crm_read_latest_email: `show contact` → `comms <name>`
    * taiga_list:   project optional → `mcp-taiga list <project>` (PROJECT is required positional)
    * taiga_create_task executor: `create <subj> --project` → `create <project> <subject> [-d desc]` (both positional, project required)
  Note: `slack_post_gated` tool gates under action_type `slack_post`; coexists with the pre-existing ungated
  `slack_post` (governed by per-instance allowed_tools — a claw must be granted the _gated_ one only).
- `feat-email-to-task-flow` — PUSHED (`72f569e`). REVIEW PENDING (next). Task-create abstracted behind injected
  `TaskCreator` Protocol (TODO adapter), so the taiga_create_task fix above does not affect it.

## Next steps
1. ~~Push all three~~ DONE (SSH-over-443 fixed: single `Host github.com`, HostName ssh.github.com, Port 443).
2. Finish tool-layer CLI fixes + update tests to correct argv, re-run, amend+push. ← IN PROGRESS
3. Review feat-email-to-task-flow.
4. Merge approved branches to `main`, delete each, push. Auth/SSO session deploys from `main` AFTER merge.
Remaining roadmap: BD-coach claw, self-improving `code_agent` loop (Claude Code subagent → draft PRs). See `~/work/6-06-2026-ITERATION-HANDOFF.md` §7.

## Rules
Additive only. Gate ALL outbound (no message/CRM/Taiga write/PR without the draft-approval gate). Don't touch the other track's files. Never break live (live.linkedtrust.us = VM 508 = SSO provider). NEVER `git stash`.
