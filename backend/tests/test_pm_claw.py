"""
Unit tests for the PM claw (src/services/pm_claw.py).

Pure Python — no real Taiga, no Slack, no abra, no DB. The TaskReader and
GoalEventReader Protocols are satisfied by fakes; the human-output gate is the
REAL gate (with a fake crystallizer + frozen clock, exactly as its own tests do)
so we prove the claw composes with it; the draft-approval ACTION gate is a fake
recorder so we prove the SEND is held for approval and never executed by the claw.

Covered (per spec):
  - overdue / unassigned / missing-deadline detection.
  - multiple goals collapse into ONE stand-up via the output gate (not one per goal).
  - off-track goals flagged (stale vs cadence; never-active goal).
  - nothing sent directly: the claw defers/gates, never sends.
  - empty project = clean no-op / quiet (nothing queued, nothing gated).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.services import human_output_gate as hog
from src.services.human_output_gate import (
    Disposition,
    HumanOutputGate,
    OutputGateConfig,
)
from src.services.pm_claw import (
    Flag,
    GoalActivity,
    PmClawConfig,
    StandupReport,
    Task,
    assess,
    run_pm_claw,
)


NOW = datetime(2026, 6, 6, 9, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeTaskReader:
    """Satisfies the TaskReader Protocol; returns a canned task list."""

    def __init__(self, tasks):
        self._tasks = list(tasks)
        self.calls: list[int] = []

    def list_tasks(self, *, org_id: int):
        self.calls.append(org_id)
        return self._tasks


class FakeGoalEventReader:
    """Satisfies the GoalEventReader Protocol; returns canned goal activity."""

    def __init__(self, activity):
        self._activity = list(activity)
        self.calls: list[int] = []

    def recent_activity(self, *, org_id: int):
        self.calls.append(org_id)
        return self._activity


class RecordingApprovalGate:
    """
    Fake ACTION gate. Records the gate_or_execute call and, like the real
    default-deny gate for an outbound slack_post, holds it for approval WITHOUT
    running the executor. Asserts the claw never causes a direct send.
    """

    def __init__(self):
        self.calls: list[dict] = []
        self.executor_ran = False

    def gate_or_execute(self, org_id, action_type, acting_identity, executor,
                        target=None, payload=None, preview=None,
                        instance_id=None, goal_id=None):
        # Capture the executor but DO NOT run it — slack_post is gated.
        self._executor = executor
        self.calls.append({
            "org_id": org_id, "action_type": action_type,
            "acting_identity": acting_identity, "target": target,
            "payload": payload, "preview": preview, "instance_id": instance_id,
        })

        class _Result:
            gated = True
            executed = False
            result = None
            pending_action = {"id": "fake-pending-1"}
        return _Result()


class RecordingCrystallizer:
    """Deterministic, inspectable join (does not trim) — same shape the output
    gate's own tests use, so 'all goals in one message' is visible."""

    def __init__(self):
        self.calls: list[dict] = []

    def crystallize(self, items, *, in_thread, receiver=None):
        self.calls.append({"items": list(items), "in_thread": in_thread})
        return " || ".join(i.strip() for i in items if i and i.strip())


@pytest.fixture
def clock(monkeypatch):
    """Freeze the output gate's clock so its rate/dedup windows are deterministic."""
    class _Clock:
        t = NOW.timestamp()

        def __call__(self):
            return self.t
    c = _Clock()
    monkeypatch.setattr(hog, "_now", c)
    return c


@pytest.fixture
def crystal():
    return RecordingCrystallizer()


# --------------------------------------------------------------------------- #
# assess(): pure detection
# --------------------------------------------------------------------------- #


def _flags_of(items, flag):
    return [f for f in items if f.flag is flag]


