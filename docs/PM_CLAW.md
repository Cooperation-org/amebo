# PM Claw

A project-management claw for Amebo. Once a day it reads project state, assesses
it, and reports **ONE** concise stand-up covering **all** goals — through the
existing noise gate. It is additive: all-new files, no edits to the registry,
scheduler, or app entrypoints.

## Why

`docs/BOUNDARIES.md` says Amebo "leans on the task tracker as the heartbeat":
the canonical task list and deadlines live in Taiga, not in Amebo. The PM claw
is the agency layer over that heartbeat. A good human PM does not narrate every
ticket; they look at the board once a day and say one useful thing. This claw
does exactly that and routes it through the gates so it stays a quiet, useful
colleague rather than a firehose.

## What it checks (the assessment)

`assess(tasks, activity, *, config, now)` is pure (no I/O, no gates) and raises
these flags:

| Flag | Condition |
|---|---|
| `OVERDUE` | open task whose `due_date` is before now |
| `DUE_SOON` | open task due within `due_soon_within_days` (default 2) |
| `NO_DEADLINE` | open task with no `due_date` |
| `NO_ASSIGNEE` | open task with no assignee |
| `GOAL_OFF_TRACK` | goal whose last activity is older than its cadence (`cadence_days`, else `default_stale_after_days` = 7), or that has never recorded any activity |

Done tasks (`done/closed/completed/resolved`, case-insensitive, configurable)
are ignored. The result is a structured `StandupReport`: a per-goal rollup
(`GoalRollup`: open/overdue/unassigned/no-deadline counts + off-track) plus a
flat `FlagItem` list. The caller always gets the full assessment regardless of
what the gates do with the message.

## How it composes with the two gates

The claw performs **no direct side effect**. It returns the report and queues a
gated/deferred message. Two gates sit on the outbound path and compose (see
`docs/OUTPUT_GATE.md`, `docs/DRAFT_APPROVAL_GATE.md`):

1. **Draft-approval gate (ACTION gate, `draft_approval_service`).** A Slack post
   is outbound, so the SEND is routed through `gate_or_execute(...,
   action_type="slack_post", ...)`. `slack_post` is GATED by default-deny, so it
   is held for a human to approve; the claw passes a deferred-send hook as the
   `executor`, which runs **only** on approval. The claw never executes a send.

2. **Human-output gate (MESSAGE gate, `human_output_gate.HumanOutputGate`).**
   The one stand-up body is handed to `output_gate.gate(text, channel=...,
   urgency="normal")`, which DEFERs it into the channel's daily digest. At the
   stand-up hour the scheduler calls `flush_daily_digest`, which crystallizes
   **all** queued items into **one** message covering **every** goal — many
   goals collapse into one message, not one per goal. We reuse the gate's
   batching / crystallize / thread-prefer machinery wholesale and reinvent
   nothing.

`goal_id` is deliberately omitted when deferring: the single message spans all
goals. A quiet project (no open tasks, no flags) queues nothing — the claw stays
silent.

## Injection seams + TODOs

The claw depends on Protocols, never on concrete tools, so tests inject fakes and
real adapters bind to the tool layer / `goal_events`:

| Seam | Protocol | Real adapter (TODO) |
|---|---|---|
| Tasks | `TaskReader.list_tasks(*, org_id)` → `Sequence[Task]` | wrap the `mcp_taiga` tool in `src/tools/registry.py`; map rows to `Task(id, title, status, assignee, due_date, goal_id)`; run under the org's team-scoped service credential (BOUNDARIES.md), never a god-token |
| Goal activity | `GoalEventReader.recent_activity(*, org_id)` → `Sequence[GoalActivity]` | read `goal_events` via `GoalRepo.list_for_org` + `list_events`; derive `cadence_days` from each goal's `trigger_config` cron period or `target_criteria` |
| Message gate | `OutputGate.gate(...)` | the shared `HumanOutputGate` instance the notifier owns |
| Action gate | `ApprovalGate.gate_or_execute(...)` | the shared `DraftApprovalService` |
| Send hook | `deferred_send(action) -> str` | the gated Slack-post executor, invoked only after approval |

The `Task` and `GoalActivity` dataclasses are the minimal projection the claw
needs; the adapter normalizes the tracker's native shape into them so the claw
stays tracker-agnostic.

## Scheduler-tick integration note (NOT wired here)

This is additive only. The scheduler is **not** edited. When the PM claw is
wired (in a separate change that owns the scheduler), a tick would:

```python
# once per stand-up window, per goal-enabled org:
report = run_pm_claw(
    org_id=org_id,
    channel=pm_channel_for(org_id),
    task_reader=taiga_task_reader,          # real adapter (TODO above)
    goal_event_reader=goal_events_reader,   # real adapter (TODO above)
    output_gate=shared_output_gate,         # the HumanOutputGate already on the notifier path
    approval_gate=DraftApprovalService(notifier=slack_notifier),
    deferred_send=gated_slack_post_executor,
    instance_id=instance_id,
)
# nothing to send here: the message is deferred into the digest and the SEND is
# gated. The existing flush at is_standup_hour() (see docs/OUTPUT_GATE.md) emits
# the single daily stand-up.
```

The flush itself is the output gate's existing responsibility (`flush_daily_digest`
at `is_standup_hour`), already documented in `docs/OUTPUT_GATE.md`. The PM claw
adds no clock, no daemon, no new send path.

## Pieces

| Piece | File |
|---|---|
| Claw + config + assessment + report | `backend/src/services/pm_claw.py` |
| Tests (fakes only) | `backend/tests/test_pm_claw.py` |

No migration, no new table: the claw owns no durable state. Tasks/deadlines live
in the tracker; goal activity lives in `goal_events`; gate state is the output
gate's transient, GC'd state. The claw is stateless between passes.

## Tests

`backend/tests/test_pm_claw.py` is pure Python (no Taiga/Slack/abra/DB). It
injects fake readers and a fake ACTION gate, and uses the **real**
`HumanOutputGate` (fake crystallizer + frozen clock) to prove composition:

- overdue / unassigned / missing-deadline detection
- off-track goals flagged (stale-vs-cadence and never-active)
- multiple goals collapse into ONE stand-up via the output gate
- nothing sent directly: the SEND is gated and the message deferred
- empty / clean project = quiet no-op (nothing queued, nothing gated)

Run: `python -m pytest tests/test_pm_claw.py -q` from `backend/`.
