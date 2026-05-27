"""
Tests for GoalRepo. Hits the real amebo DB (psycopg2 pool), following the
existing test_workspace_isolation.py pattern. Each test class creates and
cleans up its own org so tests are isolated.
"""

from __future__ import annotations

import pytest

from src.db.connection import DatabaseConnection
from src.db.repositories.goal_repo import GoalRepo


@pytest.fixture
def test_org_id():
    """Create a throw-away org for the test, return its id, clean up after."""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO organizations (org_name, org_slug)
                VALUES ('Test Goal Org', 'test-goal-org-' || md5(random()::text))
                RETURNING org_id
                """,
            )
            org_id = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)

    yield org_id

    # Clean up — goals cascade-delete via FK, but organization itself must go too
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM goals WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


@pytest.fixture
def repo():
    return GoalRepo()


class TestGoalCRUD:
    def test_create_returns_pending_goal_with_uuid(self, repo, test_org_id):
        goal = repo.create(org_id=test_org_id, title="Pursue partnership")
        assert goal["id"]  # UUID assigned by DB
        assert goal["org_id"] == test_org_id
        assert goal["title"] == "Pursue partnership"
        assert goal["status"] == "pending"
        assert goal["completed_at"] is None

    def test_create_with_full_payload(self, repo, test_org_id):
        goal = repo.create(
            org_id=test_org_id,
            title="Daily comms",
            description="Post a daily aligned update",
            target_criteria={"posts_per_day": 1},
            trigger_config={"type": "cron", "expression": "0 9 * * *"},
            notify_channel="slack:#comms",
        )
        assert goal["target_criteria"] == {"posts_per_day": 1}
        assert goal["trigger_config"]["type"] == "cron"
        assert goal["notify_channel"] == "slack:#comms"

    def test_get_returns_none_for_unknown_uuid(self, repo):
        assert repo.get("00000000-0000-0000-0000-000000000000") is None

    def test_get_round_trip(self, repo, test_org_id):
        created = repo.create(org_id=test_org_id, title="X")
        fetched = repo.get(created["id"])
        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["title"] == "X"


class TestGoalListing:
    def test_list_for_org_newest_first(self, repo, test_org_id):
        a = repo.create(org_id=test_org_id, title="A")
        b = repo.create(org_id=test_org_id, title="B")
        items = repo.list_for_org(test_org_id)
        assert len(items) == 2
        # newest first — b was created after a
        assert items[0]["id"] == b["id"]
        assert items[1]["id"] == a["id"]

    def test_list_for_org_filters_by_status(self, repo, test_org_id):
        a = repo.create(org_id=test_org_id, title="A")
        repo.create(org_id=test_org_id, title="B")
        repo.set_status(a["id"], "active")

        actives = repo.list_for_org(test_org_id, status="active")
        assert len(actives) == 1
        assert actives[0]["id"] == a["id"]

    def test_list_for_org_invalid_status_raises(self, repo, test_org_id):
        with pytest.raises(ValueError):
            repo.list_for_org(test_org_id, status="bogus")

    def test_list_pending_for_specific_org_excludes_others(self, repo, test_org_id):
        # Create another org with a pending goal that should NOT appear
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO organizations (org_name, org_slug) "
                    "VALUES ('Other', 'other-' || md5(random()::text)) RETURNING org_id"
                )
                other_org_id = cur.fetchone()[0]
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)

        try:
            other_goal = repo.create(org_id=other_org_id, title="other")
            mine = repo.create(org_id=test_org_id, title="mine")

            mine_pending = repo.list_pending(org_id=test_org_id)
            assert [g["id"] for g in mine_pending] == [mine["id"]]

            all_pending_ids = {g["id"] for g in repo.list_pending()}
            assert mine["id"] in all_pending_ids
            assert other_goal["id"] in all_pending_ids
        finally:
            conn = DatabaseConnection.get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM goals WHERE org_id = %s", (other_org_id,))
                    cur.execute("DELETE FROM organizations WHERE org_id = %s", (other_org_id,))
                    conn.commit()
            finally:
                DatabaseConnection.return_connection(conn)


class TestGoalStatus:
    def test_set_status_transitions(self, repo, test_org_id):
        g = repo.create(org_id=test_org_id, title="X")
        updated = repo.set_status(g["id"], "active")
        assert updated["status"] == "active"
        assert updated["completed_at"] is None

    def test_set_status_completed_sets_timestamp(self, repo, test_org_id):
        g = repo.create(org_id=test_org_id, title="X")
        updated = repo.set_status(g["id"], "completed", completed=True)
        assert updated["status"] == "completed"
        assert updated["completed_at"] is not None

    def test_set_status_invalid_raises(self, repo, test_org_id):
        g = repo.create(org_id=test_org_id, title="X")
        with pytest.raises(ValueError):
            repo.set_status(g["id"], "bogus")


class TestGoalEvents:
    def test_append_event_assigns_zero_then_increments(self, repo, test_org_id):
        g = repo.create(org_id=test_org_id, title="X")
        e0 = repo.append_event(g["id"], actor_type="user", action="created")
        e1 = repo.append_event(g["id"], actor_type="claw", action="activated")
        e2 = repo.append_event(g["id"], actor_type="claw", action="completed",
                                result_summary="done")

        assert e0["step_index"] == 0
        assert e1["step_index"] == 1
        assert e2["step_index"] == 2
        assert e2["result_summary"] == "done"

    def test_append_event_unknown_goal_raises(self, repo):
        with pytest.raises(LookupError):
            repo.append_event(
                "00000000-0000-0000-0000-000000000000",
                actor_type="system", action="created",
            )

    def test_append_event_invalid_actor_raises(self, repo, test_org_id):
        g = repo.create(org_id=test_org_id, title="X")
        with pytest.raises(ValueError):
            repo.append_event(g["id"], actor_type="bogus", action="x")

    def test_list_events_in_order(self, repo, test_org_id):
        g = repo.create(org_id=test_org_id, title="X")
        repo.append_event(g["id"], actor_type="user", action="created")
        repo.append_event(g["id"], actor_type="claw", action="activated")

        events = repo.list_events(g["id"])
        assert [e["step_index"] for e in events] == [0, 1]
        assert [e["action"] for e in events] == ["created", "activated"]

    def test_events_cascade_on_goal_delete(self, repo, test_org_id):
        g = repo.create(org_id=test_org_id, title="X")
        repo.append_event(g["id"], actor_type="user", action="created")

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM goals WHERE id = %s", (g["id"],))
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)

        assert repo.list_events(g["id"]) == []
