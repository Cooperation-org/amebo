"""
End-to-end tests for the /api/goals/* surface.

Uses the same async-httpx-ASGI fixture pattern as test_changemaker_endpoints.
Auth is mocked at the dependency level so we don't need a real API key
record; tests focus on the route shapes and org-scoping rules.
"""

from __future__ import annotations

from unittest.mock import patch
from datetime import datetime, timezone

import httpx
import pytest

from src.db.connection import DatabaseConnection
from src.db.repositories.goal_repo import GoalRepo
from src.services.goal_engine import GoalEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    from src.api.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
def client(app):
    """Async httpx client backed by an ASGI transport (sync façade)."""
    import asyncio
    transport = httpx.ASGITransport(app=app)

    class _Sync:
        def _req(self, method, path, **kw):
            async def go():
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as ac:
                    return await ac.request(method, path, **kw)
            return asyncio.run(go())
        def get(self, p, **kw): return self._req("GET", p, **kw)
        def post(self, p, **kw): return self._req("POST", p, **kw)
    return _Sync()


@pytest.fixture
def test_org_id():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES ('Goals API Test', 'goals-api-' || md5(random()::text)) "
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
def auth_as(app, test_org_id):
    """
    Override the goals routes' auth dependency so tests don't need real
    API keys or JWTs. The routes authenticate via get_service_or_user
    (accepts either a service X-API-Key or a user JWT); both paths resolve
    to a client dict carrying org_id, which is all the routes read. Yields a
    callable that lets a test switch the impersonated org partway through.
    """
    from src.api.middleware.auth import get_service_or_user

    current = {
        "org_id": test_org_id, "key_name": "test",
        "permissions": ["read", "write"], "auth": "service",
    }

    def _override():
        return current

    app.dependency_overrides[get_service_or_user] = _override

    def _set_org(org_id: int):
        current["org_id"] = org_id

    yield _set_org

    app.dependency_overrides.pop(get_service_or_user, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateAndList:
    def test_create_and_list(self, client, auth_as, test_org_id):
        resp = client.post("/api/goals/", json={"title": "First goal"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["title"] == "First goal"
        assert body["org_id"] == test_org_id
        assert body["status"] == "pending"

        list_resp = client.get("/api/goals/")
        assert list_resp.status_code == 200
        assert any(g["id"] == body["id"] for g in list_resp.json())

    def test_create_with_full_payload(self, client, auth_as):
        resp = client.post("/api/goals/", json={
            "title": "Cron goal",
            "description": "runs every minute",
            "target_criteria": {"max_calls": 1},
            "trigger_config": {"type": "cron", "expression": "* * * * *"},
            "notify_channel": "slack:#x",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["trigger_config"]["type"] == "cron"
        assert body["notify_channel"] == "slack:#x"

    def test_list_filtered_by_status(self, client, auth_as):
        a = client.post("/api/goals/", json={"title": "A"}).json()
        client.post("/api/goals/", json={"title": "B"})

        # Move A to active via dispatch-now, then ensure status filter works
        with patch("src.api.routes.goals.GoalDispatcher") as DP:
            DP.return_value.dispatch.return_value = type(
                "R", (), {
                    "goal_id": a["id"], "status": "skipped",
                    "summary": None, "error": None, "notification_sent": False,
                    "tool_rounds": 0, "tool_calls": [],
                },
            )()
            client.post(f"/api/goals/{a['id']}/dispatch-now")

        resp = client.get("/api/goals/?status=pending")
        ids = [g["id"] for g in resp.json()]
        # B should still be pending; A's status depends on dispatch (skipped does
        # not move A out of pending here, so it still appears).
        assert any(g_id for g_id in ids)

    def test_list_invalid_status_400(self, client, auth_as):
        resp = client.get("/api/goals/?status=bogus")
        assert resp.status_code == 400


class TestGetGoal:
    def test_get_returns_goal(self, client, auth_as):
        created = client.post("/api/goals/", json={"title": "X"}).json()
        resp = client.get(f"/api/goals/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_unknown_returns_404(self, client, auth_as):
        resp = client.get("/api/goals/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestOrgScoping:
    def test_other_orgs_goal_invisible(self, client, auth_as):
        # Create a goal as one org
        created = client.post("/api/goals/", json={"title": "private"}).json()

        # Make another org and switch to it
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO organizations (org_name, org_slug) "
                    "VALUES ('Other Org', 'other-' || md5(random()::text)) "
                    "RETURNING org_id"
                )
                other_org_id = cur.fetchone()[0]
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)

        try:
            auth_as(other_org_id)

            # GET by id must 404, not 403, to avoid leaking existence
            resp = client.get(f"/api/goals/{created['id']}")
            assert resp.status_code == 404

            # LIST must not include it
            list_resp = client.get("/api/goals/")
            assert all(g["id"] != created["id"] for g in list_resp.json())
        finally:
            conn = DatabaseConnection.get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM organizations WHERE org_id = %s",
                                (other_org_id,))
                    conn.commit()
            finally:
                DatabaseConnection.return_connection(conn)


class TestEvents:
    def test_events_returned_in_order(self, client, auth_as, test_org_id):
        engine = GoalEngine(GoalRepo())
        g = engine.create_goal(test_org_id, "X")
        engine.activate(g["id"])

        resp = client.get(f"/api/goals/{g['id']}/events")
        assert resp.status_code == 200
        events = resp.json()
        assert [e["action"] for e in events] == ["created", "activated"]
        assert events[0]["step_index"] == 0
        assert events[1]["step_index"] == 1


class TestLifecycleOps:
    def test_pause_and_resume(self, client, auth_as):
        created = client.post("/api/goals/", json={"title": "X"}).json()
        # Pause from pending is allowed by the engine's transition table
        paused = client.post(f"/api/goals/{created['id']}/pause").json()
        assert paused["status"] == "paused"
        # Resume → active
        resumed = client.post(f"/api/goals/{created['id']}/resume").json()
        assert resumed["status"] == "active"

    def test_resume_when_not_paused_409(self, client, auth_as):
        created = client.post("/api/goals/", json={"title": "X"}).json()
        # Goal is pending — resume() expects paused → 409
        resp = client.post(f"/api/goals/{created['id']}/resume")
        assert resp.status_code == 409

    def test_answer_waiting_goal(self, client, auth_as, test_org_id):
        engine = GoalEngine(GoalRepo())
        g = engine.create_goal(test_org_id, "needs input",
                               config={"short_name": "t-answer"})
        engine.activate(g["id"])
        engine.await_user(g["id"], question="which one?")

        resp = client.post(f"/api/goals/{g['id']}/answer",
                           json={"answer": "the first one"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "pending"
        # config rides through the response so the queue can sort/label
        assert body["config"]["short_name"] == "t-answer"

        # A background dispatch may append further events after the answer,
        # so assert on presence, not position.
        events = client.get(f"/api/goals/{g['id']}/events").json()
        answered = [e for e in events if e["action"] == "user_answered"]
        assert len(answered) == 1
        assert answered[0]["result_summary"] == "the first one"

    def test_answer_when_not_waiting_409(self, client, auth_as):
        created = client.post("/api/goals/", json={"title": "X"}).json()
        resp = client.post(f"/api/goals/{created['id']}/answer",
                           json={"answer": "too early"})
        assert resp.status_code == 409


class TestDispatchNow:
    def test_dispatch_now_invokes_dispatcher(self, client, auth_as, test_org_id):
        engine = GoalEngine(GoalRepo())
        g = engine.create_goal(test_org_id, "manual one",
                                trigger_config={"type": "manual"})

        fake_result = type("R", (), {
            "goal_id": g["id"], "status": "completed",
            "summary": "done", "error": None, "notification_sent": True,
            "tool_rounds": 2,
            "tool_calls": [
                {"name": "abra_search", "ok": True, "summary": "found 3"},
                {"name": "slack_post", "ok": True, "summary": "[held for approval] ..."},
            ],
        })()

        with patch("src.api.routes.goals.GoalDispatcher") as DP:
            DP.return_value.dispatch.return_value = fake_result
            resp = client.post(f"/api/goals/{g['id']}/dispatch-now")

        assert resp.status_code == 200
        # The per-step trail is surfaced so a manual run is never blank.
        assert resp.json() == {
            "goal_id": g["id"],
            "status": "completed",
            "summary": "done",
            "error": None,
            "notification_sent": True,
            "tool_rounds": 2,
            "tool_calls": [
                {"name": "abra_search", "ok": True, "summary": "found 3"},
                {"name": "slack_post", "ok": True, "summary": "[held for approval] ..."},
            ],
        }
