"""
PM claw — the project-management claw.

Strategic purpose (see docs/PM_CLAW.md, docs/BOUNDARIES.md, docs/ORGS_GOALS_CLAW.md):
Amebo "leans on the task tracker as the heartbeat" — the canonical task list and
deadlines live in Taiga, not in Amebo. This claw is the agency layer over that
heartbeat: once a day it reads project state (tasks + recent goal activity),
ASSESSES it (overdue work, missing deadlines/assignees, goals drifting off
their cadence), and reports ONE concise stand-up that covers ALL goals at once.

It is ADDITIVE and composes with the two existing gates instead of reinventing
them:

  - human-output gate (MESSAGE gate, ``human_output_gate.HumanOutputGate``):
    the stand-up is DEFERRED into the channel's daily digest and flushed as ONE
    crystallized message covering every goal at the stand-up hour. The claw
    never sends one message per goal and never floods the channel. We reuse the
    gate's batching/crystallize/thread-prefer machinery wholesale.

  - draft-approval gate (ACTION gate, ``draft_approval_service``): a Slack post
    is an outbound action, so the actual SEND of the stand-up is an action that
    must be approved by a human first (default-deny). The claw itself performs
    NO direct side effect: it returns a structured report and queues a
    gated/deferred message. Nothing leaves the process here.

Boundaries (docs/BOUNDARIES.md): Amebo owns no task list and no deadlines. It
READS them from the tracker through an injected ``TaskReader`` and reads recent
activity through an injected ``GoalEventReader`` (goal_events is the in-flight
audit Amebo does own). Both are Protocols so the real adapters bind to the tool
layer / goal_events while tests inject fakes — no real Taiga/Slack/abra calls
in this module.

Additive: this provides the claw as a function the scheduler WOULD call on a
tick. It does NOT wire the scheduler, edit the registry, or rewire any send
path. Integration seam is documented in docs/PM_CLAW.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence

logger = logging.getLogger(__name__)


# ===========================================================================
# Config — every knob here, defaults documented, no magic numbers inline.
# ===========================================================================


@dataclass(frozen=True)
class PmClawConfig:
    """
    Tunables for the assessment pass. Defaults are conservative ("a quiet,
    useful PM"). Override at construction; never hardcode a number in the logic.
    """

    # A goal with no recorded activity within this window is flagged "off
    # track" UNLESS its own cadence (see ``cadence_days`` resolution below)
    # says a longer gap is fine. This is the fallback when a goal declares no
    # cadence of its own.
    default_stale_after_days: int = 7

    # A task whose due date is within this many days (and not done) is surfaced
    # as "due soon" so the stand-up can warn before it slips, not only after.
    due_soon_within_days: int = 2

    # Task statuses that mean "this is finished, stop tracking it". Compared
    # case-insensitively. Anything else counts as open/in-flight.
    done_statuses: frozenset = frozenset({"done", "closed", "completed", "resolved"})

    def __post_init__(self) -> None:
        if self.default_stale_after_days < 0:
            raise ValueError("default_stale_after_days must be >= 0")
        if self.due_soon_within_days < 0:
            raise ValueError("due_soon_within_days must be >= 0")


# ===========================================================================
# Injection seams — the claw depends on Protocols, never on a concrete tool.
# Real adapters bind to the tool layer / goal_events; tests inject fakes.
# ===========================================================================


@dataclass(frozen=True)
class Task:
    """
    One task as the claw needs to see it. The minimal projection of a tracker
    row (Taiga story/task, etc.) — id, title, status, assignee, due_date.

    ``due_date`` is a timezone-aware ``datetime`` (or None when the task has no
    deadline). The adapter is responsible for normalizing the tracker's native
    representation into this shape; the claw stays tracker-agnostic.
    """

    id: str
    title: str
    status: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[datetime] = None
    # Which goal this task rolls up under, if the tracker/adapter knows. When
    # None the task is counted at the project level but not under any goal.
    goal_id: Optional[str] = None


class TaskReader(Protocol):
    """
    Reads the org's tasks from the system of record (Taiga via the tool layer).
    The claw NEVER imports a tracker; the adapter passes the projection in.

    TODO(adapter): the real implementation wraps the ``mcp_taiga`` tool (see
    src/tools/registry.py) — list the org's project tasks and map each row to a
    ``Task``. It runs under the org's team-scoped service credential
    (BOUNDARIES.md "service / team authority"), never a god-token. Until that
    adapter lands, tests inject a fake reader.
    """

    def list_tasks(self, *, org_id: int) -> Sequence[Task]:
        """Return the org's current tasks (any status). Empty sequence is a
        valid, common answer (a clean or brand-new project)."""
        ...


@dataclass(frozen=True)
class GoalActivity:
    """
    Recent-activity summary for one goal, distilled from goal_events. The claw
    only needs to know which goals exist, how to name/cadence them, and when
    each last did something — not the full event stream.

    ``last_activity_at`` is timezone-aware (or None when the goal has never
    recorded an event). ``cadence_days`` is the goal's own freshness
    expectation when it declares one (e.g. a daily cron goal → 1); None means
    "use the config default".
    """

    goal_id: str
    title: str
    last_activity_at: Optional[datetime] = None
    cadence_days: Optional[int] = None


class GoalEventReader(Protocol):
    """
    Reads recent goal activity for an org. The claw uses this to judge whether a
    goal is drifting (no recent activity relative to its cadence/target).

    TODO(adapter): the real implementation reads goal_events via GoalRepo
    (``list_for_org`` for the goal set + ``list_events`` for the latest event
    timestamp per goal) and derives ``cadence_days`` from each goal's
    ``trigger_config`` (a cron expression's period) or ``target_criteria``.
    goal_events is in-flight state Amebo DOES own (BOUNDARIES.md), so this read
    stays inside Amebo. Tests inject a fake reader.
    """

    def recent_activity(self, *, org_id: int) -> Sequence[GoalActivity]:
        """Return one ``GoalActivity`` per active goal for the org."""
        ...


# A function that runs one message through the human-output gate and returns
# its decision. This is exactly ``HumanOutputGate.gate`` — typed structurally
# so the claw never imports the gate class, only depends on its call shape.
# (channel/goal_id/urgency keyword args mirror the real gate.)
class OutputGate(Protocol):
    def gate(
        self,
        message: str,
        *,
        channel: str,
        thread_ts: Optional[str] = None,
        urgency: str = "normal",
        goal_id: Optional[str] = None,
    ) -> Any:
        ...


# The action gate the claw routes the outbound SEND through. Structurally typed
# to ``DraftApprovalService.gate_or_execute`` so a Slack post is held for human
# approval (default-deny) rather than sent by the claw. The claw never executes;
# the executor it passes is the deferred-send hook, invoked only on approval.
class ApprovalGate(Protocol):
    def gate_or_execute(
        self,
        org_id: int,
        action_type: str,
        acting_identity: str,
        executor: Callable[[Dict[str, Any]], str],
        target: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        preview: Optional[str] = None,
        instance_id: Optional[int] = None,
        goal_id: Optional[str] = None,
    ) -> Any:
        ...


# ===========================================================================
# Structured report — what the claw assessed (returned to the caller).
# ===========================================================================


class Flag(str, Enum):
    """A single thing the PM claw noticed worth a human's attention."""

    OVERDUE = "overdue"                  # task past its due date, not done
    DUE_SOON = "due_soon"                # task due within the warning window
    NO_DEADLINE = "no_deadline"          # open task with no due date set
    NO_ASSIGNEE = "no_assignee"          # open task with nobody on it
    GOAL_OFF_TRACK = "goal_off_track"    # goal stale vs its cadence/target


@dataclass
class FlagItem:
    """One raised flag, with enough context to render a stand-up line and to
    let a human jump to the underlying task/goal."""

    flag: Flag
    subject_id: str                      # task id or goal id
    subject_title: str
    detail: str = ""                     # human-readable specifics
    goal_id: Optional[str] = None        # rollup key when known


@dataclass
class GoalRollup:
    """Per-goal summary line for the stand-up: counts + the goal's own flags."""

    goal_id: str
    title: str
    open_tasks: int = 0
    overdue: int = 0
    unassigned: int = 0
    no_deadline: int = 0
    off_track: bool = False
    flags: List[FlagItem] = field(default_factory=list)


@dataclass
class StandupReport:
    """
    The structured result of one PM-claw pass. The caller gets the full
    assessment (so it is queryable / testable) regardless of what the gates
    decided to do with the message.

    ``message_queued`` is True when a (deferred or gated) stand-up message was
    handed to the gates; ``sent_directly`` is ALWAYS False — the claw never
    sends. ``gate_decision`` / ``approval_result`` carry whatever the gates
    returned, for the caller to act on.
    """

    org_id: int
    channel: str
    generated_at: datetime
    per_goal: List[GoalRollup] = field(default_factory=list)
    flags: List[FlagItem] = field(default_factory=list)
    standup_text: Optional[str] = None
    message_queued: bool = False
    sent_directly: bool = False          # invariant: the claw never sends
    gate_decision: Any = None            # the human-output GateDecision
    approval_result: Any = None          # the draft-approval GateResult

    @property
    def is_quiet(self) -> bool:
        """True when there is nothing worth a stand-up (clean / empty project).
        A quiet pass queues no message — the claw stays silent."""
        return not self.flags and all(g.open_tasks == 0 for g in self.per_goal)


# ===========================================================================
# The claw entry point
# ===========================================================================


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize a datetime to timezone-aware UTC so comparisons are safe.
    Naive datetimes from a tracker/DB are assumed UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _is_done(status: Optional[str], cfg: PmClawConfig) -> bool:
    return (status or "").strip().lower() in cfg.done_statuses


def assess(
    tasks: Sequence[Task],
    activity: Sequence[GoalActivity],
    *,
    config: PmClawConfig,
    now: datetime,
) -> tuple[List[GoalRollup], List[FlagItem]]:
    """
    Pure assessment over the projections. No I/O, no gates — just the rules:

      - overdue:      open task whose due_date < now.
      - due_soon:     open task whose due_date is within due_soon_within_days.
      - no_deadline:  open task with no due_date.
      - no_assignee:  open task with no assignee.
      - off_track:    goal whose last activity is older than its cadence
                      (cadence_days, else default_stale_after_days), or which
                      has never recorded any activity.

    Returns (per-goal rollups, flat flag list). Separated out so it is trivially
    unit-testable with fakes and carries no dependency on the gates.
    """
    now = _aware(now) or datetime.now(timezone.utc)

    # Seed a rollup for every known goal so a goal with zero tasks still shows.
    rollups: Dict[str, GoalRollup] = {
        a.goal_id: GoalRollup(goal_id=a.goal_id, title=a.title) for a in activity
    }
    flags: List[FlagItem] = []

    def rollup_for(goal_id: Optional[str]) -> Optional[GoalRollup]:
        if goal_id is None:
            return None
        r = rollups.get(goal_id)
        if r is None:
            # Task references a goal we have no activity row for; still track it.
            r = GoalRollup(goal_id=goal_id, title=goal_id)
            rollups[goal_id] = r
        return r

    # --- task-level flags ---------------------------------------------------
    for t in tasks:
        if _is_done(t.status, config):
            continue  # finished work is not surfaced

        r = rollup_for(t.goal_id)
        if r is not None:
            r.open_tasks += 1

        due = _aware(t.due_date)
        if due is None:
            item = FlagItem(Flag.NO_DEADLINE, t.id, t.title,
                            "open task has no due date", goal_id=t.goal_id)
            flags.append(item)
            if r is not None:
                r.no_deadline += 1
                r.flags.append(item)
        else:
            if due < now:
                overdue_by = now - due
                item = FlagItem(
                    Flag.OVERDUE, t.id, t.title,
                    f"overdue by {overdue_by.days}d", goal_id=t.goal_id,
                )
                flags.append(item)
                if r is not None:
                    r.overdue += 1
                    r.flags.append(item)
            elif (due - now).days <= config.due_soon_within_days:
                item = FlagItem(
                    Flag.DUE_SOON, t.id, t.title,
                    f"due in {(due - now).days}d", goal_id=t.goal_id,
                )
                flags.append(item)
                if r is not None:
                    r.flags.append(item)

        if not (t.assignee or "").strip():
            item = FlagItem(Flag.NO_ASSIGNEE, t.id, t.title,
                            "no assignee", goal_id=t.goal_id)
            flags.append(item)
            if r is not None:
                r.unassigned += 1
                r.flags.append(item)

    # --- goal-level flags (off-track via cadence) ---------------------------
    for a in activity:
        r = rollups[a.goal_id]
        horizon_days = (
            a.cadence_days if a.cadence_days is not None
            else config.default_stale_after_days
        )
        last = _aware(a.last_activity_at)
        off = False
        if last is None:
            off = True
            detail = "no recorded activity yet"
        elif (now - last).days > horizon_days:
            off = True
            detail = f"no activity in {(now - last).days}d (cadence {horizon_days}d)"
        if off:
            r.off_track = True
            item = FlagItem(Flag.GOAL_OFF_TRACK, a.goal_id, a.title,
                            detail, goal_id=a.goal_id)
            flags.append(item)
            r.flags.append(item)

    return list(rollups.values()), flags


def _render_goal_line(r: GoalRollup) -> str:
    """One compact line per goal. The output gate's crystallizer collapses the
    whole batch into the final stand-up; this just makes each goal legible."""
    bits: List[str] = []
    if r.open_tasks:
        bits.append(f"{r.open_tasks} open")
    if r.overdue:
        bits.append(f"{r.overdue} overdue")
    if r.unassigned:
        bits.append(f"{r.unassigned} unassigned")
    if r.no_deadline:
        bits.append(f"{r.no_deadline} no-deadline")
    if r.off_track:
        bits.append("off-track")
    status = ", ".join(bits) if bits else "on track"
    return f"{r.title}: {status}"


def run_pm_claw(
    *,
    org_id: int,
    channel: str,
    task_reader: TaskReader,
    goal_event_reader: GoalEventReader,
    output_gate: OutputGate,
    approval_gate: Optional[ApprovalGate] = None,
    config: Optional[PmClawConfig] = None,
    acting_identity: Optional[str] = None,
    instance_id: Optional[int] = None,
    deferred_send: Optional[Callable[[Dict[str, Any]], str]] = None,
    now: Optional[datetime] = None,
) -> StandupReport:
    """
    Run one PM-claw pass for an org and queue ONE daily stand-up covering ALL
    goals. The claw performs NO direct side effect — it returns the assessment
    and routes the message through the gates.

    Flow:
      1. READ project state via the injected Protocols (tasks + goal activity).
      2. ASSESS (overdue / due-soon / no-deadline / no-assignee / off-track).
      3. COMPOSE one stand-up body covering all goals.
      4. ROUTE the SEND through the draft-approval (ACTION) gate — a Slack post
         is outbound, so it is held for human approval (default-deny). The
         executor passed is the deferred-send hook; it runs ONLY on approval.
      5. DEFER the message body into the human-output (MESSAGE) gate's daily
         digest, so multiple passes/goals collapse into ONE message flushed at
         the stand-up hour. The claw never SENDs now.

    A quiet project (no open tasks, no flags) queues nothing — the claw stays
    silent (a useful PM does not post "nothing to report").

    Parameters mark their injection seams; real adapters carry TODOs above.
    """
    cfg = config or PmClawConfig()
    when = _aware(now) or datetime.now(timezone.utc)
    acting = acting_identity or f"amebo:org-{org_id}"

    # (1) READ — injected; real adapters call the tool layer / goal_events.
    tasks = list(task_reader.list_tasks(org_id=org_id))
    activity = list(goal_event_reader.recent_activity(org_id=org_id))

    # (2) ASSESS — pure, testable.
    per_goal, flags = assess(tasks, activity, config=cfg, now=when)

    report = StandupReport(
        org_id=org_id,
        channel=channel,
        generated_at=when,
        per_goal=per_goal,
        flags=flags,
    )

    # Quiet project → stay silent. Nothing queued, nothing gated.
    if report.is_quiet:
        logger.debug("[pm-claw] org=%s channel=%s: quiet, nothing to report",
                     org_id, channel)
        return report

    # (3) COMPOSE one body covering ALL goals. The output gate crystallizes the
    # batch into the final stand-up; this is the pre-crystallize material.
    goal_lines = [_render_goal_line(r) for r in per_goal] or ["(no goals tracked)"]
    flag_count = len(flags)
    standup_text = (
        f"Stand-up ({when:%Y-%m-%d}): {flag_count} item(s) need attention.\n"
        + "\n".join(goal_lines)
    )
    report.standup_text = standup_text

    # (4) ACTION gate — the SEND of a Slack post is outbound; hold for approval.
    # The claw does NOT execute: it passes a deferred-send hook as the executor,
    # invoked only after a human approves (FREE actions would run it now, but a
    # slack_post is GATED by default-deny, so this never runs inside the claw).
    if approval_gate is not None:
        def _executor(_action: Dict[str, Any]) -> str:
            if deferred_send is not None:
                return deferred_send(_action)
            # No real sender wired yet — surface that, never send silently.
            # TODO(send): bind to the gated Slack post executor on approval.
            logger.info("[pm-claw] approved stand-up for org=%s has no sender wired",
                        org_id)
            return "[pm-claw] approved; no sender wired"

        approval_result = approval_gate.gate_or_execute(
            org_id=org_id,
            action_type="slack_post",          # outbound → GATED (default-deny)
            acting_identity=acting,
            executor=_executor,
            target=channel,
            payload={"text": standup_text, "notify_channel": channel},
            preview=f"Daily PM stand-up: {flag_count} flag(s) across "
                    f"{len(per_goal)} goal(s)",
            instance_id=instance_id,
        )
        report.approval_result = approval_result

    # (5) MESSAGE gate — DEFER the body into the channel's daily digest so all
    # goals collapse into ONE stand-up at the flush hour. We pass urgency
    # 'normal' so the gate batches it; the claw never forces a top-level send.
    # goal_id is intentionally omitted: this single message spans ALL goals.
    decision = output_gate.gate(standup_text, channel=channel, urgency="normal")
    report.gate_decision = decision
    report.message_queued = True
    # Invariant, asserted explicitly: the claw itself never sends.
    report.sent_directly = False

    logger.info(
        "[pm-claw] org=%s channel=%s: queued stand-up, %d flag(s), %d goal(s)",
        org_id, channel, flag_count, len(per_goal),
    )
    return report
