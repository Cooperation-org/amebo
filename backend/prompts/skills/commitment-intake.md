# Skill: Commitment Intake

When a team member says someone has committed to the accelerator effort
("Mike's in as an advisor", "she agreed to mentor"), record it as a public
attestation using the `linkedtrust_create_commitment` tool so it appears on
the wall (https://linkedtrust.us/earnedgov/#committed).

## Gather (conversationally, don't interrogate)
1. **Who** — name, and their link (LinkedIn or site). No link? Proceed without.
2. **Role** — advisor | mentor | partner | founder | supporter. If ambiguous, ask.
3. **Their words** — VERBATIM. "What did they actually say?" This is the one
   thing you must never fill in yourself: no words → no claim, ask first.
   Tightening whitespace is fine; rephrasing, polishing, or extending is not.
4. **How known** — the person speaking for themselves here = FIRST_HAND (rare
   in chat); a team member relaying what they were told = SECOND_HAND (default),
   with `source_uri` = the relayer's link.

## Then
- Call `linkedtrust_create_commitment`. It routes through the approval gate
  (an owner directing you live executes immediately).
- Tell them the person can upgrade a relayed claim to their own words + video
  at https://linkedtrust.us/earnedgov/commit/?upgrade=<claim_id>.
- Offer a buzz brief (load the `commitment-buzz-brief` skill) — facts, quotes,
  links only; the human writes any announcement themselves.
- Log a follow-up for the person in the CRM if one doesn't exist.

## Never
- Never invent, embellish, or "clean up" the commitment statement.
- Never overstate scope: record exactly what was committed, nothing grander.
- Never announce anywhere yourself — briefs only, humans post.
