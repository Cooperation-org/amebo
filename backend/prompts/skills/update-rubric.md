---
name: update-rubric
description: Change what this team's work list treats as important, when someone says what matters to them (money, a person waiting, partnerships, cases). Reads the rubric first, proposes the smallest change, files it through set_rubric for approval.
triggers:
  - "what matters"
  - "rubric"
  - "why is this at the top"
  - "should be first"
  - "more important"
---
The list every person sees ranks on the org's rubric (src/services/rubric.py):
weights on a few signals, plus a focus line in the team's own words. A real due
date always outranks everything judged; the rubric only orders the undated rest.

1. `read_rubric` first. Say the current order in one line.
2. Map what the person said to the signals. Their words, not yours, go in
   `focus` and `why`:
   - "someone is waiting on me / asked me" → `someone_waiting`
   - "they replied / they're interested / warm contact" → `contact_interested`
   - "will it generate money / revenue" → `money`
   - "partnerships, attention" → `contact_interested` up, `money` 0
   - "cases, advocacy, no money" → `money` 0, `someone_waiting` highest
   - "show me only the top few" → `top_n`
   - anything that is a rule in words rather than a weight ("this month
     Level Up comes first", "a warm intro cooling beats a cold lead") →
     `judgement`, verbatim. A model applies it inside the hard order and
     says why on the row.
3. Change as little as possible. One or two weights, or the focus line. Do not
   rewrite weights nobody mentioned.
4. `set_rubric` with only the changed fields and `why`. It is gated: a human
   approves before the list changes. Tell the person in one line what will
   change and that it is waiting for approval.
5. Never invent what matters to a team. If nobody said, ask one question.
