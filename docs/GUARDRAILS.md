# Task Guardrails

Every task in marten (marten.linkedtrust.us) that touches amebo, abra, or LinkedTrust
links to this doc. If you (human or AI) picked up a task and haven't read this, stop here first.

## Paste-able block for every task

Copy this into the description of each task you create:

> **GUARDRAILS — read before coding.** This task is part of a larger system with strict
> boundaries. Before writing any code: (1) read `/opt/shared/repos/amebo/docs/GUARDRAILS.md`
> and `/opt/shared/repos/amebo/docs/BOUNDARIES.md`; (2) read the OVERVIEW.md and CLAUDE.md
> of the repo you're working in. Each fact has ONE home — amebo is the actor, never the
> database; the map lives in abra; tasks in Taiga; contacts in the CRM; trust in LinkedTrust.
> No hacks, no "for now" stand-ins, no hardcoded values, no new tables or services without
> asking. Work on a branch, small diffs, PR — never push to main. If anything fails or is
> unclear, STOP AND ASK in the task comments — do not work around it.

## Required reading, in order

1. `amebo/docs/BOUNDARIES.md` — what amebo owns vs. references. The canonical model.
2. The `OVERVIEW.md` of the repo your task is in (amebo, abra, LinkedClaims, trust_claim_backend).
3. The repo's `CLAUDE.md` / `README.md` for local conventions and how to run it.

## Rules that are never negotiable

- **Each fact has one home.** Who a person is → abra. Tasks → Taiga. Contacts → CRM (Odoo).
  Trust → LinkedTrust. Amebo holds only orchestration state (its users, membership,
  capabilities, credentials) and transient in-flight state. Before adding a table or field,
  ask: does this fact already have a home?
- **No hacks.** No localStorage stand-ins, no magic strings, no hardcoded IDs or paths, no
  "just for this demo". If the right backend doesn't exist, stop and ask.
- **Live and claw modes must never fork.** One loop, same tools, same permissions,
  regardless of trigger. (BOUNDARIES.md "One engine, two triggers".)
- **No god-tokens.** Credentials go through the credential helper, scoped per person or per
  team. Never a super-credential, never raw secrets outside the helper.
- **Stay in scope.** Do only what the task says. If the task seems to require touching
  another system, a schema change, or a new service — comment on the task and wait.
- **Branch + PR.** Never commit to main. Small, reviewable diffs. No `git stash`.
- **If anything fails, stop and ask.** A missing path, a failing command, an unexpected
  schema — report it in the task comments. Working around it causes more damage than asking.

## If you are an AI assistant

You were probably handed this task without the project context. Do not guess it.
Read the three documents above before proposing any code. Prefer asking one clarifying
question in the task over making one assumption in code. Your output will be reviewed
against BOUNDARIES.md — code that duplicates a fact's home, forks live/claw behavior,
or invents a workaround will be rejected.
