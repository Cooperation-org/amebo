# Amebo Outreach — Build Specs for Later Agents (2026-07-06)

> AI-drafted (Claude Fable). For Opus/other agents (or devs) picking this up after 7/7.
> Verified today against /opt/shared/repos/amebo (registry, gated_actions, docs) and the
> live `instances` table. Read `amebo/docs/BOUNDARIES.md` + `docs/TOOL_LAYER.md` +
> `docs/DRAFT_APPROVAL_GATE.md` before touching anything. House rules apply: no hacks,
> gated-by-default for anything outbound, humans send.

## Spec 0 — Enable the follow-up tools (config only, 5 minutes) — DO FIRST

Registered in `backend/src/tools/registry.py` but missing from whatscookin's
`config.allowed_tools`: `crm_schedule`, `crm_log_contacted`, `crm_tag_contact`,
`taiga_update_task`, `taiga_add_comment`, `taiga_close_task`, `list_skills`.
This gap is why amebo can create leads/tasks but cannot follow up or close — and it blocks
the `crm-scribe` skill (see `/opt/shared/projects/skills/crm-scribe.md`).

How (per team convention, config lives in DB, no restart needed):
```bash
cd /opt/shared/repos/amebo/backend && set -a && . ./.env
psql "$DATABASE_URL"
-- inspect first:
select jsonb_pretty(config->'allowed_tools') from instances where slug='whatscookin';
-- then append the seven names to that array with jsonb_set / || (write the UPDATE by hand
-- after inspecting; don't blind-paste). All seven are gated actuators — the draft-approval
-- gate still applies, so this adds *draftable* capability, not autonomous sends.
```
Get Golda's OK before the UPDATE (it changes the team agent's behavior).

## Spec 0.5 — Wire the pending-action notifier (small, high value)

The draft-approval gate works (pending_action rows + approve/reject via
`api/routes/pending_actions.py`), but the notification to the approver is a
**stub that only logs** — `draft_approval_service.py:57` carries
`TODO(notify): wire this to the existing notify channel`; `_notify_pending`
uses the instance's `notify_channel` when present, else the logging default.
Golda's chosen flow (amebo suggests → Golda gates → push to team) depends on her
actually seeing the queue. Two options: set the instance's `notify_channel` so
pending actions ping her in Slack, or make checking the pending queue part of the
daily/weekly sweep. Wire the Slack notify — the hook is already there.

## Spec 1 — `send_email` actuator (deprioritized 2026-07-06)

**Priority note (Golda, 2026-07-06):** intro emails "have not been working well — what
works better is to talk in small spaces, the permissioned spaces." So this actuator is
LOWER priority than Spec 0/0.5/3; build it for transactional follow-ups and promised
artifacts, not as the outreach channel.

Amebo drafts outreach but cannot send email at all. `send_email` is pre-listed in
`GATED_ACTIONS` (`backend/src/services/gated_actions.py:80`) but no tool exists.
`email_service.py` (SMTP) serves only auth flows. The intended design is already written:
`docs/MARKETING_COMMS_CAPABILITY.md` — "a drip is a claw"; drive Odoo `mass_mailing` for
CRM audiences; direct SMTP only for non-Odoo audiences.

Order of work (deliverability first, per that doc — do not skip to code):
1. Dedicated sending subdomain + SPF/DKIM/DMARC; List-Unsubscribe; reply-detection
   auto-pause. Without this, sending harms the domain — STOP if not provisioned.
2. Tool impl in `gated_actuators.py` pattern: executor closure →
   `DraftApprovalService.gate_or_execute(action_type='send_email', ...)`. Single-recipient,
   personal-voice sends only; bulk goes through Odoo mass_mailing via a separate
   `odoo_cli`-style path.
3. Register in `registry.py` (`needs_confirmation=True`); it's already default-deny gated.
4. Add to `allowed_tools` for whatscookin only after a test instance run.
5. Tests: `backend/tests/test_tool_layer.py` pattern (mock SMTP + gate).

## Spec 2 — `web_search` tool (small)

Amebo has only `http_fetch` (known-URL text, 256KB, no search). Options, in order of
preference: (a) wire a search API (e.g. Brave/Anthropic web search via the API) as a
read-only tool in `cli_read_tools.py` style, `is_read_only=True`, FREE_ACTIONS; key in
instance config/env, never code; or (b) skip it and keep routing research to Claude Code
sessions, which have real WebSearch — the `lead-dossier` skill already documents this
split. Decide with Golda; (b) costs nothing.

## Spec 3 — Follow-up sweep as a claw (after Spec 0)

`docs/OPPORTUNITY_CLAW.md` and `docs/ORGS_GOALS_CLAW.md` are the precedent. Stand up a
claw (via `amebo-claw` / `/api/goals`) that runs the `follow-up-sweep` skill weekly
(Monday am) and posts the per-owner top-3 via `slack_post_gated`. The skill body is
already in the org repo — the claw just schedules it. Keep "one engine, two triggers":
no logic forks between the claw and someone @amebo-ing "run the sweep".

## Spec 4 — Conference follow-up engine (first live use: Badge Summit Jul 21–23)

From the June skill-ideas list (#8). Minimal version, no new tools needed after Spec 0:
capture (form or notes file) → within 48h: per-person `crm_create_contact`/link,
`crm_log_contacted`, `crm_schedule`, promised-artifact Taiga task, draft thank-you for
the human to send. Encode as an org skill (`skills/conference-followup.md`) reusing
`crm-scribe`; write it with the team, not for them — capture their actual follow-up
habits and words.

## Not to build (checked and rejected today)

- More prospect loaders / list builders — 1,220 untouched Identified leads already.
- A separate outreach tracker/app — CRM + Taiga + the sweep are the homes (BOUNDARIES).
- Autonomous sending of anything — gate stays; humans send; that's policy, not a gap.

## Where everything lives (for the next agent's first 10 minutes)

- Strategy synthesis: projects repo, `strategy/2026-July/07-06-26-landing-work-synthesis.md`
- Skills (org overlay, amebo loads via `load_skill`): `/opt/shared/projects/skills/`
  — lead-dossier, intro-request, crm-scribe, follow-up-sweep, grant-watch (+ prior
  start-campaign). Amebo core skills already include find-partner, ecosystem-research,
  demo-opener, sales-coach, product-gtm (`amebo/backend/prompts/skills/`).
- June GTM corpus: `/opt/shared/projects/strategy/2026-June/` (piles, targets, prompts).
- Pipeline reality check queries: `odoo-cli campaign-list`, `odoo-cli follow-up list`,
  `odoo-cli agenda all`, `mcp-taiga list gtm-ideas`, and the psql-via-.env recipe in
  Spec 0. Also stored in abra scope `claude` (search: `amebo-outreach`).
