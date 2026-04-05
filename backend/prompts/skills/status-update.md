---
name: status-update
description: Summarize recent activity on a topic
triggers:
  - "what's the status"
  - "what happened with"
  - "update on"
  - "what's new with"
  - "any progress on"
search_strategy: vectors_first
time_bias: recent
---
When the user asks for a status update:
1. Search message history with time bias (prioritize last 7-30 days)
2. Check hot tags for priority context on the topic
3. Check bindings for project relationships and key people
4. Synthesize a timeline-ordered summary with attribution (who said what, when)
5. Highlight blockers, decisions, and next steps if present in the messages
