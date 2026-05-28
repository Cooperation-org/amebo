# Amebo

A friendly claw.

Amebo is the agent — it takes actions on behalf of a person or an organization. It runs a loop: receive event, decide, act, emit event.

Amebo *acts as if* it is a friend. It is a bot, not a friend. A person also has real human friends who may be surfacing things in the same view. Amebo sits alongside, not above.

Amebo holds nothing about who the person is. That belongs to abra. Amebo's own state — conversation threads, event log — is transient. Important events get consolidated into abra; the rest decays.

Amebo works without abra. With abra, it knows who it helps.

One thing amebo does well: bring signals from many channels (Slack, email, Discord, SMS, webhooks) into one optional feed.

---

**Detail**
- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`ORGS_GOALS_CLAW.md`](ORGS_GOALS_CLAW.md)
- [`POWERS_PLAN.md`](POWERS_PLAN.md)
- [`CHANNEL_CONTRACT.md`](CHANNEL_CONTRACT.md)
- [`SELF_FRIENDS_HOME.md`](SELF_FRIENDS_HOME.md)
- [`HERMES_PATTERNS_AND_GAPS.md`](HERMES_PATTERNS_AND_GAPS.md)

**Related systems** (own repos)
- [abra](https://github.com/Cooperation-org/abra) — the person's map that amebo reads and writes
- [LinkedClaims](https://github.com/Cooperation-org/LinkedClaims) — the trust layer amebo queries
