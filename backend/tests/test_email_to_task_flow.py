"""
Unit tests for the email-to-task flow (the flagship claw use case).

Pure Python — NO real CRM, NO real Taiga, NO real Slack, NO DB. Every external
dependency is injected as a fake:

  - FakeCrmReader      → returns a canned forwarded email (or None).
  - RecordingGate      → records create_pending_action calls instead of hitting
                         the pending_actions table; hands back fake ids.
  - RecordingTaskCreator / RecordingNotifier → would be the executors the gate
                         runs on approval; the flow must NEVER call them (it only
                         drafts), so the tests assert they stay untouched.
  - the real HumanOutputGate is used for the output-gate path (it is pure /
                         offline-safe), proving the Slack text passes through it.

Asserted (per spec):
  - a fake email → a DraftedTask + two GATED pending_actions (task-create,
    slack-notify); NO direct side effect (executors never called).
  - the channel comes from config (not hardcoded).
  - empty / no-email case is a clean no-op (no drafts, no executor calls).
  - the Slack notification passes through the output gate (and is withheld when
    the gate suppresses it as a duplicate).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.services.email_to_task_flow import (
    ACTION_CREATE_TASK,
    ACTION_SLACK_POST,
    DraftedTask,
    ForwardedEmail,
    process_latest_forwarded_email,
)
from src.services.human_output_gate import HumanOutputGate


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeCrmReader:
    """Returns a preset email (or None). Records the lookups it was asked for."""

    def __init__(self, email: Optional[ForwardedEmail]):
        self._email = email
        self.calls: List[Dict[str, Any]] = []

    def latest_forwarded_from(
        self, *, sender: str, org_id: int
    ) -> Optional[ForwardedEmail]:
        self.calls.append({"sender": sender, "org_id": org_id})
        return self._email


class RecordingGate:
    """Fake draft-approval gate: records create_pending_action calls and returns
    a fake row with a sequential id. No DB, no notification — just enough to
    prove the flow drafts (never executes)."""

    def __init__(self) -> None:
        self.created: List[Dict[str, Any]] = []
        self._next_id = 1

    def create_pending_action(
        self,
        org_id: int,
        action_type: str,
        acting_identity: str,
        target: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        preview: Optional[str] = None,
        instance_id: Optional[int] = None,
        goal_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        row = {
            "id": f"pa-{self._next_id}",
            "org_id": org_id,
            "action_type": action_type,
            "acting_identity": acting_identity,
            "target": target,
            "payload": payload,
            "preview": preview,
            "instance_id": instance_id,
            "goal_id": goal_id,
            "status": "pending",
        }
        self._next_id += 1
        self.created.append(row)
        return row


class RecordingTaskCreator:
    """Executor the gate would run AFTER approval. The flow must never call it."""

    def __init__(self) -> None:
        self.calls: List[DraftedTask] = []

    def create_task(self, task: DraftedTask) -> str:
        self.calls.append(task)
        return "task-created"


class RecordingNotifier:
    """Executor the gate would run AFTER approval. The flow must never call it."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, str]] = []

    def notify(self, channel: str, message: str) -> bool:
        self.calls.append({"channel": channel, "message": message})
        return True


def _email() -> ForwardedEmail:
    return ForwardedEmail(
        sender="partner@example.org",
        subject="Can we get the Q3 numbers by Friday?",
        body="Hi team, we need the Q3 revenue numbers for the board deck.",
        received_at="2026-06-06T10:00:00Z",
        source_url="https://crm.linkedtrust.us/web#id=42&model=mail.message",
        message_id="mail.message-42",
    )


SENDER = "partner@example.org"
CHANNEL = "#whats-cookin-ops"
ORG_ID = 7
ACTING = "amebo:whats-cookin"


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_email_produces_task_and_two_gated_drafts_no_side_effects():
    reader = FakeCrmReader(_email())
    gate = RecordingGate()
    creator = RecordingTaskCreator()
    notifier = RecordingNotifier()

    result = process_latest_forwarded_email(
        sender=SENDER,
        slack_channel=CHANNEL,
        org_id=ORG_ID,
        readers=reader,
        task_creator=creator,
        notifier=notifier,
        gate=gate,
        acting_identity=ACTING,
        instance_id=99,
        goal_id="goal-1",
    )

    # A task was crystallized from the email.
    assert result.drafted_task is not None
    assert result.drafted_task.title == "Can we get the Q3 numbers by Friday?"
    assert "partner@example.org" in result.drafted_task.description
    assert result.drafted_task.source_url == _email().source_url

    # Exactly two gated drafts: task-create then slack-notify.
    assert len(gate.created) == 2
    task_draft, slack_draft = gate.created
    assert task_draft["action_type"] == ACTION_CREATE_TASK
    assert slack_draft["action_type"] == ACTION_SLACK_POST

    # Both ids surfaced on the result, in queue order.
    assert result.task_pending_action_id == task_draft["id"]
    assert result.slack_pending_action_id == slack_draft["id"]
    assert result.pending_action_ids == [task_draft["id"], slack_draft["id"]]

    # NO direct side effect: the executors the gate runs on approval are never
    # called by the flow's draft step.
    assert creator.calls == []
    assert notifier.calls == []

    # Provenance is stamped on the drafts.
    assert task_draft["acting_identity"] == ACTING
    assert task_draft["goal_id"] == "goal-1"
    assert task_draft["instance_id"] == 99


