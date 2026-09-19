---
name: map
description: A digest of many inputs as a map a person can dig into, pin, and bury. Use whenever there is more than one thing to show.
---
The surface is the map, not a report. The person reads the top layer, opens
what they want, pushes down what they do not.

- Top layer: at most seven lines, ordered by what matters most to this person
  now. Each line is one thing, in the source's own words when there are any,
  with its link.
- Under each line, folded: the detail. Sources, numbers, what happened, links.
- Every line can be pinned (stays on top) or buried (does not come back).
  Buried is remembered by the surface, not by the agent.
- Nothing about the agent itself: no "I found", no method, no work summary.
- What the agent inferred is marked (?); what came from a record stands plain.

When the receiver is a surface, end the answer with one fenced block:

```map
[{"key": "stable-slug", "line": "one line", "detail": "folded text, may be several lines", "link": "https://...", "source": "where this came from"}]
```

`key` stays the same across runs for the same thing, so a burial holds.
When the receiver is a channel (Slack, email): the top three lines and the
map's link. Nothing else.
