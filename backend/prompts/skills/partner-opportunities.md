---
name: partner-opportunities
description: Before someone reaches out to a person or partner, find the opportunities worth bringing up, what we and they could go after together. Reads what we already hold first and searches the web only for what is missing, saving whatever a search finds. Use for "I'm reaching out to X", "good partner opportunities for X", "what can we bring up with X".
---
Project owner: "someone in Slack can say, hey, I'm going to reach out to so-and-so, give me some good partner opportunities I can bring up to them." · "as much as possible, it hits our existing database so it doesn't just burn tokens." · "whenever it does searches, of course, it should augment the existing database."

Two different things, kept apart. An **opportunity** exists without us: an RFP or grant with a date, or a need someone stated. A **pitch** is something we made up to offer, and exists only if its people are there. Say which one each line is.

## Read first, in this order. Stop reading once you have 3 good ones.
1. **Their list:** `amebo-elm GET /api/partners` for their id, `amebo-elm GET /api/partners/<id>` for their rows. Rows already there are the answer: use them, and check only that dates have not passed. Not listed: `amebo-elm POST /api/partners '{"name":"<name>"}'`.
2. **What they can do:** `amebo-elm GET "/api/world/capability?entity=<id>"`, `abra about <their-name>`, `abra search "<name>"`, `amebo-odoo comms <name>`. People change employers: go by the latest evidence.
3. **What we can do:** `amebo-elm GET /api/world/capability` (entity LinkedTrust).
4. **What exists:** `amebo-elm GET /api/world/opportunity`, one short line each: RFPs, grants, stated needs. Our pitches and research: `amebo-elm GET /api/opportunities?tags=research`. Pick up to 5 by title, then `amebo-elm GET /api/lead/<id>/card` for only those. Never read every card.
5. **Past work with them:** `amebo-elm GET /api/search?q=<name or org>`, and Grep `connections/` and `grants/` in the projects repo.

## Search the web only for what is still missing
Who they are now when nothing above is under a year old, or a live opportunity when fewer than 3 hold up. At most 3 searches, on their field and what they can do. Before fetching a page, `amebo-elm GET "/api/world/source?url=<url>"`: if stored and under 30 days old, read that.

**Every search saves, the moment it finds something, before you answer:**
- A page you read: `amebo-elm POST /api/world/source '{"url":"...","title":"...","text":"<what it said that matters>"}'`.
- A live opportunity: `amebo-elm POST /api/world/opportunity '{"name":"<the call>","kind":"rfp|grant|need","uri":"<where published>","issuer":"<org>","amount":<published>,"deadline":"YYYY-MM-DD","whoCanApply":"<quote the source>","summary":"...","sourceUrl":"..."}'`. It matches on uri and name, and updates what we hold. A date or amount goes in only if the source publishes it. A `need` is one a person stated, with where they said it.
- What the partner can do: `amebo-elm POST /api/world/capability '{"entityId":<id>,"name":"<short>","description":"<what, in their words>","sourceUrl":"..."}'`.

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
Each line goes on their list: `amebo-elm POST /api/partners/<id> '{"opportunityId":<id>,"why":"<what each side brings, plain facts, written for the partner to read>","rank":<fit>,"capabilityIds":[<ours>,<theirs>]}'`. A pitch has `"title":"..."` and no `opportunityId`. `rank` is the rubric's alignment: 80+ their stated need matches, 40 to 60 plausible, under 20 a stretch. It matches what is there and updates it. Their list: https://elm.linkedtrust.us/partners?partner=<id>

## Output
A person who may have moved gets one line first. Then up to 3 lines, best first. One line each: what it is, opportunity or pitch, what we bring and they bring, the date, the link. Elm link for a row (`https://elm.linkedtrust.us/lead/<id>`). Then their list link. Nothing else.

## Don't
- Never write the message or an opening line. Facts only; the person speaks for themselves.
- `why` goes to the partner. No internal notes, `who we know` lines, `Why not` or guesses about them in it.
- Don't make up reminders, follow-up dates or deadlines.
- Name the person or say "they". Never he or she.
- No guessing at what a person wants or can do. Say what you could not verify.