def test_assess_detects_overdue_unassigned_and_missing_deadline():
    cfg = PmClawConfig()
    tasks = [
        Task(id="1", title="Ship API", status="in progress", assignee="amy",
             due_date=NOW - timedelta(days=3), goal_id="G1"),        # overdue
        Task(id="2", title="Write docs", status="todo", assignee=None,
             due_date=NOW + timedelta(days=10), goal_id="G1"),       # unassigned
        Task(id="3", title="Triage bugs", status="todo", assignee="bob",
             due_date=None, goal_id="G1"),                           # no deadline
        Task(id="4", title="Already shipped", status="done", assignee=None,
             due_date=NOW - timedelta(days=9), goal_id="G1"),        # ignored (done)
    ]
    activity = [GoalActivity(goal_id="G1", title="Launch", last_activity_at=NOW)]

    per_goal, flags = assess(tasks, activity, config=cfg, now=NOW)

    assert len(_flags_of(flags, Flag.OVERDUE)) == 1
    assert _flags_of(flags, Flag.OVERDUE)[0].subject_id == "1"
    assert len(_flags_of(flags, Flag.NO_ASSIGNEE)) == 1
    assert _flags_of(flags, Flag.NO_ASSIGNEE)[0].subject_id == "2"
    assert len(_flags_of(flags, Flag.NO_DEADLINE)) == 1
    assert _flags_of(flags, Flag.NO_DEADLINE)[0].subject_id == "3"

    # The done task contributes no flags and no open count.
    g1 = next(r for r in per_goal if r.goal_id == "G1")
    assert g1.open_tasks == 3
    assert g1.overdue == 1
    assert g1.unassigned == 1
    assert g1.no_deadline == 1


def test_assess_flags_off_track_goals_by_cadence_and_never_active():
    cfg = PmClawConfig(default_stale_after_days=7)
    activity = [
        # daily-cadence goal idle 3 days → off track (3 > 1)
        GoalActivity(goal_id="A", title="Daily digest",
                     last_activity_at=NOW - timedelta(days=3), cadence_days=1),
        # default-cadence goal idle 2 days → on track (2 <= 7)
        GoalActivity(goal_id="B", title="Slow burn",
                     last_activity_at=NOW - timedelta(days=2)),
        # never recorded any activity → off track
        GoalActivity(goal_id="C", title="Brand new", last_activity_at=None),
    ]
    per_goal, flags = assess([], activity, config=cfg, now=NOW)

    off = {f.subject_id for f in _flags_of(flags, Flag.GOAL_OFF_TRACK)}
    assert off == {"A", "C"}
    assert next(r for r in per_goal if r.goal_id == "A").off_track is True
    assert next(r for r in per_goal if r.goal_id == "B").off_track is False
    assert next(r for r in per_goal if r.goal_id == "C").off_track is True


# --------------------------------------------------------------------------- #
# run_pm_claw(): composition with the gates
# --------------------------------------------------------------------------- #


def test_multiple_goals_collapse_into_one_standup_via_output_gate(clock, crystal):
    # Force the output gate to DEFER (rate limit 0) so the message goes into the
    # daily digest and the stand-up flush proves the single-message contract.
    gate = HumanOutputGate(
        config=OutputGateConfig(max_msgs_per_channel=0, dedup_lookback=timedelta(0)),
        crystallizer=crystal,
    )
    approval = RecordingApprovalGate()

    tasks = [
        Task(id="1", title="A-task", status="todo", assignee=None,
             due_date=NOW - timedelta(days=1), goal_id="A"),
        Task(id="2", title="B-task", status="todo", assignee="bob",
             due_date=None, goal_id="B"),
    ]
    activity = [
        GoalActivity(goal_id="A", title="Goal A", last_activity_at=NOW),
        GoalActivity(goal_id="B", title="Goal B", last_activity_at=NOW),
        GoalActivity(goal_id="C", title="Goal C",
                     last_activity_at=NOW - timedelta(days=30)),  # off-track
    ]

    report = run_pm_claw(
        org_id=42,
        channel="#standup",
        task_reader=FakeTaskReader(tasks),
        goal_event_reader=FakeGoalEventReader(activity),
        output_gate=gate,
        approval_gate=approval,
        now=NOW,
    )

    # The claw deferred exactly ONE message into the digest (not one per goal).
    assert report.message_queued is True
    assert report.gate_decision.disposition is Disposition.DEFER
    assert gate.pending_digest_count("#standup") == 1

    # Flush the daily stand-up: ONE crystallized message covering ALL goals.
    sent: list[tuple] = []
    decision = gate.flush_daily_digest(
        "#standup", sender=lambda c, t, ts: sent.append((c, t, ts)) or True
    )
    assert len(sent) == 1
    one_text = sent[0][1]
    assert "Goal A" in one_text and "Goal B" in one_text and "Goal C" in one_text
    assert decision.disposition is Disposition.SEND


