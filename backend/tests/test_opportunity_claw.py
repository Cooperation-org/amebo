"""
Tests for the opportunity (prioritization) claw.

Mirrors test_pm_claw's discipline: the pure logic (candidate selection, ranking)
is tested directly, and the entry point is tested with injected fakes so no real
Taiga / abra / model calls happen. The key invariants:

  - opportunities = unassigned AND open tasks (nothing else)
  - no rubric  -> the claw stays silent and ranks nothing (no invented order)
  - the claw NEVER sends directly; outbound goes through the gates
  - the cheap-model Scorer is an injection seam (a fake here)
"""

from datetime import datetime, timezone

import pytest

from src.services.opportunity_claw import (
    AnthropicScorer,
    OpportunityClawConfig,
    Rubric,
    RubricCriterion,
    ScoredOpportunity,
    rank,
    run_opportunity_claw,
    select_candidates,
)
from src.services.pm_claw import Task


NOW = datetime(2026, 6, 14, tzinfo=timezone.utc)


# --- fakes ------------------------------------------------------------------


class FakeTaskReader:
    def __init__(self, tasks):
        self._tasks = tasks

    def list_tasks(self, *, org_id):
        return self._tasks


class FakeRubricReader:
    def __init__(self, rubric):
        self._rubric = rubric

    def get_rubric(self, *, org_id):
        return self._rubric


class FakeScorer:
    """Scores by a dict {task_id: score}; default 0."""

    def __init__(self, scores):
        self._scores = scores
        self.called_with = None

    def score(self, candidates, rubric):
        self.called_with = list(candidates)
        return [
            ScoredOpportunity(
                task_id=t.id, title=t.title,
                score=self._scores.get(t.id, 0.0), rationale="fake",
            )
            for t in candidates
        ]


class RecordingOutputGate:
    def __init__(self):
        self.calls = []

    def gate(self, message, *, channel, thread_ts=None, urgency="normal", goal_id=None):
        self.calls.append({"message": message, "channel": channel, "urgency": urgency})
        return {"action": "deferred"}


class RecordingApprovalGate:
    def __init__(self):
        self.calls = []

    def gate_or_execute(self, org_id, action_type, acting_identity, executor,
                        target=None, payload=None, preview=None,
                        instance_id=None, goal_id=None):
        # default-deny: never call the executor (would be the send)
        self.calls.append({"action_type": action_type, "target": target,
                           "preview": preview, "payload": payload})
        return {"status": "pending_approval"}


def _rubric():
    return Rubric(
        org_id=1, name="impact-rubric",
        criteria=(RubricCriterion("impact", 2.0, "real-world benefit"),),
    )


def _task(id, title, assignee=None, status="open"):
    return Task(id=id, title=title, status=status, assignee=assignee)


# --- pure: candidate selection ---------------------------------------------


def test_select_candidates_keeps_only_unassigned_open():
    cfg = OpportunityClawConfig()
    tasks = [
        _task("a", "unassigned open"),                      # ✓ opportunity
        _task("b", "assigned", assignee="golda"),           # ✗ owned
        _task("c", "done", status="done"),                  # ✗ finished
        _task("d", "closed", status="Closed"),              # ✗ finished (case)
        _task("e", "also open"),                            # ✓ opportunity
    ]
    out = select_candidates(tasks, cfg)
    assert [t.id for t in out] == ["a", "e"]


def test_blank_assignee_string_counts_as_unassigned():
    cfg = OpportunityClawConfig()
    out = select_candidates([_task("a", "x", assignee="   ")], cfg)
    assert [t.id for t in out] == ["a"]


# --- pure: ranking ----------------------------------------------------------


def test_rank_orders_desc_and_stamps_rank():
    scored = [
        ScoredOpportunity("a", "A", 10),
        ScoredOpportunity("b", "B", 90),
        ScoredOpportunity("c", "C", 50),
    ]
    ranked = rank(scored)
    assert [s.task_id for s in ranked] == ["b", "c", "a"]
    assert [s.rank for s in ranked] == [1, 2, 3]


def test_rank_is_stable_on_ties():
    scored = [
        ScoredOpportunity("a", "A", 50),
        ScoredOpportunity("b", "B", 50),
    ]
    ranked = rank(scored)
    assert [s.task_id for s in ranked] == ["a", "b"]  # input order preserved


