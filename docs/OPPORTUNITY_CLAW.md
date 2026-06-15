# Opportunity Claw — preliminary prioritization

The prioritization claw. Sits beside `pm_claw` and uses the same machinery.

## The problem it solves

An org always has more it *could* do than it can fund. There was no home for
that pool of candidates — the CRM holds people, the tracker holds *committed*
tasks, nothing held "things we could spend time on, awaiting prioritization."

**Decision (Golda, 2026-06-14): opportunities are not a new record type — they
are the org's unassigned, open tasks in the task tracker.** No new table, no new
store. This claw reads them, scores them against a rubric with a cheap model,
and hands a *preliminary ordering* to a human steering committee / funders.

## The flow

```
unassigned/open tasks  →  score vs rubric (cheap model)  →  rank  →  gated draft
   (TaskReader)            (Scorer = haiku)                          (humans
                            rubric from abra (RubricReader)           finalize
                                                                      order + $)
```

- **Candidates** = open (not done) AND unassigned tasks. `select_candidates()`.
- **Rubric** = the org's values/vision operationalized as weighted criteria.
  Lives in **abra** (semantic, per-audience), never in amebo. This is how the
  top of the spine (values/vision) gets teeth at the bottom (what we fund).
  **No rubric → the claw stays silent and ranks nothing.** A ranking without
  explicit criteria is a hidden judgment; we never do that.
- **Scorer** = a cheap model (haiku). Correct *because* the rubric carries the
  judgment and a human finalizes — the model produces a draft order, not a
  decision.
- **Finalize** = the existing gates. The SEND is outbound → draft-approval gate
  (default-deny). Budget assignment is the committee's, surfaced not decided.

## Boundaries (docs/BOUNDARIES.md)

amebo owns no task list, no rubric, no budget. The claw READS tasks
(`TaskReader`, reused from `pm_claw`), READS the rubric (`RubricReader` → abra),
SCORES (`Scorer` → cheap model). All three are Protocols — real adapters bind to
the tool layer / abra / Anthropic; tests inject fakes. The claw performs **no
direct side effect**: it returns a `RankingReport` and routes the message
through the gates.

## Skill

`prompts/skills/rank-opportunities.md` lets the chat surface invoke the same
behavior ("rank our opportunities", "what should we fund"). One pattern, two
triggers (scheduled claw + chat skill) — same as goals.

## Rubric shape in abra

The rubric content blob is JSON:

```json
{"criteria": [
  {"name": "real-world impact", "weight": 2.0, "description": "..."},
  {"name": "fits our vision",   "weight": 1.5, "description": "..."}
]}
```

## OPEN integration decision (not invented here)

**Which abra (scope, name) holds a given org's rubric is not yet decided**, so
`AbraRubricReader` takes an injected `resolve(org_id) -> (scope, name) | None`
rather than guessing a convention. Pick the convention before wiring the real
adapter (per the repo's "never invent a stand-in" rule). Candidates: a fixed
name per org scope (e.g. scope `org-<id>`, name `rubric`), or an explicit
binding from the org row to an abra name.

## Status / wiring

Additive and **not wired to the scheduler** — same state as `pm_claw`. To go
live it needs the same seam both claws share:

1. The real `TaskReader` adapter is built: `TaigaCliTaskReader`
   (`src/services/taiga_task_reader.py`), shared with `pm_claw`. Taiga has no
   org object — an org IS the set of projects its login sees — so the adapter
   resolves **org → Taiga login token**, enumerates that login's projects, and
   aggregates stories. **Prerequisite:** `org_credentials` has no `taiga` kind
   yet, so per-org Taiga tokens have nowhere to live; add that kind before
   `resolve` can read a real token.
2. A `resolve` for `AbraRubricReader` (the open decision above).
3. `AnthropicScorer` is ready (haiku, mock fallback when no key).
4. A scheduler branch / trigger, and the gated Slack-send executor on approval.
