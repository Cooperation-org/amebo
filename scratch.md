# scratch — cross-session coordination

## 2026-06-05 — REVIEW REQUESTED: email→CRM poller

Design doc: **`docs/email-poller-architecture.md`** — please review/comment before code.

Summary: send/BCC email to one inbox (amebo2019@gmail.com); poller files it.
Separation of concerns is the hard rule — amebo polls, Odoo + abra each work
independently, resolver is pluggable (`OdooResolver` default = To: → contact;
`AbraResolver` later). Plus-alias routing (+crm/+project/+task/+rag), resolution
order (reply-headers → To:/Cc → body token → dead-letter), idempotency on
Message-ID. MVP = `+crm` → To: match → `odoo-cli log` to chatter; rest stubbed.
Open questions for reviewers at the bottom of the doc.

(Older coding-orchestration status: see `june-1-2026-scratch.md`.)
