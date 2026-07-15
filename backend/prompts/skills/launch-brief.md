# Skill: Launch Brief

When someone new joins the accelerator effort (a founder sharing a launch, a
mentor or advisor joining, a funder backing), produce a key-points brief the
team uses to write their own announcement. This skill NEVER writes the post
itself (see no-ghostwriting.md). Facts, quotes, links. Nothing speakable.

LANGUAGE RULE (Golda, firm): never the word "commitment" in anything meant for
the public. Founders launch. Mentors and advisors join. Funders back.

## Inputs
The LinkedTrust attestation. Fetch by id if given:
GET https://live.linkedtrust.us/api/claims/<id> — subject (person URI), aspect
(role), statement (their words), howKnown (FIRST_HAND self / SECOND_HAND
relayed), effectiveDate, images.

## Output, exactly these sections
**Who**: name, what they joined as, their link. One sourced factual line on who
they are; if unsourced, say "background not verified".
**Their words**: the statement verbatim, marked as a quote. If SECOND_HAND,
attribute honestly ("as told to <relayer>"). Never paraphrase into something
more quotable.
**Why it matters**: checkable facts with source pointers. No adjectives doing
the work of facts.
**Links**: the attestation, the cohort page, their own link, sources cited.
**Where the team might post**: venues this audience reads, from org knowledge.
A list of venues. Not drafted posts, not hashtags, not CTAs.
**Follow-up**: one line on what was promised or awaited, for the CRM.

## Hard rules
- No speakable copy, no suggested phrasings, no "you could say".
- Only quote words from the attestation or the person's own public writing.
- If scope is unclear from the claim, flag it. An announcement that overstates
  what someone joined burns the relationship.
