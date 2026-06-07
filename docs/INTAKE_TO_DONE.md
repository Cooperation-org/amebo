# Goal: Intake to Done

The flagship amebo flow Golda needs. Stated 2026-06-07, in her words.

## The goal (verbatim intent)

> I want to be able to give the links or files, in Slack or email, then tell it
> what to do about it. When I talk to it, I will say the keywords so it can find
> it. It makes a task on the board that has enough info to be doable, that has all
> the context. It notifies people in Slack. It drives to have someone do it or get
> it done. We assign some funds to it sometimes. And it checks if it gets worked on.

This is recurring real work, not a demo. Golda has ~6 items waiting to go through
this flow right now.

## What "done" means for this goal

A single path that takes an intake and drives it to completion:

1. **Intake.** Give it source material: a forwarded email, or links/files dropped
   in Slack or email.
2. **Tell it, with keywords.** Say what to do about it (voice or text), and say
   keywords so it can **find** the right intake. Binding is by keyword search
   (CRM / abra / Slack), not by replying in a specific thread.
3. **Make the work.** It creates **one task** on the Taiga board (a story with
   subtasks is not required; one task is fine). The task carries enough context to
   be doable on its own: the source material, the instruction, and relevant context
   pulled from abra / the CRM. Not a thin one-liner. **Every task has a deadline.**
4. **Notify.** It tells the right people in Slack.
5. **Fund (sometimes).** Some items get funds assigned (Taiga cash tag).
6. **Drive it forward (make sure it gets done).** The requester feeds the info and
   says what is needed; from there the system is accountable for getting it done. It
   checks whether the task is being worked on. If it is not done by the deadline, a
   claw picks it up and asks the assignee directly: "you gonna do this?" If there is
   no answer, it unassigns and gives it to someone else. **If no one picks it up, it
   tells whoever created the task** so they can add more funds or otherwise
   intervene. The escalation (deadline -> ask -> no answer -> reassign -> nobody
   takes it -> tell the creator) is mostly fixed logic; the **asking the person** is
   the part that needs intelligence (read the context, phrase it like a person,
   judge the reply).

   The escalation target is **the task's creator**, read from the task itself, never
   hardcoded. Whoever made the task is who hears about it when it stalls.

Every outbound step (board write, Slack post, assignment, funding) is a gated
draft for Golda's approval until trusted. Nothing is sent blind.

## What already exists (this session's work, on `main`, deployed live)

- **Email to CRM**: the mail poller is live (forward to the special address ->
  Odoo chatter).
- **Email to task + Slack notify**: `email_to_task_flow.py` (gated drafts).
- **Hands/eyes**: tool layer (`taiga_create_task`, `slack_post_gated`,
  `abra_search`, `odoo_search`, `crm_read_latest_email`, `taiga_list`).
- **Progress check**: `pm_claw.py` reads Taiga + goal activity, flags stalled work.
- **Output visibility**: a manual claw run now shows its per-step trail.

## What is missing (the build path to drive toward the goal)

1. **Keyword find.** Take the spoken/typed keywords and find the matching intake
   across the CRM, abra, and recent Slack. This is the binding mechanism (no thread
   reply needed). Built on the existing read tools (`crm_read_latest_email`,
   `abra_search`, `odoo_search`, Slack history search).
2. **Instruction capture.** Accept the "what to do about it" instruction (voice
   transcript or text) alongside the keywords. Voice transcription is the new input;
   once it is text, the rest is the same.
3. **One task with full context.** Crystallize intake + instruction + the found
   context into a single doable Taiga task (`taiga_create_task`, gated). Rich
   description, not a one-liner. (Story+subtasks not required.)
4. **Assignment + funding.** Route an owner assignment and an optional funds amount
   (Taiga cash tag, `mcp-taiga create --cash N`) through the gate as drafts.
5. **Drive-forward / follow-up loop.** A claw watches the created task against its
   **deadline**. The escalation is a fixed state machine; only the assignee nudge
   needs model intelligence:
   - deadline passes and task not done -> claw picks it up (`pm_claw` already flags
     overdue / no-deadline; enforce deadline-required at create time).
   - **ask the assignee** "you gonna do this?" in Slack (gated). INTELLIGENT step:
     read task + history, phrase it like a person, interpret the reply (yes / no /
     silence).
   - no answer within a window -> **unassign and reassign** to someone else (fixed
     logic), then notify. Repeat the watch.
   - nobody picks it up -> **tell the task's creator** (gated message) so they can
     add more funds or intervene. Target is read from the task's creator field,
     never hardcoded. The funds lever is theirs; the system surfaces the decision.
   Fold the "ask for help when stuck" behavior in here (same family). The imperative
   is accountability: once the creator has fed the info and said what is needed, the
   loop owns getting it done or escalating back to them, not dropping it.

## Status

Goal recorded 2026-06-07. Pieces 1-5 above are the remaining work. Building order
and the voice-binding decision tracked in `scratch.md`.
