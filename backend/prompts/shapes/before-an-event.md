---
name: before-an-event
description: The timeline before a dated event, so seats fill and people arrive ready. Use for a workshop, a launch, a deadline.
---
An event has a date. Everything before it is a set of moves at offsets from
that date. The structure is the same for every event; the offsets and moves are
set per event and live on the event's own record, never in the agent.

```
event {name, date}
  move {when: offset before the date, what, who acts, to whom, done when}
```

Each run: which moves are due now, which are late, how many people are signed
up versus the last check, and who signed up and has not heard from us. Surface
late and due as a `map`; nothing else.

The failure this shape exists to prevent (project owner, 2026-09-19): "we
didn't realize people had signed up ... I didn't wind up sending the messages
till the night before."
