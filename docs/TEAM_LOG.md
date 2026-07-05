# The team log — backwards-facing view (idea, not scheduled)

*AI-written (Claude Fable) record of Golda's spoken thought, 2026-07-05. Status: recorded idea — "it's not the first thing to do." Quoted phrases are hers.*

## The thought

A lightweight, dated, searchable log of what the team is doing — "a log of new things with pointers to them that can be searchable as a history" — surfaced as one of amebo's views: "a backwards-facing blog of what's been happening in the team, summarized at different levels."

Why: "Slack times stuff out after 90 days and I'm always searching for stuff." The recurring need: "oh my God, what was I working on Tuesday? What are the loose ends from there?"

The pattern is proven personally: "on my home laptop... I just have a work page dated by each day and I have notes in there... and I can search them in one directory. That's been a very useful pattern for me personally — that's why I'm thinking it could be a useful pattern for the team."

Lineage: Kene's original design for amebo was a **weekly newsletter from Slack** — highlights of what was done that week. The log is the substrate of that; the newsletter is a weekly crystallization of it (see [CRYSTALLIZE.md](CRYSTALLIZE.md)).

## Where it would live (observation, not decided)

Golda: it shouldn't clutter the projects repo, and "might be something amebo could own." One tension to resolve before building: I4 says amebo owns only transient state — but I4 *also* already names "daily journal posts" as abra-legal content (abra holds ephemera and dated entries; Golda was previously doing exactly this with abra catcodes, date-by-date). So the likely shape that fits the architecture with no new store:

- **Entries** → abra, dated, tagged, with links (the home she already used for this).
- **Capture** → amebo, as a participant: crystallized one-line log entries from Slack/CRM/repo activity, plus anything a person files directly.
- **The view** → an amebo front-end template: date-by-date, searchable, filter by tag, different summary levels (day / week / "newsletter").

## Not decided, not scheduled

Recorded so it isn't lost. Pieces it would touch when picked up: the crystallize engine (CRYSTALLIZE.md), the weekly-recap machinery that already exists for goals, and the dashboard template system ([DASHBOARD.md](DASHBOARD.md)).
