# Making amebo useful

Project owner, 2026-09-19: "I just want to tell you something so you can
incorporate it into all the systems we've been designing ... surface one small
thing back to me. That's how it goes."

## What the numbers say (last 30 days unless noted)

| | |
|---|---|
| chat turns from people | 63 (13 Slack threads, 12 CLI, 0 web) |
| cron claws that ran with a model before 2026-09-19 | 0 of 20 dispatches |
| tools registered / used by claws | 49 / 15 |
| tool calls that errored | 23 of 232; `campaign_link` 8 of 8 |
| claw runs stopped by the 5-round budget | 6 (rounds spent listing directories) |
| gated actions ever approved by a person (all time) | 11 of 104; 64 rejected, 20 still pending, median age 15 days |
| inbox rows that are "contact, nothing scheduled" | 12 of 20 |
| pins or buries ever made on the inbox | 4, by one person |
| backend error lines, 14 days | 6,426 (6,296: Slack backfill on 52 channels the bot is not in) |
| spend on claws | $6.63 |

Every write a claw wants goes into an approval queue that a person has answered
eleven times in the life of the system. A claw gets five tool rounds and fifty
cents, spends them finding out where things are, and stops. What it does find
lands on a goal row nobody opens. The surface people were given is twelve
contact rows with nothing to do.

## Proposal

1. **Trust tiers replace the draft gate.** Reads: free. Writes into our own
   systems that a person can undo (Taiga, CRM notes, abra, the org repo, dev
   deploys): free, one audit line each. Words a person outside will read
   (Slack post, email, social): pass a sanitizer (their words only, one line,
   no AI voice, no drafting for a human) and then post, gated only for a new
   recipient. Destructive: gated. `pending_actions` keeps the last tier only.
2. **A hand that can do.** A claw that has a clear task hands it to a bounded
   Claude Code session on this VM (the `doer` skill and Taiga `agent` tag
   already exist), dev and demo only, and reports the link. Today a claw can
   read the org repo and nothing else; everything shipped this week was done
   outside amebo.
3. **Know where things are.** One org note (the app registry, the repos, the
   boards, the DBs) in every claw prompt, kept in abra working memory, so no
   round is spent on `ls`. Budgets by kind of goal: research 25 rounds / $3,
   a check 5 rounds / $0.50.
4. **One surface, one shape.** A claw run ends in a map (seven lines, a press
   per line, a question with its answer box). The goal map page is the
   surface; the inbox drops contact rows that carry no next step; Slack gets
   one line and the map link only on a NEEDS: line. "Drafts waiting on you"
   goes away with the gate.
5. **Intake is the front door.** What the owner says (voice, paste, Slack)
   runs the goals-intake path inside amebo: goals, tasks, abra names,
   statements, in their words. It is a Claude Code skill today, not an amebo
   one.
6. **Turn off what lies.** Backfill only channels the bot is in; fix
   `campaign_link` and `list_projects` config; drop the Discord bot until it
   has a token; make the GC enumeration error fatal or silent, not 102 lines.

Order: 6, 3, 1 (a week), then 4, then 5, then 2.
