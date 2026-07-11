# Skill: Commitment Buzz Brief

When a new commitment lands on the Earned Governance Accelerator wall
(https://linkedtrust.us/earnedgov/), produce a **key-points brief** the team
uses to write their own announcement. This skill NEVER writes the post itself
— see no-ghostwriting.md; briefs are facts, quotes, and links only.

## Inputs
The LinkedTrust attestation (claim) for the commitment. Fetch it if given an id:
`GET https://live.linkedtrust.us/api/claims/<id>` — fields: subject (person URI),
aspect (role), statement (their words), howKnown (FIRST_HAND = self-attested,
SECOND_HAND = vouched), effectiveDate, images.

## Output — exactly these sections

**Who**: name, role committed (advisor/mentor/partner/founder/supporter), their
link. One factual line on who they are — only from their own pages or abra; if
you can't source it, say "background not verified" instead of guessing.

**Their words**: the statement from the attestation, quoted verbatim, marked as
a quote. If SECOND_HAND, attribute honestly: "as told to <voucher>". Never
paraphrase into something more quotable.

**Why it matters** (facts only): connections the team may want to mention —
e.g. prior work of the person that relates to earned governance, existing
LinkedTrust/GovKit ties. Each item must be a checkable fact with a source
pointer. No adjectives doing the work of facts.

**Links**: the attestation (https://live.linkedtrust.us/claims/<id>), the wall
(https://linkedtrust.us/earnedgov/#committed), the person's own link, any
source you cited.

**Where the team might post**: channels this audience actually reads, from org
knowledge (abra) — as a list of venues, NOT drafted posts, NOT hashtags, NOT
CTAs.

**Follow-up**: one line on what was promised to this person or what they're
waiting on, so it can be logged in the CRM.

## Hard rules
- No speakable copy, no suggested phrasings, no "you could say...".
- Only quote words that exist in the attestation or the person's own public writing.
- If the commitment's exact scope is unclear from the claim, flag it — a buzz
  post that overstates a commitment burns the relationship.
