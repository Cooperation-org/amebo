"""
End-to-end tests for /api/statements/*.

Same async-httpx-ASGI + dependency-override pattern as test_goals_api. What is
checked here is what a person can do from the page: add, correct in place,
switch on and off, keep a proposal, throw one away — and that none of it reaches
another org's rows.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest

from src.db.connection import DatabaseConnection


@pytest.fixture(scope="module")
def app():
    from src.api.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
def client(app):
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
        def patch(self, p, **kw): return self._req("PATCH", p, **kw)
        def delete(self, p, **kw): return self._req("DELETE", p, **kw)
    return _Sync()


def _new_org(name: str) -> int:
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES (%s, %s || md5(random()::text)) RETURNING org_id",
                (name, "stmt-api-"),
            )
            oid = cur.fetchone()[0]
            conn.commit()
            return oid
    finally:
        DatabaseConnection.return_connection(conn)


def _drop_org(org_id: int) -> None:
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM org_statements WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


@pytest.fixture
def org_id():
    oid = _new_org("Statements API Test")
    yield oid
    _drop_org(oid)


@pytest.fixture
def auth_as(app, org_id):
    """Impersonate a signed-in person by default; a test can switch to a service
    key (amebo itself) or to another org."""
    from src.api.middleware.auth import get_service_or_user

    current = {
        "org_id": org_id, "auth": "user", "user_id": 1,
        "email": "golda@example.org", "permissions": ["read", "write"],
    }
    app.dependency_overrides[get_service_or_user] = lambda: current

    def _set(**kw):
        current.update(kw)

    yield _set
    app.dependency_overrides.pop(get_service_or_user, None)


def _add(client, **body):
    return client.post("/api/statements/", json={"name": "mission", **body})


# ---------------------------------------------------------------------------


def test_a_person_adds_one_and_it_is_live(client, auth_as):
    r = _add(client, body="we help people prove what they did",
             source="whiteboard photo, 4 aug", informs_priority=True)
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["accepted_at"] is not None
    assert row["written_by"] == "golda@example.org"

    live = client.get("/api/statements/resolved").json()
    assert live == [{"id": row["id"], "name": "mission",
                     "text": "we help people prove what they did"}]


def test_amebo_proposing_is_inert(client, auth_as):
    """A service key is amebo. What it writes is visible and does nothing."""
    auth_as(auth="service", key_name="claw")
    row = _add(client, body="a guess from a transcript",
               informs_priority=True).json()
    assert row["accepted_at"] is None
    assert client.get("/api/statements/resolved").json() == []

    # The page shows it so it can be kept or thrown away where it sits.
    assert [s["id"] for s in client.get("/api/statements/").json()] == [row["id"]]

    auth_as(auth="user", email="golda@example.org")
    kept = client.patch(f"/api/statements/{row['id']}", json={"accept": True}).json()
    assert kept["accepted_at"] is not None
    assert len(client.get("/api/statements/resolved").json()) == 1


def test_words_or_a_pointer_but_not_both(client, auth_as):
    assert _add(client, body="words", pointer="https://example.org/m").status_code == 422
    assert _add(client).status_code == 422


def test_switching_a_pointer_to_words_replaces_it(client, auth_as):
    row = _add(client, pointer="https://example.org/m", informs_priority=True).json()
    assert row["body"] is None

    edited = client.patch(f"/api/statements/{row['id']}",
                          json={"body": "typed out instead"}).json()
    assert edited["body"] == "typed out instead"
    assert edited["pointer"] is None


def test_a_pointer_is_read_at_use_time(client, auth_as):
    row = _add(client, pointer="https://example.org/m", informs_priority=True).json()
    with patch("src.tools.http_fetch.http_fetch", return_value="what the doc says"):
        live = client.get("/api/statements/resolved").json()
    assert live == [{"id": row["id"], "name": "mission", "text": "what the doc says"}]


def test_switching_it_off_stops_it_steering(client, auth_as):
    row = _add(client, body="words", informs_priority=True).json()
    client.patch(f"/api/statements/{row['id']}", json={"informs_priority": False})
    assert client.get("/api/statements/resolved").json() == []


def test_throwing_one_away(client, auth_as):
    row = _add(client, body="outgrown").json()
    assert client.delete(f"/api/statements/{row['id']}").status_code == 204
    assert client.get("/api/statements/").json() == []
    assert client.delete(f"/api/statements/{row['id']}").status_code == 404


def test_another_org_sees_and_touches_nothing(client, auth_as, org_id):
    row = _add(client, body="ours", informs_priority=True).json()
    other = _new_org("Statements API Other")
    try:
        auth_as(org_id=other)
        assert client.get("/api/statements/").json() == []
        assert client.patch(f"/api/statements/{row['id']}",
                            json={"name": "theirs"}).status_code == 404
        assert client.delete(f"/api/statements/{row['id']}").status_code == 404
    finally:
        _drop_org(other)

    auth_as(org_id=org_id)
    assert client.get("/api/statements/").json()[0]["name"] == "mission"
