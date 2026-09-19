---
name: map
description: A digest of many inputs as a map a person can dig into, pin, and bury. Use whenever there is more than one thing to show.
---
The surface is the map, not a report. The person reads the top layer, opens
what they want, pushes down what they do not.

- Top layer: at most seven lines, ordered by what matters most to this person
  now. A line is one thing, eight words or fewer, in the source's own words
  when there are any, with its link. A second fact is a second line.
- A line that needs the person's answer is a question, and its answer box
  sits beside it. One question, one box. Answered lines fold away.
- Under a line, folded, only if it is the thing itself: an image, a number,
  a quote. Never a description of the thing, never a path.
- Every line can be pinned (stays on top) or buried (does not come back).
  Buried and answered are remembered by the surface, not by the agent.
- Nothing about the agent itself: no "I found", no method, no fix, no file.
- What the agent inferred is marked (?); what came from a record stands plain.
- Before it is shown: the `review-as-a-human` skill, six passes.

When the receiver is a surface, end the answer with one fenced block:

```map
[{"key": "stable-slug", "line": "eight words or fewer", "link": "https://...", "ask": false, "detail": "", "source": ""}]
```

`key` stays the same across runs for the same thing, so a burial or an
answer holds. `ask: true` makes the line a question with its own answer box.
When the receiver is a channel (Slack, email): the top three lines and the
map's link. Nothing else.
