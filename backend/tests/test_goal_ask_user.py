"""WP12: ask_user — pause a goal to ask a human, resume on reply."""

from __future__ import annotations

import uuid
import pytest

from src.db.connection import DatabaseConnection
from src.db.repositories.goal_repo import GoalRepo
from src.services.goal_engine import GoalEngine, InvalidTransitionError
from src.tools.goal_tools import ask_user_impl


@pytest.fixture
def engine():
    return GoalEngine(GoalRepo())


@pytest.fixture
def org_id():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES ('AskUser', 'askuser-' || md5(random()::text)) RETURNING org_id")
            oid = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)
    yield oid
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM goals WHERE org_id = %s", (oid,))
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (oid,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


class TestAskUser:
    def test_await_then_answer_roundtrip(self, engine, org_id):
        g = engine.create_goal(org_id, "pick a vendor")
        engine.activate(g["id"])
        engine.await_user(g["id"], "Which vendor — A or B?", thread_ref="t1")
        assert engine.get(g["id"])["status"] == "waiting_user"
        assert "question_asked" in [e["action"] for e in engine.events(g["id"])]

        engine.answer(g["id"], "Vendor A", thread_ref="t1")
        assert engine.get(g["id"])["status"] == "pending"       # re-armed
        answered = [e for e in engine.events(g["id"]) if e["action"] == "user_answered"]
        assert answered and answered[-1]["result_summary"] == "Vendor A"  # carryover picks this up

    def test_answer_requires_waiting_user(self, engine, org_id):
        g = engine.create_goal(org_id, "x")
        with pytest.raises(InvalidTransitionError):
            engine.answer(g["id"], "no")

    def test_ask_user_tool_pauses_goal(self, engine, org_id):
        g = engine.create_goal(org_id, "x")
        engine.activate(g["id"])
        out = ask_user_impl({"question": "Ready to send?"},
                            {"goal_id": g["id"], "thread_ref": "t2"})
        assert "WAITING FOR THE USER" in out
        assert engine.get(g["id"])["status"] == "waiting_user"

    def test_ask_user_needs_a_goal(self):
        assert "only works while pursuing a goal" in ask_user_impl({"question": "hi"}, {})

    def test_ask_user_requires_question(self, engine, org_id):
        g = engine.create_goal(org_id, "x")
        engine.activate(g["id"])
        assert "question is required" in ask_user_impl({}, {"goal_id": g["id"]})
