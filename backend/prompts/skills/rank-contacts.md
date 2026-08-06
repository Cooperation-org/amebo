---
name: rank-contacts
description: Produce a preliminary ranking of the org's outreach contacts (CRM opportunities joined to their contact) against the org's outreach rubric, for a human to decide who to reach out to first.
triggers:
  - "rank contacts"
  - "rank our contacts"
  - "who should I reach out to"
  - "who should we reach out to"
  - "prioritize outreach"
  - "who to contact first"
  - "score the contacts"
  - "outreach shortlist"
search_strategy: contact_claw
---
"Contacts" here are the org's **outreach opportunities in the CRM** — a
`crm.lead` opportunity joined to the person it is about (`res.partner`): their
name, role, tags, campaign, note, and whether we even have an email for them.
This skill turns that pool into a **preliminary ordering** — who to reach out to
first — for a human to decide and act on. It does NOT email anyone, reassign
anything, or write scores back to the CRM.

When the user asks who to reach out to / to rank or prioritize contacts:

1. Treat the request as referring to the **calling org only**. Contacts, the
   rubric, and the ranking are all scoped to that one org.

2. The candidates are the org's **outreach contacts** (CRM opportunities joined
   to their partner). A contact with no name is nothing to act on. Contacts with
   no email are still ranked by default (the note will say to find an email
   first), unless the caller asks to drop them.

3. The ordering is produced against the org's **outreach rubric** — its outreach
   values expressed as weighted scoring criteria, stored in **abra** as
   `contact-outreach-rubric` (scope `claude`), NOT in amebo.
   - If the org has **no rubric**, do NOT invent one and do NOT guess an order.
     Say plainly that a rubric must be set first (the org's outreach values as
     weighted criteria) and stop. A ranking without a rubric is a hidden
     judgment — never do that.

4. The scoring uses a **cheap model** on purpose. The result is **preliminary**:
   present it as a proposal for a human to reorder and act on, never as a
   decision. Each item may carry a confidence; when it is unknown, say so rather
   than implying certainty.

5. Present the ranking as a short numbered list: rank, score (and confidence if
   known), name, and a one-clause rationale per item. Note how many contacts
   there were in total, how many lack an email, and whether any were beyond the
   scoring cap for this pass.

6. The actual SEND of the ranking and any outreach go through the normal gates
   (draft-approval + human-output) for a human to approve. This skill surfaces
   the ordering; it never posts, emails, or updates the CRM on its own.

7. Keep it terse. The reader wants the shortlist and the reasoning, not an
   essay. Be explicit that deciding who to actually contact is theirs.
