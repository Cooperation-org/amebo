# Amebo Use Cases — the runner's north star

*What "working" means, as concrete end-to-end scenarios amebo (the runner) can evaluate its own work against and drive toward. Each has an evaluable **Done when** — write it as an e2e test and make it pass. Grounded in the real team context (LinkedTrust / What's Cookin', Raise the Voices, CivicWorks) and amebo's actual tools (Slack, Taiga, Odoo CRM, project repos, abra). Companion to the architecture (`/opt/shared/projects/plans/amebo/7-4-2026-amebo-architecture.md`) and the WP plan.*

**How the runner uses this:** pick a use case, run it end-to-end against the real system, observe whether the **Done when** holds. If it doesn't, that gap is the next work. A use case is only "green" when a human (or an e2e test) has seen it happen for real — not when a unit test passes. (We learned this the hard way: a mocked test was green while the live path crashed.)

Status legend: ✅ works end-to-end (verified) · 🟡 partial / wired but not exercised live · ⬜ not yet.

---

## UC-1 — File an idea/skill under a specific org, from anywhere
**Story:** Golda is a member of several orgs. In *any* channel, she says: *"amebo, file this as a skill under raise the voices: when a big company asks about our co-op model, answer with the 3-tier structure first."* It lands in **RTV's** space, in her words, and is available whenever amebo acts for RTV — even though she said it in a different org's channel.
**Done when:** the utterance resolves to org=RTV (not the channel's default org), the content is stored in RTV's scope **verbatim** (plus a clearly separated one-line summary), and a later "amebo, what's our skill for corporate questions?" while acting for RTV returns it. Cross-org routing + verbatim preservation both hold.
**Exercises:** WP2 resolution (explicit targeting), WP9 skills. **Status:** 🟡 (resolution ✅ WP2; skill filing ⬜ WP9).

## UC-2 — Amebo pings a person in Slack, gated
**Story:** A goal reaches a point where a human needs to act. Amebo sends that person a Slack DM naming the specific next step and a link — short, like a colleague, not a report.
**Done when:** amebo composes the message, it passes the draft-approval gate, and on approval a real Slack message arrives at the right person (by their Slack id, resolved via `member_tool_accounts`, never guessed from content). At tier T0 (unknown sender) the same request is refused below the model.
**Exercises:** trust gate (§4.3), outbound (WP13), attribution. **Status:** ✅ (verified live — amebo DM'd Golda through the gate; `member_tool_accounts` mention-resolution is WP13 🟡).

## UC-3 — A task from a Slack conversation, with a deadline
**Story:** In a thread, someone says "we should follow up with Acme about the pilot by Friday." @amebo drafts a Taiga task (subject, description with context, due date, assignee) — it does **not** create it silently; a human approves, then it's created as amebo.
**Done when:** the draft is held (nothing created), and on approval a Taiga story exists on the right board with the due date, owned by amebo. A missing deadline makes amebo ask rather than create a dateless task.
**Exercises:** gated Taiga writes (WP6), OrgContext routing (WP2/WP5-8). **Status:** ✅ create verified live earlier; update/comment/close ✅ WP6 (gate-tested; live-exercise pending).

## UC-4 — Embed a read-only amebo in a tool, safely
**Story:** A public-facing page (or the Changemaker app) embeds an amebo chat. An unknown visitor asks about the org and gets a helpful answer — but the embed can **never** execute anything or read private team knowledge.
**Done when:** an unauthenticated `POST /api/chat/public` (for an opted-in instance) answers from approved knowledge with **zero tools offered**; a not-opted-in instance 404s; the answer never contains private RAG/abra/Slack content; and any write is refused two independent ways (no tool offered + T0 gate).
**Exercises:** public endpoint + hardening, trust gate. **Status:** ✅ (verified live — answers with `tools=[]`; opt-in + isolation + no-leak in place).

## UC-5 — A week-long goal that iterates instead of restarting
**Story:** Monday: "amebo, this week's goal for RTV: line up 3 co-op partners to try the demo." Amebo works it across the week — each dispatch remembers what it already tried, checks what changed, and moves forward; it doesn't repeat Monday's work on Wednesday.
**Done when:** dispatch N is briefed with progress from dispatches 1..N-1 (recent verbatim, older compressed), **re-verifies** current state against the live tools before acting (a task it drafted may already be done), and writes a closing summary. Two dispatches demonstrably build on each other.
**Exercises:** goal carryover (WP11), completion-condition eval (WP19). **Status:** 🟡 (carryover + dispatch_summary ✅ WP11; the re-verify discipline is prompt-enforced — exercise it live).

## UC-6 — Ask a human and wait, then resume
**Story:** Mid-goal, amebo hits a decision only a human can make. It posts one short question to the person/channel, **pauses** the goal, and when they reply, resumes with the answer folded in — no busy-polling, no re-asking.
**Done when:** the goal goes `waiting_user`, the scheduler skips it, a reply on that thread flips it to `pending`, and the next dispatch's carryover contains the answer. A configurable timeout wakes it with "no answer" recorded.
**Exercises:** ask_user (WP12). **Status:** ⬜ WP12.

## UC-7 — Weekly pipeline-hygiene nudge
**Story:** Every Monday amebo looks at the CRM, finds deals with no next step or gone stale, and posts one concise, clickable digest to the team channel — through the gate — so the team can fix hygiene without amebo nagging per-deal.
**Done when:** the digest lists the real hygiene buckets with deep-links that open the specific Odoo record, is deduped per day, and only posts after approval; inert if no notify channel is set.
**Exercises:** pipeline_status_claw, CRM read routing (WP5), outbound gate. **Status:** ✅ (shipped + piloted live; now routes CRM per-org via WP5).

## UC-8 — Two orgs, one Slack app, actions land in the right org
**Story:** One amebo instance serves both RTV and CivicWorks in the same Slack workspace. A message in the RTV channel creates an RTV task; a message in the CivicWorks channel creates a CivicWorks task — using each org's own Taiga/CRM credentials, never crossed.
**Done when:** the incoming event resolves to the correct org (venue default → membership → explicit targeting), and the tool call uses that org's connection (its Taiga URL/token), verified by two orgs hitting different endpoints.
**Exercises:** WP2 resolution, WP3 connections, WP4 Slack multi-app, WP5-8 routing. **Status:** 🟡 (resolution + per-org connection routing ✅; the Slack multi-socket/per-org-token runtime is ⬜ WP4).

## UC-9 — Onboard a new org with zero code
**Story:** A new org shows up. An admin runs one provisioning command: point/create its context repo + `org.yaml`, store its secrets, attach it to an instance, add members. Amebo now serves it — its CRM, tasks, repo, knowledge — with **no code change**.
**Done when:** RTV and CivicWorks are both provisioned via the CLI (Golda supplying real creds), and amebo answers/acts for them correctly, with zero edits to amebo source. This is the acceptance test that the tenancy layer is truly generic.
**Exercises:** WP17 provisioning + cutover. **Status:** ⬜ WP17 (schema + connection layers ✅ underneath).

## UC-10 — Correct amebo once, it stays corrected
**Story:** Amebo gets something wrong; a human corrects it in conversation ("no — for RTV we lead with values, not price"). That correction becomes durable in the org's space, and amebo's later behavior reflects it.
**Done when:** the correction is captured verbatim to the org's space (`capture_feedback`), distilled standing guidance lives in the org's context repo `guidance.md`, and that guidance is loaded into the system prompt when amebo next acts for that org — so the mistake isn't repeated.
**Exercises:** continuous-improvement (arch §7). **Status:** ⬜.

## UC-11 — Update a project's MAIN.md from what actually happened
**Story:** A project's MAIN.md is stale. Amebo reads recent activity, proposes a precise edit (team lead, next milestone, links), and — gated — updates the file in the org's project repo, committed with attribution.
**Done when:** the edit targets the acting org's projects root (not a hardcoded path), the path-traversal guard holds relative to that root, and the change is a reviewable diff, not a rewrite.
**Exercises:** WP7 projects routing, main_md tools. **Status:** ✅ per-org root routing (WP7); the gated-commit-with-attribution step is the remaining polish.

## UC-12 — Friday recap
**Story:** Friday, amebo posts one digest of the week's active goals for the org: what moved, what's blocked, what needs a human — one message, through the gate.
**Done when:** the recap is built from the goals' `goal_events` (not re-derived), names blockers and asks, and posts once through the output gate on the org's configured day.
**Exercises:** weekly cadence (WP14), goal carryover (WP11). **Status:** ⬜ WP14 (carryover ✅ underneath).

---

## Driving order (highest north-star value first)
1. **UC-1** (file-under-X) — the flagship story; needs WP9. Do next.
2. **UC-6 / UC-12 / UC-5** — make goals feel like a colleague (WP12, WP14) on the WP11 base.
3. **UC-8 / UC-9** — real multi-org (WP4 Slack runtime, WP17 provisioning) — turns the plumbing into a live second org.
4. **UC-10** — the Hermes lesson (continuous improvement).

Everything else is ✅ or 🟡 and mostly needs a live exercise to confirm, not new code.
