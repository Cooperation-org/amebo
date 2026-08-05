# Statements — what an org is aiming at

Mission, vision, values, strategy, OKRs. `src/db/repositories/statement_repo.py`
(the store), `src/services/statements.py` (reading a pointer),
`src/api/routes/statements.py` (the API), `src/components/goals/Statements.tsx`
(the page, above the goals), migration 031.

## The shape

One record, and it is a pointer, not a mission statement.

| Field | What it is |
|---|---|
| `name` | the relation, in the team's own word: `mission`, `values`, `Q3 OKRs`, `operating principles` |
| `body` | their words, held here because someone pasted them |
| `pointer` | a URI, when the words live somewhere else |
| `source` | where it came from, in their words: "photo of the whiteboard, 4 aug" |
| `informs_priority` | whether it steers anything |
| `accepted_at` | null = amebo proposed it, and it does nothing |
| `holder` | `org` today; `project:<slug>` or `person:<login>` when one of those holds its own |

`body` or `pointer`, never both. The name carries the meaning, so nothing parses
the document — a team that keeps "operating principles" writes that and it works.

Golda 2026-08-05: "Mission Vision those kind of things should probably live in a
document that has a pointer to it ... the way we know to use it is by the
semantics of the thing pointing to it."

## Where the words live

`RESOLVERS` in `services/statements.py` maps a URI scheme to a reader. A new
place words can live is one entry there and nothing else moves.

| Pointer | Read from |
|---|---|
| *(none — body set)* | the row |
| `https://…` | the public web, through `tools/http_fetch` (its SSRF rules, not a second set) |
| `repo:docs/mission.md` | this org's context repo, confined to the repo root |
| `abra:some-name` | abra content |

An unknown scheme is not an error. The row stays on the page and contributes
nothing, because a pointer nobody can follow yet is still worth writing down.
Read text is capped at `MAX_CHARS`.

## What it steers

Goal dispatch. `_load_org_context` takes the switched-on statements and puts
them in the system prompt under the team's own headings. Which ones were used is
written to `goal_events` as `statements_used`, so someone who disagrees with a
run can get from it back to the row and change it.

Explicit beats guessing: an org with statements switched on gets only those.
Only an org that has said nothing falls back to the old vector search for the
literal words "vision" and "values" — a guess, and one nobody could see.

Nothing is load-bearing. No statements, and goals are pursued exactly as before
any of this existed.

Not wired: the work list's judged rank. That half is deliberately small and
deterministic and every card says in plain words why it sits where it does
(`WORK_LIST.md`). Free text cannot be scored that way without a model call per
card per page load, and the reason would stop being defensible. Statements steer
what the claw pursues; the clock still ranks what a person is shown.

## Whose words

Only text a human wrote or pasted counts. Amebo may propose — a statement
created under a service key lands with `accepted_at` null, visible on the page
and read by nothing. A person accepting is what makes it live, and correcting a
proposal reassigns authorship to them. Amebo never rewrites a statement.

## Still open

- No proposer yet. Nothing extracts candidate statements from transcripts,
  whiteboard entries or documents; the accepted/proposed split exists so one can
  be added without changing the record.
- `holder` is always `org`. A project or a person holding its own is a filter,
  not a migration.
- A photographed whiteboard is typed in by a person. No image reader.