# --- entry point ------------------------------------------------------------


def test_no_candidates_is_quiet():
    report = run_opportunity_claw(
        org_id=1, channel="slack:#x",
        task_reader=FakeTaskReader([_task("b", "owned", assignee="g")]),
        rubric_reader=FakeRubricReader(_rubric()),
        scorer=FakeScorer({}),
        output_gate=RecordingOutputGate(),
        now=NOW,
    )
    assert report.is_quiet
    assert not report.message_queued
    assert "no unassigned" in report.note


def test_no_rubric_ranks_nothing():
    out_gate = RecordingOutputGate()
    report = run_opportunity_claw(
        org_id=1, channel="slack:#x",
        task_reader=FakeTaskReader([_task("a", "open opp")]),
        rubric_reader=FakeRubricReader(None),   # no rubric
        scorer=FakeScorer({"a": 99}),
        output_gate=out_gate,
        now=NOW,
    )
    assert report.is_quiet
    assert not report.message_queued
    assert out_gate.calls == []                 # nothing queued
    assert "no rubric" in report.note


def test_empty_rubric_ranks_nothing():
    empty = Rubric(org_id=1, name="empty", criteria=())
    report = run_opportunity_claw(
        org_id=1, channel="slack:#x",
        task_reader=FakeTaskReader([_task("a", "open opp")]),
        rubric_reader=FakeRubricReader(empty),
        scorer=FakeScorer({"a": 99}),
        output_gate=RecordingOutputGate(),
        now=NOW,
    )
    assert report.is_quiet
    assert "no rubric" in report.note


def test_ranks_and_routes_through_gates_without_sending():
    out_gate = RecordingOutputGate()
    approval = RecordingApprovalGate()
    tasks = [_task("a", "low"), _task("b", "high"), _task("c", "mid")]
    report = run_opportunity_claw(
        org_id=1, channel="slack:#steering",
        task_reader=FakeTaskReader(tasks),
        rubric_reader=FakeRubricReader(_rubric()),
        scorer=FakeScorer({"a": 10, "b": 90, "c": 50}),
        output_gate=out_gate,
        approval_gate=approval,
        now=NOW,
    )
    # ranked best-first
    assert [s.task_id for s in report.ranked] == ["b", "c", "a"]
    # claw never sends directly; it queued one message + one gated action
    assert report.sent_directly is False
    assert report.message_queued is True
    assert len(out_gate.calls) == 1
    assert out_gate.calls[0]["urgency"] == "normal"
    assert len(approval.calls) == 1
    assert approval.calls[0]["action_type"] == "slack_post"   # outbound → gated
    assert "impact-rubric" in report.draft_text


def test_shortlist_and_overflow_are_reported_not_dropped():
    cfg = OpportunityClawConfig(max_candidates=2, shortlist_size=1)
    tasks = [_task("a", "A"), _task("b", "B"), _task("c", "C")]
    scorer = FakeScorer({"a": 30, "b": 20})  # only first 2 scored
    report = run_opportunity_claw(
        org_id=1, channel="slack:#x",
        task_reader=FakeTaskReader(tasks),
        rubric_reader=FakeRubricReader(_rubric()),
        scorer=scorer,
        output_gate=RecordingOutputGate(),
        config=cfg,
        now=NOW,
    )
    assert report.candidate_count == 3
    assert report.scored_count == 2
    assert report.overflow == 1
    assert len(scorer.called_with) == 2          # cap respected
    assert len(report.ranked) == 1               # shortlist respected
    assert "+1 more" in report.draft_text        # overflow surfaced, not hidden


# --- the cheap-model adapter degrades, never crashes ------------------------


def test_anthropic_scorer_falls_back_without_client():
    scorer = AnthropicScorer(anthropic_client=None)
    # No real API key in test env → client None → deterministic fallback.
    if scorer.client is not None:
        pytest.skip("ANTHROPIC_API_KEY present; fallback path not exercised")
    tasks = [_task("a", "A"), _task("b", "B")]
    scored = scorer.score(tasks, _rubric())
    assert [s.task_id for s in scored] == ["a", "b"]
    assert all("order preserved" in s.rationale for s in scored)
    # fallback preserves input order after rank()
    assert [s.task_id for s in rank(scored)] == ["a", "b"]
