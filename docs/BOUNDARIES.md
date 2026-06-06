# Amebo: Boundaries and the System-of-Record Discipline

> Canonical design guidance for Amebo. If you are about to add state, a table, or a
> "let me just remember this" to Amebo, read the table first. The default answer is:
> it lives somewhere else, and Amebo points at it.

## What Amebo owns vs. what it references

Amebo is the **agency layer**, not a storage layer. It owns only the transient state it
needs to perceive, decide, and act right now. Everything durable and authoritative lives
in a system of record that Amebo references but does not own.

| Amebo OWNS (transient, operational) | Lives elsewhere; Amebo only references (durable, authoritative) |
|---|---|
| The inbound funnel and channel adapters (Slack, email, web, CLI, voice) | Who a person or org *is* → **Abra** |
| The agentic loop (receive → think → act → emit) | Name-bindings / mind-map → **Abra** |
| **Crystallizing**: distilling input to the smallest output that carries the meaning | Contacts → **CRM (Odoo)** |
| In-flight conversation / thread state (decays; 24h GC) | Tasks, deadlines, status → **Taiga** |
| In-flight goal-state and audit (`goal_events`) | Long-form initiatives / goal narratives → **projects git repo (markdown)** |
| Tool invocation and per-instance permission enforcement (`allowed_tools`) | Trust, attestations, access → **LinkedTrust** |
| The draft / approval queue (pending outbound actions) | Semantic index → **pgvector via Abra** (rebuildable, never authoritative) |
| | Coding → **Claude Code** invoked as a subagent in a bounded worktree |

## Amebo is the actor, never the database

Amebo's identity is "the actor." It perceives, decides, and acts on someone's behalf. It is
not a place where truth lives. The moment Amebo starts being the canonical home for a fact
that another system should own, the separation has rotted and the system is on its way to a
tangle. If you find yourself reaching for a new Amebo table to hold something durable, stop:
that thing has a home, and Amebo's job is to reference it.

## The human-assistant test

The rule for deciding what belongs in Amebo, stated the way the principle actually reads
(Amebo uses things the way a person would):

> Would a great human assistant keep this in their head, or look it up in the shared system?
>
> - **In their head** (the thread they are in right now, what they are working on this minute) → **Amebo**.
> - **Look it up / write it down for everyone** (who someone is, the canonical task list, the goal doc) → **system of record**; Amebo just points at it.

## One engine, two triggers

Claws are not a second system. Live, people-guided interaction is the foundation; a claw is
the same engine with a different trigger. There is one loop (receive → think → act → emit),
and it runs identically whether a human or a schedule started the turn.

| | Trigger | Output sink |
|---|---|---|
| **Live** | a human (Slack, web, CLI, voice) | back to the human, in their voice and bandwidth |
| **Claw** | a schedule or an event | a notify channel plus the audit log |

The richest pattern blurs the line: a claw notices something (proactive trigger), then opens
a live conversation and hands into the same loop. So "live vs. claw" is really *who started
this turn*, not two architectures.

**Invariant: the two modes must never fork.** Same brain, same tools, same per-instance
permissions, same context management, regardless of trigger. Only the trigger and the output
sink may differ. If live-mode and claw-mode ever diverge into separate code with different
tool access or different memory rules, the tangle has begun. Protecting this unification is
the architectural rule, not an implementation detail.

## Minimal state, judgment-based retention, per-system garbage collection

Amebo holds as little state as it can. Its own working state decays fairly quickly unless
Amebo judges there is a reason to keep something; that judgment is part of its job. Anything
worth keeping is crystallized out to a system of record and the rest is allowed to decay
(important events consolidate into Abra; the rest GCs at 24h).

Garbage collection is not a single mechanism. Each system of record runs its own GC,
appropriate to that system, including Amebo's own Abra scope, which is working memory and not
a permanent mind-map. Amebo's Abra scope therefore needs its own decay policy; it is not the
same as the human `golda` scope, which is durable and human-authored. Do not assume one GC
policy fits every store.

## Permissions: Amebo acts as the principal, never on its own authority

Amebo has no ambient authority of its own. Every action it takes is taken *as* a principal:
the person it is helping live, or the org a claw runs for. Its permission to reach a
downstream system (CRM, Taiga, LinkedTrust, Abra) is exactly that principal's permission,
never more. If the principal cannot do it, Amebo cannot do it on their behalf.

Credentials (JWT, OAuth access/refresh tokens, API keys) are held behind an **encapsulated
token helper, keyed by principal**. The rest of Amebo never sees raw secrets; it asks the
helper "give me principal X's token for system Y" and gets back a scoped token or nothing.
Permission resolution is therefore: identify who this turn is for, then retrieve that
principal's tokens. Depending on who we are talking to, we retrieve the appropriate
permissions.

Rules this enforces:

- **No god-token.** Amebo never holds a single super-credential that bypasses per-principal
  scope. There is no "Amebo can do anything" path.
- **Encapsulation.** Token storage is hidden behind the helper so it can evolve (env var →
  vault → KMS → SSO broker) without touching any call site. Call sites ask for a capability,
  not a secret.
- **Per-principal, per-system.** The helper returns the token for a specific (principal,
  system) pair. One principal's tokens are never visible to another principal's turn. This
  is the mechanism behind the multi-tenant isolation the spin-off startups will need.
- **Stamp the actor.** Every write Amebo performs carries the acting principal's identity
  (author URI / session stamp), so the audit trail and any system-of-record write records
  who it was really done as.

This composes with the coarse per-instance `allowed_tools` gate (which tools exist at all for
an instance) and the finer token-scoped permission (what those tools may actually do as this
principal). Both apply.

> Coordination note: the SSO / OAuth implementation that issues these tokens across
> LinkedTrust, Amebo, Taiga, and the CRM is being built separately. This section records the
> boundary principle the token helper must satisfy; it is not the implementation.

## Keep key understandings in a system of record

This document is itself an instance of the principle. The understanding it records does not
live in any one session's memory or in any one person's head; it lives here, in the repo,
where the next contributor and the next agent can find it. When a design understanding is
reached, write it down in the right system of record. That is how the vision survives many
hands without drifting.