def test_slack_channel_comes_from_config_not_hardcoded():
    reader = FakeCrmReader(_email())
    gate = RecordingGate()

    custom_channel = "#a-different-channel"
    result = process_latest_forwarded_email(
        sender=SENDER,
        slack_channel=custom_channel,
        org_id=ORG_ID,
        readers=reader,
        task_creator=RecordingTaskCreator(),
        notifier=RecordingNotifier(),
        gate=gate,
        acting_identity=ACTING,
    )

    slack_draft = gate.created[1]
    assert slack_draft["target"] == custom_channel
    assert slack_draft["payload"]["channel"] == custom_channel
    assert slack_draft["payload"]["notify_channel"] == custom_channel
    assert result.slack_pending_action_id == slack_draft["id"]


def test_no_email_is_clean_no_op():
    reader = FakeCrmReader(None)
    gate = RecordingGate()
    creator = RecordingTaskCreator()
    notifier = RecordingNotifier()

    result = process_latest_forwarded_email(
        sender=SENDER,
        slack_channel=CHANNEL,
        org_id=ORG_ID,
        readers=reader,
        task_creator=creator,
        notifier=notifier,
        gate=gate,
        acting_identity=ACTING,
    )

    assert result.acted is False
    assert result.email is None
    assert result.drafted_task is None
    assert result.pending_action_ids == []
    # No drafts queued, no executors run.
    assert gate.created == []
    assert creator.calls == []
    assert notifier.calls == []
    # But the reader was consulted with the configured sender/org.
    assert reader.calls == [{"sender": SENDER, "org_id": ORG_ID}]


def test_slack_notification_passes_through_output_gate():
    reader = FakeCrmReader(_email())
    gate = RecordingGate()
    output_gate = HumanOutputGate()

    result = process_latest_forwarded_email(
        sender=SENDER,
        slack_channel=CHANNEL,
        org_id=ORG_ID,
        readers=reader,
        task_creator=RecordingTaskCreator(),
        notifier=RecordingNotifier(),
        gate=gate,
        output_gate=output_gate,
        acting_identity=ACTING,
        goal_id="goal-1",
    )

    # The output gate ran and decided to SEND the (crystallized) text.
    assert result.slack_output_disposition == "send"
    # The Slack draft was queued with the gate's crystallized text.
    slack_draft = gate.created[1]
    assert slack_draft["action_type"] == ACTION_SLACK_POST
    assert slack_draft["payload"]["text"]
    assert result.slack_pending_action_id == slack_draft["id"]


def test_output_gate_suppress_withholds_slack_draft():
    # Run the same notification twice through ONE output gate: the second is a
    # duplicate, which the output gate SUPPRESSes, so no Slack draft is queued
    # the second time. The task draft still stands.
    output_gate = HumanOutputGate()

    first_gate = RecordingGate()
    process_latest_forwarded_email(
        sender=SENDER,
        slack_channel=CHANNEL,
        org_id=ORG_ID,
        readers=FakeCrmReader(_email()),
        task_creator=RecordingTaskCreator(),
        notifier=RecordingNotifier(),
        gate=first_gate,
        output_gate=output_gate,
        acting_identity=ACTING,
    )
    assert len(first_gate.created) == 2  # task + slack

    second_gate = RecordingGate()
    result = process_latest_forwarded_email(
        sender=SENDER,
        slack_channel=CHANNEL,
        org_id=ORG_ID,
        readers=FakeCrmReader(_email()),
        task_creator=RecordingTaskCreator(),
        notifier=RecordingNotifier(),
        gate=second_gate,
        output_gate=output_gate,
        acting_identity=ACTING,
    )

    # Duplicate Slack message suppressed → only the task draft was queued.
    assert result.slack_output_disposition == "suppress"
    assert result.slack_pending_action_id is None
    assert len(second_gate.created) == 1
    assert second_gate.created[0]["action_type"] == ACTION_CREATE_TASK
    assert result.task_pending_action_id is not None


def test_real_draft_approval_service_satisfies_the_gate_protocol():
    # Structural check: the production DraftApprovalService exposes the
    # create_pending_action method shape the flow's ApprovalGate Protocol needs,
    # so production wiring type-checks without a DB call here.
    from src.services.draft_approval_service import DraftApprovalService

    assert hasattr(DraftApprovalService, "create_pending_action")
