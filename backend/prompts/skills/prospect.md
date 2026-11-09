---
name: prospect
description: Sales prospecting. Find specific, live opportunities (a dated tender or grant, a funding round, a hiring post for work we do, a need someone stated) AND a specific person we know connected to each, then attach them to an existing lead, opportunity or campaign. Use for "prospect", "find hot opportunities", "sales prospecting for X", "who should we go after in X".
---
Project owner: "push it to do specific research to be valuable not just general, when doing sales prospecting" · "search for specific hot opportunities AND specific connections to them, that we could bring into existing opportunity or lead or campaign" · "using YDC tools or other tools" · "bullet points facts exactly. I WILL INTERPRET THEM"

Specific means: a named organization, a named thing they are buying, funding or hiring for, a date or amount they published, and the page that says so. "Healthcare is adopting AI" is not an opportunity. "St. Luke's posted RFP 2026-114 for intake automation, due 2026-12-15, link" is.

## Steps
1. **Scope.** The area, campaign or lead named in the message. A campaign or lead: read it first (`amebo-elm GET /api/campaigns`, `amebo-elm GET /api/lead/<id>/card`). Nothing named: ask one question, which area.
2. **What we already hold.** `amebo-elm GET /api/world/opportunity`, `amebo-elm GET /api/opportunities?tags=research`, `amebo-elm GET "/api/search?q=<area or org>"`. Do not search the web for what is already there.
3. **Hot opportunities, searched.** `ydc search "<specific query>" -n 10` for tenders, RFPs, grants with deadlines, funding rounds in the last 90 days, job posts for work we do (agentic AI, automation, verification, credentials), public statements of need. `ydc research "<question>"` only for one hard question, it is slow. WebSearch when ydc has nothing. Keep only ones with a date in the future or in the last 90 days, a named organization and a source page. At most 5.
4. **Connections, for each.** Who we know there or one step away: `abra who "<org>"`, `abra search "<org>"`, `amebo-elm GET "/api/search?q=<org>"`, `amebo-odoo comms <name>`. Evidence only: a message, a meeting, a LinkedIn connection. Name the person and the evidence. None: say "none found".
5. **Save as you go, the moment you have each one.** The opportunity: `amebo-elm POST /api/world/opportunity '{"name":"...","kind":"rfp|grant|need","uri":"<source>","issuer":"<org>","amount":<published or omit>,"deadline":"YYYY-MM-DD or omit","summary":"<facts>","sourceUrl":"..."}'`. Attach it to the lead it belongs to: `amebo-elm PATCH /api/lead/<id> '{"opportunity_id":<id>}'`. A lead that does not exist yet stays unmade: list it, a person decides.
6. **Ethics.** Value aligned only. Never the US Department of Defense, DHS, CBP, Border Patrol or ICE, including through a contractor.

## Output
Facts only, one bullet each, each with its source link. No opinion, ranking words, reasoning, or account of what you searched.
- **<Org>: <what they are buying, funding or hiring>**, <date>, <amount if published>. <source link>
  - Connection: <person>, <evidence>. Or "none found".
  - Attached to: <elm link>. Or "no lead yet".

Under 400 characters per opportunity. Nothing found: "Nothing found in <scope>." and the queries' topic in a few words.

## Don't
- Never write the message or an opening line.
- No general market statements, trends or sizes.
- No invented dates, amounts or connections.
