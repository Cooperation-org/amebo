"""WP14: weekly recap digest from an org's live goals + their carryover."""
from __future__ import annotations
import uuid
import pytest
from src.db.connection import DatabaseConnection
from src.db.repositories.goal_repo import GoalRepo
from src.services.goal_engine import GoalEngine
from src.services.weekly_recap import weekly_recap


@pytest.fixture
def org_id():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO organizations (org_name, org_slug) "
                        "VALUES ('Recap', 'recap-' || md5(random()::text)) RETURNING org_id")
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


class TestWeeklyRecap:
    def test_empty(self, org_id):
        assert "No active goals" in weekly_recap(org_id)

    def test_surfaces_blocked_and_moving(self, org_id):
        eng = GoalEngine(GoalRepo())
        a = eng.create_goal(org_id, "line up partners")
        eng.activate(a["id"])
        GoalRepo().append_event(goal_id=a["id"], actor_type="claw",
                                action="dispatch_summary", result_summary="reached out to 2 co-ops")
        b = eng.create_goal(org_id, "confirm venue")
        eng.activate(b["id"])
        eng.await_user(b["id"], "Which date works?")

        digest = weekly_recap(org_id)
        assert "line up partners" in digest and "reached out to 2 co-ops" in digest
        assert "confirm venue" in digest and "Needs you" in digest
        # blocked goal appears under the needs-you section
        assert digest.index("Needs you") < digest.index("confirm venue")
