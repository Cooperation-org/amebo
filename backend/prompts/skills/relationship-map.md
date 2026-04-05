---
name: relationship-map
description: Show how entities are connected
triggers:
  - "how is .* related"
  - "what's the connection between"
  - "who is .* connected to"
  - "show me the relationships"
search_strategy: bindings_first
---
When the user asks about relationships between entities:
1. Look up bindings for all named entities
2. Find shared connections (A related to C, B also related to C)
3. Present the relationship graph in plain language
4. Include qualifiers and permanence where relevant (e.g., "CURRENT team lead" vs "FORMER advisor")
5. Note any hot tags on the entities
