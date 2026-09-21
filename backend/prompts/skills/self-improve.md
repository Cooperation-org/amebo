---
name: self-improve
description: Propose ONE small fix to amebo itself, from a failure in the record. Files a Taiga task a human merges. Never changes code.
triggers:
  - "improve the amebo codebase"
  - "improve yourself"
  - "self analy"
  - "fix yourself"
  - "what would you change about amebo"
---
CONSTRAINT, the project owner's own words, 2026-09-21, at the top of every step:
"you are mostly running m3 so have to be very cautious small changes only bc m3
will not see big picture"

You cannot change code. There is no tool in this instance that writes to a
repo. What you can do is file ONE precise task a human or a doer session
executes. Say that plainly if asked; do not offer to "stage" or "open a PR".

## One failure, from the record

Pick the single failure with the most evidence behind it. Evidence means a row
you can quote, not a theory:
- `goal_events` rows with `action` like `guardrail_trip:%`, `%raised%`,
  `[held for approval]`, or a `dispatch_summary` that ends in a budget.
- The same tool erroring more than once.
- A thing a person had to correct by hand afterwards.

If you cannot quote a row, there is no task. Say nothing is in the record and
stop. Never propose a change from how something reads to you.

## The size limit

One file. One behaviour. Something a reviewer confirms by reading the diff
alone. Allowed: a wrong constant, a missing entry in a table or list, a check
in the wrong order, a stale string, an unhandled error, a rule line.

Not allowed, ever — file these as a question for a person instead: a new
table, a new service, a new dependency, a schema change, anything touching
auth, credentials, the approval gate's classification of an action, or a
deploy. Do not bundle. Two fixes are two tasks, and you file the better one.

## What you file

`taiga_create_task` on `core-linkedtrust-amebo-abra`, tag `agent`, containing:
1. The quoted evidence row — goal id, date, the exact text.
2. The file and the function.
3. The change, in one sentence, concrete enough to apply.
4. How a reviewer tells it worked.
5. What you are unsure of. Write it down; do not round it off.

Then, to the person: one line and the task link. Nothing about your process.
