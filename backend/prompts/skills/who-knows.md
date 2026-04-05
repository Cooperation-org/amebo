---
name: who-knows
description: Find people connected to a topic
triggers:
  - "who knows about"
  - "who is the expert"
  - "who works on"
  - "who is involved"
  - "who should I talk to"
search_strategy: bindings_first
---
When the user asks who knows about a topic:
1. Check structured knowledge (bindings) for the topic name — look for RELATED, ABOUT, IS relationships
2. Search message history for the topic
3. Cross-reference: who appears in both bindings and messages?
4. Present people with their relationship to the topic and recent activity
5. If there are hot tags related to the topic, mention the priority context
