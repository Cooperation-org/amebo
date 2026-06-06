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

## Feature branches — BUILT + TESTED, awaiting CRITICAL REVIEW before merge
(Golda: review carefully before merging.)
- `feat-pm-claw` — PUSHED (`f87c60a`). 9 tests pass. PM daily-standup claw (read Taiga+goal_events → one standup via output gate; off-track flags; outbound gated).
- `feat-tool-layer` — local `/home/golda/amebo-tools` (`aecd5bb`), PUSH PENDING. 26 tests. Read tools (odoo_search, crm_read_latest_email, abra_search, taiga_list) + gated actuators. NOTE: registers `slack_post_gated` (a `slack_post` already exists). TODOs on unconfirmed CLI subcommands (mcp-taiga create flags, odoo chatter read) — fail safe.
- `feat-email-to-task-flow` — local `/home/golda/amebo-flagship` (`72f569e`), PUSH PENDING. 6 tests. Flagship: latest forwarded CRM email → drafted Taiga task + Slack notify, ALL outbound held as approval drafts (never sent directly).

## Next steps (whoever picks up)
1. Push `feat-tool-layer` + `feat-email-to-task-flow` (via the 443 route).
2. CRITICAL REVIEW each before merge — especially `feat-tool-layer` (subprocess/CLI execution; confirm the TODO'd CLI subcommands against the real `mcp-taiga`/`odoo-cli`).
3. Merge to `main`, delete the branch.
4. Auth/SSO session deploys from `main`.
Remaining roadmap: BD-coach claw, self-improving `code_agent` loop (Claude Code subagent → draft PRs). See `~/work/6-06-2026-ITERATION-HANDOFF.md` §7.

## Rules
Additive only. Gate ALL outbound (no message/CRM/Taiga write/PR without the draft-approval gate). Don't touch the other track's files. Never break live (live.linkedtrust.us = VM 508 = SSO provider). NEVER `git stash`.
