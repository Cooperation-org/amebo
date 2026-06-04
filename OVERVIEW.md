# Amebo

A friendly claw.

Amebo is the agent. It takes actions on behalf of a person or an organization. It runs a loop: receive event, decide, act, emit event.

```
                    event in
                       │
                       ▼
              ┌─────────────────┐
              │  AMEBO          │  ── reads / writes ──→  ABRA
              │  receive →      │     (the person's map)
              │  think →        │
              │  act →          │  ── queries ────────→  LinkedTrust
              │  emit           │     (trust scores)
              └─────────────────┘
                       │            ── calls ──────────→  external tools
                       ▼                                   (Slack, email,
                   event out                               Taiga, GitHub,
                                                           Discord, SMS, ...)
```

Amebo *acts as if* it is a friend. It is a bot, not a friend. A person also has real human friends who may be surfacing things in the same view. Amebo sits alongside, not above.

Amebo holds nothing about who the person is. That belongs to abra. Amebo's own state — conversation threads, event log — is transient. Important events get consolidated into abra; the rest decays.

Amebo works without abra. With abra, it knows who it helps.

One thing amebo does well: bring signals from many channels (Slack, email, Discord, SMS, webhooks) into one optional unified feed.

Amebo is a funnel. A lot comes in. The core engine function is **crystallizing**: distilling that input down to the smallest output that still carries the meaning the receiver needs, in the receiver's voice and at the receiver's bandwidth. For a human, that is one or two lines on a cold ping, more only when the receiver is already engaged. The crystallize step matters more than any single channel adapter. See [`docs/CRYSTALLIZE.md`](docs/CRYSTALLIZE.md).

---

**Detail**
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/CRYSTALLIZE.md`](docs/CRYSTALLIZE.md)
- [`docs/ORGS_GOALS_CLAW.md`](docs/ORGS_GOALS_CLAW.md)
- [`docs/POWERS_PLAN.md`](docs/POWERS_PLAN.md)
- [`docs/CHANNEL_CONTRACT.md`](docs/CHANNEL_CONTRACT.md)
- [`docs/SELF_FRIENDS_HOME.md`](docs/SELF_FRIENDS_HOME.md)
- [`docs/HERMES_PATTERNS_AND_GAPS.md`](docs/HERMES_PATTERNS_AND_GAPS.md)

**Related systems** (own repos)
- [abra](https://github.com/Cooperation-org/abra) — the person's map that amebo reads and writes
- [LinkedClaims](https://github.com/Cooperation-org/LinkedClaims) — the trust layer amebo queries
