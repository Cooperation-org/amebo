# Amebo — Overview

A one-page introduction. For detail, see `ARCHITECTURE.md`,
`ORGS_GOALS_CLAW.md`, `POWERS_PLAN.md`, `CHANNEL_CONTRACT.md`,
`ABRA_INTEGRATION.md`, `SELF_FRIENDS_HOME.md`, and
`HERMES_PATTERNS_AND_GAPS.md`.

---

## What amebo is

Amebo is the agent layer. It receives events, decides what they mean,
takes action, and emits events. It is the loop.

Amebo *acts as if* it is a friend — helpful, attentive, low-friction,
in conversation. It is not actually a friend; it is a bot. A person
also has real human friends who might be surfacing things in the same
view. Amebo sits alongside them, not above them.

## The contract

Amebo acts *for* a person or *for* an organization, in conversation,
with explicit consent. It is one helper among several the user can
call on. It does not own the user's attention, identity, or mandate.

## What amebo has

- A **loop** — receive event → think → decide → act → emit event
- **Conversation/processing threads** — working memory during a task
- **Tool access and credentials**, per person and per org (OAuth,
  API keys, encrypted at rest)
- An **event log** of what it did
- **Skills** — composable behaviors loaded as needed
- Connections to **abra** (to know who it helps) and to
  **LinkedTrust** (to decide who to trust)

## What amebo doesn't hold

- The person's identity
- The person's map of what matters
- The person's history of what they cared about over time

Those belong to abra. Amebo's own state is transient. Conversation
threads decay; events GC out unless they are consolidated into abra
by the emotion signal (what the person, or amebo's own judgement,
marks as important).

## Decoupled from abra

Amebo works without abra — it just becomes less personal. With abra,
it knows who it is helping and can write back what it learns. Without
abra, it still runs loops and takes actions using its skills and
tools. The two systems are independent and intended to compose, not
required to.

## The unified-feed value

One thing amebo can do well, especially with abra present, is bring
together signals from many channels the user already lives in —
Slack, email, Discord, SMS, webhooks — and surface them as one stream
or one notification feed. The user can still use each channel
directly. Amebo just gives them an optional unified surface.

This is one example of why amebo exists: not to replace the channels
or tools the user already has, but to do the work of *bringing them
together* and *acting on them* when the user wants help.

---

## How amebo connects to the other two systems

- **Abra (the map of what's important).** Amebo reads abra to know
  who the person is and what they care about. When something matters
  enough during processing, amebo writes back to abra so the durable
  map updates. The view (canvas) lives in abra; amebo contributes
  *overlays* to that view — "in progress", "needs your attention",
  "amebo did this for you".
- **LinkedTrust (the trust endpoint).** Amebo queries LinkedTrust
  before acting on things that need trust judgement — should I act on
  this email, trust this contact, rely on this source. LinkedTrust
  scores; amebo decides.

The three systems are independent. Amebo can be replaced with a
different claw and abra keeps the map. Abra can be replaced and amebo
keeps acting. LinkedTrust can be swapped for a different trust
endpoint without touching either.

For the full picture, see the abra overview and the LinkedClaims
overview in their respective repos.

---

## Detail docs

- `ARCHITECTURE.md` — system architecture, multi-tenant model
- `ORGS_GOALS_CLAW.md` — orgs, goals, the claw layer
- `POWERS_PLAN.md` — tool inventory, MCP integration, credential management
- `CHANNEL_CONTRACT.md` — channel adapter design (Slack, web, future channels)
- `ABRA_INTEGRATION.md` — how amebo uses abra
- `SELF_FRIENDS_HOME.md` — framing: abra as self, amebo as friend, canvas as home
- `HERMES_PATTERNS_AND_GAPS.md` — comparison to NousResearch/hermes-agent
