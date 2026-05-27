# Self, Friends, Home

A framing for the whole system shape. Independent of any specific tool
or framework choice (Hermes, OpenClaw, etc.). The point is to name what
each component *is* before deciding how it's built.

Most of the **self** framing here is not new — it has been the abra
design since 2001, restated in `abra/about.md` and `abra/concept-notes.md`.
This doc connects abra's framing to the rest of the system (claws, home
dashboard, channels).

---

## The three categories

### Abra is the self

Abra is *a brain extension*. From its own concept notes:

- **Names are magic. To name something is to have power over it.**
- **Pet names** are personalized, distorted mappings into info-space —
  they magnify and focus the points and relationships *I* care about.
- **Hot tags** carry weight in proportion to current importance.
  Pinning is described as "emotional markers for permanence". Abra is
  not just what I *know* — it's what I care about, think about, feel
  about. It is a map of the self.
- **Composable like LOGO** — names use each other, can be verbs.
- **Data durable, implementations swap.** "Like a triple-store, but
  light, clean — message-in-a-bottle."
- **Scoped to people OR groups.** Abra already has both: a `golda`
  scope (personal) and a `linkedtrust` scope (team). Same shape, same
  query surface, different *whose-attention* the map belongs to.

This is the seat of personhood for the system. Not a database, not a
tool. *You*. Or *the team*. Whichever scope you've named.

### Friends are other selves you can ask for help

Friends have their own expertise, their own memory, their own
boundaries. They summarize for the self instead of dumping their
internals. Examples:

- **Amebo** is a friend — a friendly claw that can act on behalf of an
  org. (Multi-tenant org infrastructure, OAuth credentials per org,
  audit per org. Its own internals at `ARCHITECTURE.md` etc.)
- **The calendar** is a friend. **LinkedClaims** is a friend. A
  delegate-spawned specialist is, briefly, a friend.
- A friend interaction looks like *asking* and *being told back* — not
  like calling a function. The audit trail is a conversation, not a
  stack trace.

### The home is abra's canvas view

**This is an extension of abra, not a new component.** Abra already
has the data — names, hot tags, bindings, scopes. We are adding a
*canvas view* on top: a visual surface that arranges abra content the
way the user wants to see it.

The "hot tags dashboard" is already named in abra's own concept-notes:

> *"enables powerful new instruments like a 'hot tags' dashboard where
> every part of the screen relates to something in my head, in
> proportion to its current importance. can rotate aspects. So I can
> essentially load my team context and every part of the screen
> reflects things important to the team that are already in my brain
> or I need to know."*

The canvas is the *face* the self presents to itself. **A map of the
self, however the user wants to configure it.** Arranged like a room —
or like many rooms, since most active users live in several at once.

For some users it might look like **Pinterest** — a visual board of
pins, each pin being something hot, drag to rearrange, group by theme.
For others it's a calendar grid, a journal of recent claw actions, a
map, a spreadsheet of "what's hot this week", or just the morning email
digest. Same abra data; different surface per person.

**Single-view for some, multi-threaded for others — the canvas spans
the spectrum.** Some users want one calm view: today's hot tags, a
journal column, done. Others run many parallel workstreams (an MTC
aspect, a bare-metal aspect, an RTV aspect, a family aspect) and need
several aspects visible at once — tabs, side-by-side boards, swappable
contexts. Pinterest's "boards" are roughly the right shape for the
multi-aspect end; a single morning summary email is roughly right for
the simple end. The canvas needs to support both ends and the middle.

**The canvas is AI-customizable verbally.** "Show me my MTC stuff
bigger." "Make a new aspect for the bare-metal article and pull in
everything tagged Rackdog and Peter." "Hide everything from before
March." The user shapes their view through conversation — like
arranging a room, but a room they can re-arrange by speaking.

Some users may never open the canvas at all. For them "home" is the
ambient surface — the daily email, the Telegram pin, the wall display.
The data layer is the same abra; only the rendering changes.

---

## Component map

