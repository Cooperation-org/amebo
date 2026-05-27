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
    """Returns a MagicMock that mimics anthropic.Anthropic.messages.create."""
    client = MagicMock()
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
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
        assert result.summary == "Drafted the post."

        # Goal row reflects completion
        final = engine.get(g["id"])
        assert final["status"] == "completed"
        assert final["completed_at"] is not None

        # Audit trail: created → activated → completed
        actions = [e["action"] for e in engine.events(g["id"])]
        assert actions == ["created", "activated", "completed"]

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
