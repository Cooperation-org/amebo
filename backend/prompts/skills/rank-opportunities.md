---
name: rank-opportunities
description: Produce a preliminary ranking of the org's unassigned/open tasks (its "opportunities") against the org's rubric, for a steering committee or funders to finalize.
triggers:
  - "rank opportunities"
  - "rank our opportunities"
  - "prioritize the backlog"
  - "what should we work on"
  - "what should we fund"
  - "preliminary ordering"
  - "score the opportunities"
  - "steering committee list"
search_strategy: opportunity_claw
---
"Opportunities" are not a new kind of record — they are the org's **unassigned,
open tasks** in the task tracker. This skill turns that backlog into a
**preliminary ordering** for a human steering committee / funders to finalize.
It does NOT decide, reassign, or fund anything.

When the user asks to rank, prioritize, or pick what to work on / fund:

1. Treat the request as referring to the **calling org only**. Opportunities,
   the rubric, and the ranking are all scoped to that one org.

2. The opportunities are **unassigned AND open** tasks (no assignee, not in a
   done status). Tasks already owned by someone are NOT opportunities — they are
   committed work; do not rank them.

3. The ordering is produced against the org's **rubric** — its values/vision
   expressed as weighted scoring criteria, stored in **abra** (not in amebo).
   - If the org has **no rubric**, do NOT invent one and do NOT guess an order.
     Say plainly that a rubric must be set first (the org's values/vision as
     weighted criteria) and stop. A ranking without a rubric is a hidden
     judgment — never do that.

4. The scoring uses a **cheap model** on purpose. The result is **preliminary**:
   present it as a proposal for humans to reorder and fund, never as a decision.

5. Present the ranking as a short numbered list: rank, score, title, and a
   one-clause rationale per item. Note how many opportunities there were in
   total and whether any were beyond the scoring cap for this pass.

6. The actual SEND of the ranking and any **budget assignment** go through the
   normal gates (draft-approval + human-output) for a human to approve. This
   skill surfaces the ordering; it never posts or funds on its own.

7. Keep it terse. The committee wants the shortlist and the reasoning, not an
   essay. Be explicit that finalizing the order and assigning funds is theirs.
