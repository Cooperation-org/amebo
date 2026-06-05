# Email Poller Architecture (for review)

Status: proposal, not yet built. Reviewers please comment / edit.
Last updated 2026-06-05.

## Context

We want to file emails into the right place by sending or BCC'ing them to one
inbox (`amebo2019@gmail.com`). The main case: an email is sent **To: a client**
and **BCC'd to the CRM inbox**; it should land in that client's CRM record. Some
emails are instead about a project, a task, or should go to RAG storage.

Odoo cannot do this natively: its mail gateway keys off `From:` (which is us, the
sender) and only routes by reply-headers or by `mail.alias` on the recipient. It
will not match the `To:` client and log onto their record. So we build a small
poller. (HubSpot's BCC-to-CRM address did exactly this.)

## Hard rule: separation of concerns

Each part must work without the others:
- **Odoo CRM** is a system of record. It knows nothing about the poller or abra.
  We only write chatter / read contacts through `odoo-cli` (XML-RPC).
- **abra** is identity + (later) RAG storage. Standalone. Optional consumer.
- **amebo** owns the poller/router. It hard-depends on neither Odoo internals nor
  abra; it talks to them through interfaces.

## Components

### 1. Poller (in amebo)
Polls the one inbox, processes each new message exactly once, routes it.

### 2. Router — by plus-alias
Gmail delivers `amebo2019+TAG@gmail.com` to the same inbox; the `+TAG` is the
router hint (ours, not Odoo's `mail.alias`):
- `+crm@`  -> file chatter onto a contact   (build now)
- `+project@`, `+task@`, `+rag@`  -> stubbed
We are deliberately not using Odoo `mail.alias` (it cannot match `To:`), so this
is a separate layer, not a duplicate.

### 3. Resolver — pluggable, so amebo works without abra
```
Resolver.resolve(message) -> Match(partner_id, ...) | None
```
- `OdooResolver` (default, build now): `To:`/`Cc` address -> res.partner by email,
  directly via odoo-cli. No abra.
- `AbraResolver` (later): strict identity match in abra; returns partner_id plus
  cross-system ids (Taiga, Slack). abra plugs in here; amebo never requires it.

### 4. Writer — Odoo chatter
A new `odoo-cli log <partner> <subject> <body>` verb doing `message_post`
(message_type='email', subtype mail.mt_comment) onto the matched contact.

## Resolution order (first hit wins)
1. `In-Reply-To` / `References` -> existing thread (reliable for replies)
2. `To:` / `Cc` address -> contact (the main BCC case)
3. structured token in subject/body (fallback)
4. none -> **dead-letter queue** (never silently drop)

- Multiple matches: single-target rule for now; log the ambiguity.
- Zero matches: dead-letter.

## Poller state (in the amebo DB, not Odoo)
- seen `Message-ID`s (idempotency)
- dead-letter / unmatched log
amebo owns its bookkeeping; Odoo stays clean; abra untouched.

## Build now vs stub

**Now (MVP):** poll -> `+crm` -> `OdooResolver` To: match -> `odoo-cli log` to the
contact's chatter.

**Correctness, NOT stubbed (cheap and essential):**
- Idempotency: dedup on `Message-ID` before posting (re-polls must not double-post).
- Dead-letter queue for unmatched (no silent drops).
- Auto-reply / bounce skip: drop `Auto-Submitted`, `Precedence: bulk`,
  mailer-daemon, out-of-office.
- Mark processed (IMAP UID or our seen-set).

**Stubbed behind interfaces (later):**
- `AbraResolver` (strict identity) and RAG storage.
- `+project` / `+task` / `+rag` destinations.
- Attachments (MIME -> ir.attachment, inline/cid handling).
- `parent_id` threading onto an existing chatter message.
- Quoted-reply stripping (don't re-store the prior thread each reply).
- Author resolution policy for unknown senders (create vs skip).
- Follower management (`message_follower_ids`).
- Multi-recipient fan-out (currently single target).

## Correctness checklist (from review notes), mapped

| Item | Plan |
|------|------|
| Idempotency (Message-ID dedup) | NOW |
| Threading (In-Reply-To/References) | resolution step 1 NOW; parent_id linkage STUB |
| Resolution order + multi/zero match rules | NOW (defined above) |
| Unmatched dead-letter | NOW |
| Author resolution (From -> partner) | basic NOW; create-vs-skip policy STUB |
| Message metadata (type/subtype/model/res_id) | NOW |
| Attachments -> ir.attachment | STUB |
| Body HTML/plaintext + quoted-reply strip | basic store NOW; strip STUB |
| Auto-reply / bounce filtering | NOW |
| Multi-recipient fan-out | single-target NOW; fan-out STUB |
| Follower management | STUB |
| Plus-address vs mail.alias | using Gmail plus-addr as our router; not reusing mail.alias (cannot match To:) |

## Open questions for reviewers
1. abra as identity **registry** (we curate id mappings) vs **cache** (auto-synced
   from Odoo/Taiga/Slack)? Affects how `AbraResolver` is built.
2. Unknown `To:` (not a contact yet): auto-create the contact and log, or
   dead-letter for review?
3. Where should the poller run: its own process/systemd unit, or inside an
   existing amebo service? (Leaning own process, keeps it off the live web app.)
4. One inbox for everything via `+tags`, or separate inboxes per destination?

---

## Review (view session, 2026-06-05)

Critical review at Golda's request. Reviewed against the abra
`security-design.md` working draft (sibling abra repo) so the
threat model is consistent across both surfaces.

### HIGH severity

1. **Forgeable `To:` is a third-party CRM write attack.** Anyone on
   the internet can send to `amebo2019+crm@gmail.com` with any `To:`
   value. The poller matches `To:` → `res.partner` and posts to that
   contact's chatter. No check that the email actually came from the
   team. So an attacker sends `To: client@…`, `Bcc: amebo2019+crm@…`,
   and the attacker's content lands in CRM under that client's
   record, with downstream notifications to `mail.followers`.
   **Fix:** dead-letter (or hard-drop) anything whose `From:` /
   `Sender:` doesn't resolve to an allowlisted team identity (or
   DKIM-validated team domain). Add as step 0 of the resolution
   order, before any routing.

2. **Plus-alias gives spoofers full router control.** Once `+crm` /
   `+project` / `+task` ship, they're public knowledge. Anyone
   hitting `amebo2019+task@…` triggers the task router. Hardening
   the sender check in (1) closes this.

3. **Credential management and OAuth aren't mentioned.** The poller
   authenticates to Gmail (IMAP) somehow — app password? OAuth2
   refresh token? Where does the secret live, who rotates, what
   happens on revocation? Doc is silent. Same OAuth-required
   principle as the rest of the team. For inbound polling, OAuth2
   with a service-account-style refresh token, encrypted at rest,
   rotation documented.

4. **Author resolution NOW is "basic" but undefined.** §From →
   partner: basic NOW; create-vs-skip policy STUB. If basic means
   auto-create, an attacker can pollute the contact DB with phantom
   records or hijack identity attribution. Lock NOW to
   "skip-if-not-found"; auto-create only when the create-vs-skip
   policy lands.

### MEDIUM severity

5. **Idempotency seen-set unbounded.** Storing every `Message-ID`
   forever lets a sender DOS the dedup table with unique IDs. Bound
   by TTL (30 days?) or hash-only with size cap; document the
   policy.

6. **Multi-recipient silent single-target.** §"single-target rule
   for now; log the ambiguity" — but if no human reviews the log,
   senders won't know that emails addressed to N clients filed
   under one. Surface skipped recipients explicitly, ideally as a
   follow-up task or a dead-letter row.

7. **Dead-letter queue with no review workflow == silent drop.**
   Doc calls it "never silently drop" but doesn't define the review
   surface (CLI? web UI? Slack ping?) or cadence. Without that, it
   is silent drop with a different name.

8. **PII / retention not addressed.** Emails carry PII. No mention
   of retention windows, encryption at rest, deletion-on-request.
   Out of scope for MVP but flag as a "deferred" item with a
   target.

### LOW severity

9. **Threading via `In-Reply-To` could leak across organizations**
   if two senders happen to reuse a Message-ID (rare but specified).
   Confirm the resolver doesn't follow stale IDs into the wrong
   customer's thread.

10. **`odoo-cli log` is a new verb** and the doc treats it as a
    given. Cross-link to the odoo-cli repo PR; document version-skew
    handling.

11. **Plus-addressing locks you to Gmail.** Migration to any other
    provider (Workspace switch, self-hosted IMAP) breaks routing.
    Acceptable for v1, note as future migration cost.

12. **Open questions miss the security ones.** Add to "Open
    questions for reviewers" above: (a) sender authentication
    mechanism; (b) credential storage and rotation; (c) explicit
    threat model — what attacker are we defending against?

### Strong points worth keeping

- Resolution order is well-thought (reply headers → `To:` → token →
  dead-letter).
- Hard rule separation between Odoo, abra, amebo is sound.
- `AbraResolver` stubbed behind an interface keeps amebo standalone.
- Build-now vs stub split is honest about scope.

### Cross-reference

These HIGH findings overlap with abra's auth model in
`abra/security-design.md`. Forgeable `To:` is the same shape as
abra's "unauthenticated cross-scope write." OAuth credential
management is the same gap as abra's "real identity at the entry
point." Solving once across both surfaces is cheaper than twice.
