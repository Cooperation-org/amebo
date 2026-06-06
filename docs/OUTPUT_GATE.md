# Human-Output Gate

A guard that sits **before Amebo speaks to a human** and keeps the claw from
being a firehose. It is the message-side sibling of the draft-approval gate.

## Why

Amebo is "so noisy" in Slack. A useful colleague does not post constantly, does
not repeat itself, prefers a thread over a new top-level message, and can save
its updates for one daily stand-up instead of a running stream. This gate
enforces all of that, and it crystallizes hard (per `docs/CRYSTALLIZE.md`,
crystallizing is a core engine function) before anything reaches a human.

## The two gates compose (action gate vs message gate)

| | Draft-approval gate | Human-output gate (this) |
|---|---|---|
| Question | should this outbound ACTION happen at all? | is this human-facing MESSAGE concise, non-repetitive, within rate limits? |
| Decides | execute now / hold for human approval | SEND / DEFER to daily stand-up / SUPPRESS |
| File | `backend/src/services/draft_approval_service.py` | `backend/src/services/human_output_gate.py` |

They sit on the same notifier path and compose: the action gate decides whether
a thing happens; this gate decides whether/how to say it. A notification that
the action gate emits (e.g. "approval needed") is itself a human-facing message
and can be run through this gate too.

## Pieces

| Piece | File |
|---|---|
| Gate + config + crystallize seam + digest queue | `backend/src/services/human_output_gate.py` |
| GC policy adapter (transient state decay) | same file: `OutputGateGcPolicy`, `register_output_gate_gc` |
| Tests | `backend/tests/test_human_output_gate.py` |

No migration. All gate state is transient and in-memory with a TTL (see "State
and GC"); there is no table, so no migration 018 is needed.

## How it works

`gate(message, *, channel, thread_ts=None, urgency='normal', goal_id=None)`
returns a `GateDecision` whose `disposition` is one of:

- **SEND** — deliver now. `decision.text` is the crystallized body;
  `decision.thread_ts` is the thread to reply in (the gate prefers threads).
- **DEFER** — queued to the channel's daily stand-up; the notifier sends nothing
  now.
- **SUPPRESS** — dropped (a duplicate, or over-rate with nothing worth sending).

Steps, applied in order:

1. **dedup** — a message whose normalized fingerprint matches one sent to the
   same channel within `dedup_lookback` is SUPPRESSED.
2. **thread-preference** — if a `thread_ts` is supplied the gate stays in that
   thread (and adopts it as the channel's running thread); if none is supplied
   but the channel has a running thread, the message is forced into it rather
   than posting top-level. This is resolved before the rate limit because the
   rate limit governs only top-level posts; thread replies are preferred and
   cheap and never count toward (or are blocked by) the budget.
3. **rate-limit / over-noise** — at most `max_msgs_per_channel` top-level
   (non-thread, non-urgent) messages per `rate_window`. The next non-urgent
   top-level message is DEFERRED to the daily stand-up. `urgency='urgent'` and
   thread replies bypass this step.
4. **crystallize** — the message is distilled to the smallest output carrying
   the meaning, at the receiver's bandwidth (1-2 lines cold, more inside an open
   thread). Reuses the crystallize seam.
5. **decision** — SEND / DEFER / SUPPRESS as above.

**Urgent messages** bypass batching (they always SEND now) but STILL go through
dedup and crystallize: an urgent ping must not be a repeat and must still be
concise.

### Daily stand-up

Deferred messages accumulate in a per-channel digest queue. The scheduler calls
`flush_daily_digest(channel, sender=...)` when `is_standup_hour(current_hour)` is
true (the gate owns no clock/daemon). The flush crystallizes **all** queued
items into **one** stand-up message covering **all goals** (many goals collapse
into one concise message, not one per goal), sends it in the channel's running
thread when one exists, and clears the queue.

## Reusing crystallize

The gate depends on a `Crystallizer` Protocol (`crystallize(items, *, in_thread,
receiver)`), never on a concrete summarizer. `docs/CRYSTALLIZE.md` records that
the crystallize engine is a documented commitment, not yet a built function. So:

- **Real wiring** injects the crystallize-engine call into the gate's
  constructor when that engine lands.
- **Until then** a `_PassthroughCrystallizer` is used: it does NOT invent a
  summarization model (that would reinvent crystallize). It deterministically
  joins the pile and trims to the receiver bandwidth from CRYSTALLIZE.md (2 lines
  cold, expand in a thread), keeping the gate honest and offline-safe.
- **Tests** inject a fake crystallizer to assert ordering and batching without a
  model.

When the engine exists, wrap it as a `Crystallizer` and pass it in; no gate code
changes.

## State and GC

All gate state is transient operational state Amebo owns (BOUNDARIES.md "in
their head"): per-channel recent-message fingerprints (dedup), per-channel
top-level send timestamps (rate limit), and the deferred digest queue. It lives
in-memory with a TTL; nothing durable is stored, so there is no table and no
migration.

It is registered with the per-store GC via `register_output_gate_gc(gate)`,
which adds an `OutputGateGcPolicy` to the `state_decay` `default_registry`. The
existing `run_gc(...)` then decays idle-channel state alongside threads,
goal_events, and abra working memory. A channel with an undelivered stand-up is
never evicted. The notifier owner calls `register_output_gate_gc` once when
constructing the shared gate; the gate module imports nothing from `state_decay`
at load, so it stays additive and side-effect-free on import.

## The single notifier integration point

Additive-only: the live send path is **not** rewired. The one place to call the
gate is wherever Amebo is about to emit a human-facing message — the notifier
used by `GoalDispatcher` (its `_default_notifier` / the Slack adapter passed at
construction, `goal_dispatcher.Notifier = Callable[[str, str], bool]`). Wrap
that notifier:

```python
from src.services.human_output_gate import (
    HumanOutputGate, Disposition, register_output_gate_gc,
)

gate = HumanOutputGate()                 # inject config / real crystallizer here
register_output_gate_gc(gate)            # decay transient state via run_gc

def gated_notifier(channel: str, message: str) -> bool:
    decision = gate.gate(message, channel=channel)   # thread_ts/urgency/goal_id optional
    if decision.disposition is Disposition.SEND:
        return real_slack_send(channel, decision.text, thread_ts=decision.thread_ts)
    # DEFER  → queued for the daily stand-up; nothing sent now.
    # SUPPRESS → duplicate / over-noise; nothing sent.
    return True

dispatcher = GoalDispatcher(notifier=gated_notifier)
```

And on the scheduler tick, flush stand-ups at the configured hour:

```python
from datetime import datetime
if gate.is_standup_hour(datetime.now().hour):
    for channel in active_channels:
        gate.flush_daily_digest(channel, sender=real_slack_send_with_thread)
```

That is the entire integration. No change to `goal_dispatcher.py`, `main.py`,
`auth.py`, or `slack_oauth.py`.

## Config knobs

`OutputGateConfig` (all overridable; defaults documented here, never inline):

| Knob | Default | Meaning |
|---|---|---|
| `max_msgs_per_channel` | 5 | top-level non-urgent messages allowed per window |
| `rate_window` | 1 hour | the rate-limit window |
| `daily_standup_hour` | 9 | local hour (0-23) the scheduler flushes stand-ups |
| `dedup_lookback` | 24 hours | how far back a repeat is suppressed |
| `state_ttl` | 24 hours | idle-channel state GC horizon (must be ≥ longest lookback) |
