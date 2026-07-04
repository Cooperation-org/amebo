"""
Tests for GoalDispatcher.

We don't call Anthropic; the client is injected and mocked. abra context
loading is exercised against the real DB so the BindingRepo integration is
covered, but if abra isn't reachable from the test environment the loader
fails soft (returns empty context). That's the intended behavior in prod
too — a missing knowledge store should not block goal dispatch.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.db.connection import DatabaseConnection
from src.db.repositories.goal_repo import GoalRepo
from src.services.goal_dispatcher import (
    DispatchResult, GoalDispatcher,
)
from src.services.goal_engine import GoalEngine


@pytest.fixture
def test_org_id():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES ('Dispatcher Test', 'disp-test-' || md5(random()::text)) "
                "RETURNING org_id"
            )
            org_id = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)

    yield org_id

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM goals WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM instances WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


def _make_fake_client(text: str = "all done."):
    """
    Returns a MagicMock that mimics anthropic.Anthropic.messages.create.

    Mimics the SDK shape closely enough for the dispatcher's tool-use
    loop: content blocks expose .type, the response carries a stop_reason
    of "end_turn" so the loop exits cleanly, and a usage block lets the
    guardrail cost path run.
    """
    from types import SimpleNamespace
    client = MagicMock()
    block = SimpleNamespace(type="text", text=text)
    response = SimpleNamespace(
        content=[block],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=10,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
    )
    client.messages.create.return_value = response
    return client


@pytest.fixture
def engine():
    return GoalEngine(GoalRepo())


class TestDispatchHappyPath:
    def test_completes_goal_and_records_summary(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "Draft a post about resilience")

        client = _make_fake_client("Drafted the post.")
        dispatcher = GoalDispatcher(anthropic_client=client)

        result = dispatcher.dispatch(g["id"])

        assert result.status == "completed"
        # The loop appends stats; the model's text is still the leading content.
        assert result.summary.startswith("Drafted the post.")

        # Goal row reflects completion
        final = engine.get(g["id"])
        assert final["status"] == "completed"
        assert final["completed_at"] is not None

        # Audit trail: created → activated → dispatch_summary → completed
        actions = [e["action"] for e in engine.events(g["id"])]
        assert actions == ["created", "activated", "dispatch_summary", "completed"]

    def test_notification_sent_when_channel_set(self, engine, test_org_id):
        g = engine.create_goal(
            test_org_id, "X", notify_channel="slack:#goals",
        )

        sent: list[tuple[str, str]] = []
        def fake_notifier(ch, msg):
            sent.append((ch, msg))
            return True

        dispatcher = GoalDispatcher(
            anthropic_client=_make_fake_client(),
            notifier=fake_notifier,
        )
        result = dispatcher.dispatch(g["id"])

        assert result.notification_sent is True
        assert len(sent) == 1
        assert sent[0][0] == "slack:#goals"
        assert "Goal completed" in sent[0][1]

    def test_no_notification_when_channel_missing(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X")

        called = []
        dispatcher = GoalDispatcher(
            anthropic_client=_make_fake_client(),
            notifier=lambda ch, msg: called.append((ch, msg)) or True,
        )
        result = dispatcher.dispatch(g["id"])
        assert result.notification_sent is False
        assert called == []


class TestDispatchSkipsTerminal:
    def test_skips_already_completed_goal(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X")
        engine.activate(g["id"])
        engine.complete(g["id"], summary="prior run")

        dispatcher = GoalDispatcher(anthropic_client=_make_fake_client())
        result = dispatcher.dispatch(g["id"])

        assert result.status == "skipped"
        # No new lifecycle events added
        actions = [e["action"] for e in engine.events(g["id"])]
        assert actions == ["created", "activated", "completed"]


class TestDispatchHandlesFailure:
    def test_failure_marks_goal_failed_with_reason(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X")

        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("model went away")
        dispatcher = GoalDispatcher(anthropic_client=client)

        result = dispatcher.dispatch(g["id"])

        assert result.status == "failed"
        assert "model went away" in (result.error or "")

        # Goal row reflects failure
        final = engine.get(g["id"])
        assert final["status"] == "failed"

        actions = [e["action"] for e in engine.events(g["id"])]
        assert "failed" in actions


class TestDispatchOfflineMode:
    def test_dispatch_without_client_uses_stub_summary(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X")
        dispatcher = GoalDispatcher(anthropic_client=None)
        result = dispatcher.dispatch(g["id"])
        assert result.status == "completed"
        assert result.summary is not None
        assert "[no-llm]" in result.summary


class TestUnknownGoal:
    def test_dispatch_unknown_goal_returns_failed(self):
        dispatcher = GoalDispatcher(anthropic_client=_make_fake_client())
        result = dispatcher.dispatch("00000000-0000-0000-0000-000000000000")
        assert result.status == "failed"
        assert "not found" in (result.error or "").lower()


class TestRecurringGoalReArms:
    """
    A recurring (cron) goal must not retire after one run. It re-arms to
    pending so the scheduler picks it up again on the next cron edge.
    """

    CRON = {"type": "cron", "expression": "0 9 * * *"}

    def test_cron_goal_rearms_instead_of_completing(self, engine, test_org_id):
        g = engine.create_goal(
            test_org_id, "Daily reddit scout", trigger_config=self.CRON,
        )

        dispatcher = GoalDispatcher(anthropic_client=None)  # offline stub
        result = dispatcher.dispatch(g["id"])

        # The run itself finished fine...
        assert result.status == "completed"
        # ...but the goal returns to pending rather than terminal completed.
        final = engine.get(g["id"])
        assert final["status"] == "pending"
        assert final["completed_at"] is None

        actions = [e["action"] for e in engine.events(g["id"])]
        assert actions == ["created", "activated", "dispatch_summary", "rearmed"]

    def test_cron_goal_can_dispatch_again_after_rearm(self, engine, test_org_id):
        # Proves recurrence: a re-armed goal is runnable again, not stuck.
        g = engine.create_goal(
            test_org_id, "Daily reddit scout", trigger_config=self.CRON,
        )
        dispatcher = GoalDispatcher(anthropic_client=None)

        dispatcher.dispatch(g["id"])
        result2 = dispatcher.dispatch(g["id"])

        assert result2.status == "completed"
        assert engine.get(g["id"])["status"] == "pending"
        actions = [e["action"] for e in engine.events(g["id"])]
        assert actions == [
            "created", "activated", "dispatch_summary", "rearmed",
            "activated", "dispatch_summary", "rearmed",
        ]

    def test_one_shot_goals_still_complete_terminally(self, engine, test_org_id):
        dispatcher = GoalDispatcher(anthropic_client=None)

        # No trigger_config → one-shot → unchanged terminal completion.
        g1 = engine.create_goal(test_org_id, "Send one digest")
        dispatcher.dispatch(g1["id"])
        assert engine.get(g1["id"])["status"] == "completed"

        # A cron trigger with no expression is not recurring → completes.
        g2 = engine.create_goal(
            test_org_id, "Misconfigured cron",
            trigger_config={"type": "cron"},
        )
        dispatcher.dispatch(g2["id"])
        assert engine.get(g2["id"])["status"] == "completed"
