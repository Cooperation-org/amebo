# Marketing & Communications Capability

> **Status: captured, not scheduled.** This records a design understanding we reached
> while thinking it through; nobody is building it right now. It is written down so the
> next contributor/agent inherits the reasoning instead of re-deriving it
> (per `BOUNDARIES.md` — "keep key understandings in a system of record").

## Why this exists

Outbound drip-with-templates emerged as a feature people will need (we prototyped the
*shape* of it as throwaway demos for a few verticals — home care, insurance, trades). But
it is **one element of a broader marketing & communications capability, not the whole
thing, and not mandatory**. The intent is to fold it into Amebo's skills for marketing and
communications — as part of a larger offering, or as a single element a team can optionally
switch on. This doc captures the element and the boundary decisions around it.

## The shape: communications is a skill area; drip is one element

Amebo already plans the primitives this rides on: `email_read` / `email_draft` /
`email_send` native tools (see `POWERS_PLAN.md`). A marketing/comms capability composes
those into higher-level skills:

- one-off and broadcast sends,
- content drafting and crystallizing (turn a rough ask into the right message),
- and **drip sequences** — the multi-step, time-delayed one. This is the element below.

Drip is optional and pluggable: a team that only wants drafting/broadcast never enrolls
anyone in a sequence.

## Key decision: drip lives in Amebo, untethered — not an Odoo plugin

**A drip campaign is a claw.** `BOUNDARIES.md` ("One engine, two triggers") already says a
claw is the same agentic loop with a scheduled/event trigger instead of a human one. A drip
is exactly that: schedule fires → think → act (send) → emit (log). Reply-handling is the
doc's "richest pattern" — a claw notices a reply and hands into the live loop.

Why Amebo and not an Odoo module:

- **Amebo legitimately owns the moving parts.** Enrollment, the step pointer, the next-due
  timestamp, and the pending-send queue are *transient operational state* — the same class
  as `goal_events` and "the draft/approval queue (pending outbound actions)" already listed
  under *Amebo OWNS* in `BOUNDARIES.md`. No new authoritative data is created.
- **It references, it does not duplicate.** The contact stays in **Odoo** (the row Amebo
  points at); identity resolves via **abra**. Each send is *crystallized* back into the
  contact's **Odoo chatter** (`CRYSTALLIZE.md`), so the CRM stays system-of-record for comms
  and `odoo-cli comms <name>` shows the drip like any other touch.
- **Background sends run under Amebo's team service identity**, stamped `amebo:<team>`
  (`CREDENTIAL_HELPER.md`) — the clean way to send for a team without impersonating a user.
- **Untethering is the payoff.** The same engine can sequence audiences that are *not* Odoo
  rows — abra-only people, web-sourced outreach prospects, any vertical. An Odoo module can
  only ever drip Odoo contacts. Given the team's mandate to do outreach beyond the CRM, that
  reach is the point.

## What must stay in a system of record (Amebo must NOT own these)

Applying the owns-vs-references discipline so this doesn't rot into a tangle:

- **Suppression / unsubscribe list** — durable + authoritative, therefore a system of
  record, **not** Amebo's transient state. Home it in Odoo's `mail.blacklist` or LinkedTrust;
  Amebo checks it before every send.
- **Templates** — versioned, customizable records/files Amebo renders. "Customizable" =
  edit the record. (An Odoo module would instead inherit Odoo's drag-drop designer for free —
  see trade-off below.)
- **Contacts** → Odoo. **Comms history** → Odoo chatter. **Identity** → abra.

## Dependencies / open questions before any build

1. **Outbound + deliverability** — a real SMTP/ESP path, plus SPF/DKIM/DMARC on the sending
   domain and warm-up. This is the bulk of real-world effort; the sequencing logic is the
   easy part. Same dependency regardless of plugin-vs-Amebo.
2. **Compliance** — CAN-SPAM / GDPR: `List-Unsubscribe` header, physical address, honored
   opt-out. Required for cold sequences to coordinators/leads.
3. **Template home + editor UX** — where they live and how a non-dev edits them.
4. **HITL granularity** — how much of a sequence is pre-approved vs. gated per send
   (`DRAFT_APPROVAL_GATE.md`).
5. **Reply handling** — the claw-notices-reply → live-loop hand-off and a stop condition.
6. **Enrollment state decay** — completed/stopped enrollments GC per their own policy
   (`STATE_DECAY_GC.md`); only the crystallized send survives, in Odoo.

## Current stack reality (so we don't re-research)

Our CRM is **Odoo 17 Community**: `mail.template` is native and customizable; `mass_mailing`
(Email Marketing) is free but not installed; `marketing_automation` (the visual drip builder)
is **Enterprise-only**, so unavailable. A *private* custom Odoo module would be allowed and
proprietary — it would not anger Odoo — but it couldn't reach non-Odoo audiences. Full
findings: `abra about odoo_crm_drip_readiness` (scope `claude`).

## When an Odoo plugin would be the better call instead

Recorded for fairness: if drip is *only ever* for Odoo contacts **and** marketers want to
build/tweak campaigns in Odoo's native designer with built-in open/click tracking, a private
`crm_drip` module (models `crm.drip.campaign` / `.step` / `.enrollment`, an `ir.cron` engine,
`base_automation` enroll triggers) is simpler and inherits compliance plumbing. The cost is
losing reach beyond the CRM and coupling to Odoo's upgrade cycle.

## Status

Not scheduled. Captured as an emergent strategic feature within the marketing/comms
capability area. Revisit when prioritized.
