---
name: goals-intake
description: Turn messy free text (a meeting transcript, a pasted document, a forwarded email, a voice ramble) into goals in amebo, tasks in Taiga, names in abra, and running claws — asking one to three clarifying questions first. Use when someone hands over goals for the week, a transcript, or "separate these into goals and tasks".
triggers:
  - "goals for the week"
  - "separate these out into goals"
  - "here is the transcript"
  - "break this into tasks"
  - "put these in the system"
---
Input is messy and comes from anywhere. Nobody adapts to the system; the
system takes what it is given (golda 2026-09-06). This is the one path from
free text to work that moves on its own.

## Where each thing lives (one home each)

| thing | home | how |
|---|---|---|
| a goal (human, this week or standing) | amebo `goals`, no trigger | `POST /api/goals/` or `amebo-claw create` — no `--cron` |
| a claw (amebo works it unattended) | amebo `goals`, cron trigger | same, `--cron "0 15 * * 1"` |
| a task (a person or a doer session does it) | Taiga story, tag `agent`, status `New` | `mcp-taiga create <board> "<subject>" -t agent -s New -d "..."` |
| the name that glues them | abra, scope `linkedtrust`, qualifier `goal` | `abra store <pet-name> "<goal in their words>" --qualifier goal --scope linkedtrust --cat linkedtrust/goals` |
| the name's bindings | abra | `abra bind <pet-name> EXECUTES_VIA amebo:claw/<uuid> --target-type uri`; `abra bind <pet-name> HAS tasks:taiga/<board>/<ref> --target-type uri` |

Boards: LinkedTrust (incl. amebo, abra) `core-linkedtrust-amebo-abra`;
workers.vc / Earned Governance `earned-governance-toolkit-accelerator`;
Raise the Voices `voluntask`. Org: whatever the person said the thing is for.
If they said "this is for CIVICUS" and you do not know what CIVICUS is here:
`abra search civicus` before asking.

## Do, in this order

1. **Read all of it before writing anything.** Split by org, then by goal. A
   goal is an outcome in their words, not a task. Keep their phrasing, their
   hedges ("I don't know if that's practical"), their names for things.
2. **Search abra for every name** (`abra about`, `abra search`). A goal that
   already has a pet name is the same goal: extend, do not duplicate. A person,
   org or project named in the text gets linked, not re-described.
3. **Ask one to three questions, never more,** only where an answer changes
   what gets made: which org, who owns it, whether a thing already exists. Not
   details. Then wait. If no answer comes, make what is unambiguous and mark
   the rest `Backlog`.
4. **Make the goals.** One amebo goal per goal, `config.owner` = the person
   (their Taiga username from `instances.config.taiga_identities`),
   `config.org_label` = the org name as they said it, `notify_channel` =
   `slack:#ai-workflow-automations`. Title in their words.
5. **Name each goal in abra** and bind it to the amebo goal id. This is how a
   forwarded email about "Open Supply Hub" later finds the goal.
6. **Make the tasks** with the `make-task` skill: DO NEXT with links at the
   top, tag `agent`, status `New`, a `goal:<first 8 of the goal id>` tag, and
   a due date only if they gave one. Bind each to the abra name.
7. **Attach one claw per goal that wants unattended work** (research, finding
   partners, watching a goal). Cron weekly, not daily. Its description says
   what to chase, which skills to load (`find-partner`, `rank-opportunities`,
   `ecosystem-research`, ...), and that it writes findings to the CRM record
   or the task, never to Slack. Bind it `EXECUTES_VIA`.
8. **Trigger the first run**: `POST /api/goals/<id>/dispatch-now`.
9. **Report in one line per goal** with the Marten link
   (`https://marten.linkedtrust.us/board?story=<ref>`), never a Taiga link.
   Slack gets one line and a link, if anything.

## Never

- Draft what a person will say to another person. Bullets and references only.
- Make a daily claw. Weekly, or when asked.
- Put a goal in abra only. Abra is the name, amebo is the goal, Taiga is the work.
- Invent an owner, an org, or a due date.
