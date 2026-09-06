---
name: doer
description: Pick up agent-tagged tasks from the three Taiga boards and do them, in a Claude Code session or an amebo claw. Fix what is clear, park what needs a human with exactly what is needed, one Slack line with a Marten link only when a person must act.
triggers:
  - "pull tasks"
  - "work the board"
  - "do the agent tasks"
  - "what's on the board for you"
---
You do tasks. You do not make them (that is `goals-intake` and `make-task`).

## Pull

    mcp-taiga list core-linkedtrust-amebo-abra --tag agent --status New
    mcp-taiga list earned-governance-toolkit-accelerator --tag agent --status New
    mcp-taiga list voluntask --tag agent --status New

Take the first one whose description you can start without a question. Move
it to `In progress` before touching anything, so a second session does not
take the same one.

## Do

- The description is the contract: where, what is true now, what should be
  true when done, first step. If any of the four is missing, it is a bad task:
  park it (below) rather than guess.
- Code goes through the repo: pull, small commits to main, push. Never edit on
  a deployed box. Never `sudo` on shared services. Never another user's home.
- Test it the way a person uses it before calling it done. "The service is
  running" is not a test.
- Findings that are not code (research, contacts, prior art) go on the task as
  a comment, as bullets with links — and on the CRM record if it is about a
  person or org. Never as a narrative someone might paste.

## Finish

    mcp-taiga comment <board> <ref> "DONE: <what changed, how verified, links>"
    mcp-taiga move <board> <ref> "Ready for test"

The first word is the contract: `DONE:` folds into the person's review pile,
`NEEDS:` is a decision that stands on its own row.

## Park

When a decision, credential, permission or missing fact stops you:

    mcp-taiga comment <board> <ref> "NEEDS: <the one thing>. Because: <one line>."
    mcp-taiga move <board> <ref> "Needs human"

Then one Slack line in `#ai-workflow-automations`, @-mentioning the owner, with
the Marten link `https://marten.linkedtrust.us/board?story=<ref>`. Nothing
else in Slack, ever. No Taiga UI links.

## Amebo claws

An amebo claw with this skill does the non-code kinds only: research, CRM,
outreach preparation. A task that changes a repo is for a Claude Code session;
the claw leaves it in `New` and says nothing.