```
   ┌─────────────────────────────────────────┐
   │  Abra (the Self)                        │
   │  - names, pet names, hot tags           │
   │  - bindings, relationships              │
   │  - what I care / think / feel about     │
   │  - scoped per-person OR per-team        │
   │                                         │
   │  + canvas view  ← new extension         │
   │    Pinterest-like for some,             │
   │    grid / journal / map / digest        │
   │    for others. AI-arranged verbally.    │
   └─────────────────────────────────────────┘
                      │
                      │  asks friends
                      ▼
   ┌──────┬──────────┬─────────┬──────────┬──────────┐
   │amebo │ taiga    │ odoo    │ calendar │ linked-  │  ...
   │(claw)│ (tasks)  │ (CRM)   │          │ claims   │
   └──────┴──────────┴─────────┴──────────┴──────────┘
       friends, each encapsulated. Each summarizes
       for the self instead of dumping internals.
```

- **Abra (the Self) + canvas** — abra repo already exists. The canvas
  is a *new view* on it, not a new component. Could start as a single
  SvelteKit page reading abra's API with hard-coded widgets, then grow
  voice-rearrangement. The data layer doesn't change.
- **Amebo (a friend)** — multi-tenant claw. Stops trying to be the
  center. Exposes a clean API. Borrows useful patterns from agent
  frameworks (see `HERMES_PATTERNS_AND_GAPS.md`) *as a friend*, not as
  the whole system.
- **Other friends** — each their own integration. Most already exist
  (taiga via mcp-taiga, odoo via odoo-cli). New ones (calendar, email,
  LinkedClaims) added as needed.

---

## What falls out of this framing

- The agentic loop is "the self deciding which friend to ask next".
  Same shape as tool-use, friendlier language for nontechnical users.
- The delegate pattern is "asking a specialist friend". They go away,
  do work, summarize. Your context stays clean.
- LinkedClaims fits naturally: friends vouch for friends. The audit
  trail *is* a graph of asks and answers.
- The dashboard does **not** live inside amebo. Amebo is multi-tenant
  org infrastructure; the dashboard is intimate and personal. Different
  mental categories, different repos.
- For teams: the **team's abra scope** is the team's collective self.
  A team home shows what's hot for the team. Same mechanism as personal
  home, different scope. This already works in abra today via the
  scope mechanism.
- Naming for user copy should follow the framing: "tool registry" →
  "friends"; "delegate" → "ask <friend>"; "audit log" → "what I asked,
  what was said back, what I did".

---

## What this implies for abra

Abra's role is elevated here, not changed. A few priorities follow:

- **Query API completeness.** The home and every friend reason against
  abra. The surface must be rich enough — and stable enough — to
  support both. `abra-lib` extraction is the start; the API needs to be
  designed for consumers beyond amebo.
- **Identity portability.** If abra is "you" (or "your team"), it
  should be portable. Backups, exports, eventually a self-sovereign
  storage model. This connects to LinkedClaims and ATProto, which
  already model the self as portable. *Message-in-a-bottle*, per
  abra's own concept-notes.
- **Friend-of-mine bindings.** Today abra has typed relationships
  between people and projects. It should also model "amebo is a friend
  who can do X for me" — a binding the home reads to know which friends
  are available and what they're good for.

---

## What this implies for amebo

Amebo's existing instinct that "Org is the core grouping noun" stays
right — *for amebo*. Amebo is a friend who acts for an org. The *self*
that calls on amebo is a person (or a team) with their own abra.

This means amebo doesn't need to grow personal-dashboard features. It
needs to keep its API clean enough that a member's home (or their team's
home) can ask it "what did the claw do for org X this week" and get a
useful summary back.

---

## Out of scope for this doc

- The specific build of the dashboard (widget framework, voice
  arranging UX, theming).
- The specific build of new friends (email-friend, calendar-friend,
  etc.). They'll each get their own integration choice.
- Amebo's internals — see `ARCHITECTURE.md`, `ORGS_GOALS_CLAW.md`,
  `POWERS_PLAN.md`, `HERMES_PATTERNS_AND_GAPS.md`.
- Abra's internals — see `abra/about.md`, `abra/concept-notes.md`,
  `abra/binding-format-v0.1.md`.

This doc only names *what each piece is*. The how is downstream.
