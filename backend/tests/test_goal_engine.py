"""
Tests for GoalEngine — state machine semantics. Uses the real GoalRepo
against the test DB (same pattern as test_goal_repo.py).
"""

from __future__ import annotations

import pytest

from src.db.connection import DatabaseConnection
from src.db.repositories.goal_repo import GoalRepo
from src.services.goal_engine import (
    GoalEngine, GoalNotFoundError, InvalidTransitionError,
)


@pytest.fixture
def test_org_id():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES ('Engine Test', 'engine-test-' || md5(random()::text)) "
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
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


@pytest.fixture
def engine():
    return GoalEngine(GoalRepo())


class TestCreateGoal:
    def test_create_writes_creation_event(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X", created_by_user_id=None)
        events = engine.events(g["id"])
        assert len(events) == 1
        assert events[0]["action"] == "created"
        assert events[0]["actor_type"] == "system"

    def test_create_with_user_records_user_actor(self, engine, test_org_id):
        # platform_users FK is nullable; passing None for actor since we don't
        # set up a real user in this test fixture.
        g = engine.create_goal(test_org_id, "X")
        events = engine.events(g["id"])
        assert events[0]["actor_type"] == "system"


class TestLifecycleTransitions:
    def test_activate_pending(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X")
        updated = engine.activate(g["id"])
        assert updated is not None
        assert updated["status"] == "active"

        events = engine.events(g["id"])
        actions = [e["action"] for e in events]
        assert actions == ["created", "activated"]

    def test_complete_from_active(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X")
        engine.activate(g["id"])
        completed = engine.complete(g["id"], summary="all done")
        assert completed["status"] == "completed"
        assert completed["completed_at"] is not None

        events = engine.events(g["id"])
        last = events[-1]
        assert last["action"] == "completed"
        assert last["result_summary"] == "all done"

    def test_fail_from_active(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X")
        engine.activate(g["id"])
        failed = engine.fail(g["id"], reason="ran out of tools")
        assert failed["status"] == "failed"

    def test_pause_and_resume(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X")
        engine.activate(g["id"])
        paused = engine.pause(g["id"])
        assert paused["status"] == "paused"
        resumed = engine.resume(g["id"])
        assert resumed["status"] == "active"

        actions = [e["action"] for e in engine.events(g["id"])]
        assert actions == ["created", "activated", "paused", "resumed"]


class TestInvalidTransitions:
    def test_complete_pending_raises(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X")
        with pytest.raises(InvalidTransitionError):
            engine.complete(g["id"])

    def test_terminal_states_cannot_transition(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X")
        engine.activate(g["id"])
        engine.complete(g["id"])

        # activate() is race-tolerant: it returns None instead of raising.
        # Used by schedulers where another worker may have already moved
        # the goal forward.
        assert engine.activate(g["id"]) is None
        # Explicit lifecycle ops (fail/complete) require_existing → raise.
        with pytest.raises(InvalidTransitionError):
            engine.fail(g["id"])

    def test_unknown_goal_raises(self, engine):
        missing = "00000000-0000-0000-0000-000000000000"
        with pytest.raises(GoalNotFoundError):
            engine.get(missing)
        with pytest.raises(GoalNotFoundError):
            engine.complete(missing)


class TestRaceFreeActivate:
    def test_activate_already_active_returns_none(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X")
        engine.activate(g["id"])
        # Second call should NOT raise; it just sees the goal is not pending.
        result = engine.activate(g["id"])
        assert result is None


class TestToolCallEvents:
    def test_record_tool_call_does_not_change_status(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X")
        engine.activate(g["id"])
        event = engine.record_tool_call(
            g["id"], "abra", result_summary="searched",
        )
        assert event["action"] == "tool_call:abra"

        goal_after = engine.get(g["id"])
        assert goal_after["status"] == "active"

        events = engine.events(g["id"])
        actions = [e["action"] for e in events]
        assert actions == ["created", "activated", "tool_call:abra"]
