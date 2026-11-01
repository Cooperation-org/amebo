---
name: partner-opportunities
description: Before someone reaches out to a person or partner, find the opportunities worth bringing up, what we and they could go after together. Reads what we already hold first and searches the web only for what is missing, saving whatever a search finds. Use for "I'm reaching out to X", "good partner opportunities for X", "what can we bring up with X".
---
Project owner: "someone in Slack can say, hey, I'm going to reach out to so-and-so, give me some good partner opportunities I can bring up to them." · "as much as possible, it hits our existing database so it doesn't just burn tokens." · "whenever it does searches, of course, it should augment the existing database."

Two different things, kept apart. An **opportunity** exists without us: an RFP or grant with a date, or a need someone stated. A **pitch** is something we made up to offer, and exists only if its people are there. Say which one each line is.

## Read first, in this order. Stop reading once you have 3 good ones.
1. **Earlier answer:** `abra --scope claude read partner-opps-<their-name>`. Use it. Check only that dates have not passed.
2. **Who they are and what they can do:** `abra --scope claude read partner-capability-<their-name>`, `abra about <their-name>`, `abra search "<name>"`, `amebo-odoo comms <name>`. People have two CRM records and change employers: check both, and go by the latest evidence.
3. **What we hold:** `amebo-elm GET /api/opportunities?tags=grant,research`, one short line per row. Pick up to 5 by title, then `amebo-elm GET /api/lead/<id>/card` for only those. Never read every card.
4. **Past work with them:** `amebo-elm GET /api/search?q=<name or org>`, and Grep `connections/` and `grants/` in the projects repo.

## Search the web only for what is still missing
Who they are now when nothing above is under a year old, or a live opportunity when fewer than 3 hold up. At most 3 searches, on their field and what they can do. Read pages only for what you would use.

**Every search saves, the moment it finds something, before you answer:**
- A live opportunity: `amebo-elm GET /api/search?q=<title>` to see if we hold it. If we do and something changed, `amebo-elm PATCH /api/lead/<id>`. If not, `amebo-elm POST /api/lead '{"agent":true,"name":"<funder or buyer>","title":"<the call>","link":"<source>","words":"Who can apply: ... Amount: ... Fit: ...","value":<stated amount>,"deadline":"YYYY-MM-DD","tags":["grant"]}'`. Tag `grant` for grants; `research` and `hard deadline` for an RFP. A date or amount goes in only if the source publishes it. Quote the source for who can apply.
- What the partner can do: `amebo-abra-store partner-capability-<their-name> "<what, with source links>" --scope claude --cat claude/partners --qualifier "<one line>" --date <today>`.

## What makes one good
- **Fits both of us.** Name what we bring from one focus area, the best fit, not LinkedClaims by default. Name what they bring, from evidence. An opportunity we could do without them is not a partner opportunity.
  - **LinkedTrust:** impact validation and claims
  - **Workers.VC:** equity sharing collaboration, the equitable governance model that can do spin-offs
  - **Civic tech:** civic tech tools
  - **Agentic AI:** business process automation, machine learning
  - **Project Money:** managing fast-moving teams for startups
  - **Risk:** no project document defines it, so read `Active/*/MAIN.md` and claim only what one says
- **Rank by:** a date still reachable, then how directly it fits, then who we know there. No invented scores.
- **Value aligned and ethical only.** Never the US Department of Defense, DHS, CBP, Border Patrol or ICE, including through a contractor.
- Fewer than 3 is fine. None is a good answer: say what was checked.

## Save the answer
`amebo-abra-store partner-opps-<their-name> "<each line, with row ids and links>" --scope claude --cat claude/partners --qualifier "<one line>" --date <today>`. A pitch is saved only here, not as a CRM row.

## Output
A person who may have moved gets one line first. Then up to 3 lines, best first. One line each: what it is, opportunity or pitch, what we bring and they bring, the date, the link. Elm link for a row (`https://elm.linkedtrust.us/lead/<id>`), source link for the rest. Nothing else.

## Don't
- Never write the message or an opening line. Facts only; the person speaks for themselves.
- Internal notes, `who we know` lines and `Why not` stay internal if the person might forward this: leave them out.
- Don't make up reminders, follow-up dates or deadlines.
- Name the person or say "they". Never he or she.
- No guessing at what a person wants or can do. Say what you could not verify.