def test_nothing_is_sent_directly_send_is_gated_and_deferred(clock, crystal):
    gate = HumanOutputGate(
        config=OutputGateConfig(max_msgs_per_channel=0, dedup_lookback=timedelta(0)),
        crystallizer=crystal,
    )
    approval = RecordingApprovalGate()

    report = run_pm_claw(
        org_id=7,
        channel="#pm",
        task_reader=FakeTaskReader([
            Task(id="1", title="t", status="todo", assignee=None,
                 due_date=NOW - timedelta(days=2), goal_id="G"),
        ]),
        goal_event_reader=FakeGoalEventReader([
            GoalActivity(goal_id="G", title="G", last_activity_at=NOW),
        ]),
        output_gate=gate,
        approval_gate=approval,
        now=NOW,
    )

    # The SEND went through the ACTION gate as a slack_post and was held.
    assert len(approval.calls) == 1
    assert approval.calls[0]["action_type"] == "slack_post"
    assert approval.calls[0]["target"] == "#pm"
    assert approval.executor_ran is False        # claw never executes the send
    assert report.approval_result.gated is True
    # And the MESSAGE gate deferred it (nothing left the process).
    assert report.sent_directly is False
    assert report.gate_decision.disposition is Disposition.DEFER


def test_empty_project_is_quiet_no_op(clock, crystal):
    gate = HumanOutputGate(crystallizer=crystal)
    approval = RecordingApprovalGate()

    report = run_pm_claw(
        org_id=1,
        channel="#quiet",
        task_reader=FakeTaskReader([]),
        goal_event_reader=FakeGoalEventReader([]),
        output_gate=gate,
        approval_gate=approval,
        now=NOW,
    )

    assert isinstance(report, StandupReport)
    assert report.is_quiet is True
    assert report.message_queued is False
    assert report.standup_text is None
    assert gate.pending_digest_count("#quiet") == 0    # nothing queued
    assert approval.calls == []                          # nothing gated
    assert crystal.calls == []                           # gate never invoked


def test_clean_project_with_on_track_goal_is_quiet(clock, crystal):
    """A project with only done tasks and a fresh, on-track goal: no flags, no
    open tasks → the claw stays silent."""
    gate = HumanOutputGate(crystallizer=crystal)
    report = run_pm_claw(
        org_id=2,
        channel="#clean",
        task_reader=FakeTaskReader([
            Task(id="1", title="shipped", status="done", assignee="a",
                 due_date=NOW - timedelta(days=1), goal_id="G"),
        ]),
        goal_event_reader=FakeGoalEventReader([
            GoalActivity(goal_id="G", title="G", last_activity_at=NOW),
        ]),
        output_gate=gate,
        now=NOW,
    )
    assert report.is_quiet is True
    assert report.message_queued is False
    assert gate.pending_digest_count("#clean") == 0


def test_runs_without_approval_gate_still_defers_only(clock, crystal):
    """approval_gate is optional; without it the claw must still never send —
    the message is deferred through the output gate and nothing is executed."""
    gate = HumanOutputGate(
        config=OutputGateConfig(max_msgs_per_channel=0, dedup_lookback=timedelta(0)),
        crystallizer=crystal,
    )
    report = run_pm_claw(
        org_id=9,
        channel="#noapproval",
        task_reader=FakeTaskReader([
            Task(id="1", title="t", status="todo", assignee=None,
                 due_date=None, goal_id="G"),
        ]),
        goal_event_reader=FakeGoalEventReader([
            GoalActivity(goal_id="G", title="G", last_activity_at=NOW),
        ]),
        output_gate=gate,
        now=NOW,
    )
    assert report.approval_result is None
    assert report.sent_directly is False
    assert report.gate_decision.disposition is Disposition.DEFER


def test_readers_are_called_with_org_scope(clock, crystal):
    tr = FakeTaskReader([])
    gr = FakeGoalEventReader([])
    run_pm_claw(
        org_id=123,
        channel="#x",
        task_reader=tr,
        goal_event_reader=gr,
        output_gate=HumanOutputGate(crystallizer=crystal),
        now=NOW,
    )
    assert tr.calls == [123]
    assert gr.calls == [123]


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        PmClawConfig(default_stale_after_days=-1)
    with pytest.raises(ValueError):
        PmClawConfig(due_soon_within_days=-1)
