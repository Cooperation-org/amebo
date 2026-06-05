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
