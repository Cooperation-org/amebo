"""
Tests for the goal-introspection tools (list_goals, get_goal_events).

These tools read directly from the goal repo, scoped by org_id from
the context dict. We exercise them against the real DB using the same
fixture pattern as test_goal_repo.
"""

from __future__ import annotations

import pytest

from src.db.connection import DatabaseConnection
from src.db.repositories.goal_repo import GoalRepo
from src.services.goal_engine import GoalEngine
from src.tools.goal_introspection import list_goals, get_goal_events


@pytest.fixture
def test_org_id():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES ('Tool Test', 'tool-test-' || md5(random()::text)) "
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


# ---------------------------------------------------------------------------
# list_goals
# ---------------------------------------------------------------------------


class TestListGoals:
    def test_empty(self, test_org_id):
        out = list_goals({}, {"org_id": test_org_id})
        assert "no goals" in out.lower()

    def test_lists_titles(self, engine, test_org_id):
        engine.create_goal(test_org_id, "Outreach to Rackdog")
        engine.create_goal(test_org_id, "Daily standup summary")

        out = list_goals({}, {"org_id": test_org_id})
        assert "Outreach to Rackdog" in out
        assert "Daily standup summary" in out

    def test_status_filter(self, engine, test_org_id):
        a = engine.create_goal(test_org_id, "active one")
        engine.create_goal(test_org_id, "still pending")
        engine.activate(a["id"])

        actives = list_goals({"status": "active"}, {"org_id": test_org_id})
        assert "active one" in actives
        assert "still pending" not in actives

    def test_invalid_status_returns_error(self, test_org_id):
        out = list_goals({"status": "bogus"}, {"org_id": test_org_id})
        assert "invalid" in out.lower()

    def test_no_org_returns_error(self):
        out = list_goals({}, {})
        assert "no org" in out.lower()


# ---------------------------------------------------------------------------
# get_goal_events
# ---------------------------------------------------------------------------


class TestGetGoalEvents:
    def test_returns_full_history(self, engine, test_org_id):
        g = engine.create_goal(test_org_id, "X")
        engine.activate(g["id"])

        out = get_goal_events({"goal_id": g["id"]}, {"org_id": test_org_id})
        assert "Audit trail" in out
        assert "created" in out
        assert "activated" in out
        assert "X" in out

    def test_missing_goal_id(self, test_org_id):
        out = get_goal_events({}, {"org_id": test_org_id})
        assert "goal_id is required" in out.lower()

    def test_unknown_goal(self, test_org_id):
        out = get_goal_events(
            {"goal_id": "00000000-0000-0000-0000-000000000000"},
            {"org_id": test_org_id},
        )
        assert "no goal found" in out.lower()

    def test_other_orgs_goal_not_visible(self, engine, test_org_id):
        # Make a goal in a separate org, then ask from test_org_id — must 404-like.
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO organizations (org_name, org_slug) "
                    "VALUES ('Other', 'other-' || md5(random()::text)) "
                    "RETURNING org_id"
                )
                other_org = cur.fetchone()[0]
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)

        try:
            their_goal = engine.create_goal(other_org, "secret")
            out = get_goal_events(
                {"goal_id": their_goal["id"]},
                {"org_id": test_org_id},
            )
            # Should look the same as not-found — no leak.
            assert "no goal found" in out.lower()
            assert "secret" not in out
        finally:
            conn = DatabaseConnection.get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM goals WHERE org_id = %s", (other_org,))
                    cur.execute("DELETE FROM organizations WHERE org_id = %s", (other_org,))
                    conn.commit()
            finally:
                DatabaseConnection.return_connection(conn)

    def test_no_org_returns_error(self):
        out = get_goal_events({"goal_id": "x"}, {})
        assert "no org" in out.lower()
