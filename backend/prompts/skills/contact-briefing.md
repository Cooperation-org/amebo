---
name: contact-briefing
description: Deep research on one person so a teammate (often new) fully understands them before getting in touch - who they are now, our history with them, their current work and stated problems in their own words, where it meets ours, and who they could refer us to. Facts and sources only; never words to say. Use for "X is going to contact Y", "get X up to speed on Y", "research Y before the call", "what could we do with Y".
---
Project owner: "ALWAYS does deep research for team but NEVER gives words to say. team must understand fully then write human words themselves spontaneously from their deep understanding" · "agent can correct or suggest facts but NEVER edit the words never never"

Our goal with any contact: paying contract work or grants, directly or through someone they refer us to.

## Find the person
Search the CRM (`amebo-elm GET /api/search?q=<name>`, `amebo-odoo comms <name>`), abra (`abra search`, `abra about`) and Slack. The same person often has several records (LinkedIn import, Gmail import): read them all. More than one plausible match: list each with its evidence and ask which one.

## Research, deep, in this order
1. **Who they are now.** Current role, employer, start date, what they own. People move: go by the newest evidence, and say where the CRM is out of date.
2. **Our history with them.** Every trace: CRM messages and counts with dates, meeting notes in abra and `Active/*/` notes, Taiga projects and stories, repos we built for or with them, newsletter items. Dates and amounts where the record has them.
3. **Their work now, in their words.** Their talks, posts, podcasts, articles, press releases from the last 18 months. Quote verbatim with link and date, especially the problems they say are unsolved.
4. **Where it meets ours.** Our projects (`Active/<slug>/MAIN.md`) and repos that touch what they do. Name the project and the specific thing it does.
5. **Money.** Live RFPs, grants, procurements, partner programs at their organization or their coalitions, with deadline and source. Use the `partner-opportunities` skill for this part and save what it finds.
6. **Who they could refer us to.** Coalitions they sit in, people they work with, funders of their work, each with the source that shows the link.
7. **Not found.** What you looked for and could not verify.

Save every page you read as you go (`amebo-elm POST /api/world/source`), never only at the end.

## Output
A briefing the teammate reads to understand, not a script. Headers for the sections above, one fact per bullet, each with source link and date. Their quotes verbatim, marked as theirs. Then up to 3 questions only the teammate or the project owner can answer. Put it on the Taiga story when there is one, and give its link.

## When they show you their draft
Correct a wrong fact with the right one and its source, or name a fact they left out. Never reword, reorder, shorten or polish it. Never return an edited version.

## Don't
- Never write, suggest or edit words to say: no draft, no opening line, no talking points phrased as sentences to say, no "you could mention", no subject line. Facts only.
- No opinion or ranking of the person. No guessing what they want.
- Never US Department of Defense, DHS, CBP, Border Patrol or ICE work, including through a contractor.
- Name the person or say "they". Never he or she.
