"""
End-to-end tests for /api/connections/* and /connect/* routes.

Uses the same async-httpx-ASGI fixture pattern as the other API tests.
get_service_client and get_current_user_optional are overridden so we
don't need real API keys or JWTs. The Google OAuth adapter is patched
out — we use the registered fake adapter.

Tests focus on:
- Minting connect links + URL shape.
- Listing / revoking via the service API.
- The user-facing /connect/<code> flow: link validation, auth gates,
  redirect to provider OAuth.
- The /connect/<code>/callback flow: code → store → consume → success
  page.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import patch

import httpx
import pytest
from cryptography.fernet import Fernet

from src.credentials import (
    CredentialResolver,
    encryption as cred_encryption,
    get_connect_link,
    mint_connect_link,
)
from src.db.connection import DatabaseConnection


# ---------------------------------------------------------------------------
# Module-scoped encryption key
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def _test_encryption_key():
    prior = os.environ.get("AMEBO_CRED_KEY")
    os.environ["AMEBO_CRED_KEY"] = Fernet.generate_key().decode()
    cred_encryption.reset_for_tests()
    yield
    if prior is None:
        os.environ.pop("AMEBO_CRED_KEY", None)
    else:
        os.environ["AMEBO_CRED_KEY"] = prior
    cred_encryption.reset_for_tests()


# ---------------------------------------------------------------------------
# Test org + user fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_org_id():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES ('Conn Test', 'conn-test-' || md5(random()::text)) "
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
            cur.execute("DELETE FROM connect_links WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM org_credentials WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


# ---------------------------------------------------------------------------
# Async ASGI client fixture (same pattern as other tests)
# ---------------------------------------------------------------------------


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
        def delete(self, p, **kw): return self._req("DELETE", p, **kw)
    return _Sync()


# ---------------------------------------------------------------------------
# Auth overrides
# ---------------------------------------------------------------------------


@pytest.fixture
def service_auth(app, test_org_id):
    from src.api.middleware.auth import get_service_client

    cur = {"org_id": test_org_id, "key_name": "test", "permissions": ["read", "write"]}
    app.dependency_overrides[get_service_client] = lambda: cur

    def _set_org(org_id):
        cur["org_id"] = org_id

    yield _set_org
    app.dependency_overrides.pop(get_service_client, None)


@pytest.fixture
def user_auth(app, test_org_id):
    """Override get_current_user_optional to return a logged-in admin."""
    from src.api.middleware.auth import get_current_user_optional

    cur: Dict[str, Any] = {
        "user_id": 1, "org_id": test_org_id, "role": "admin", "email": "a@b",
    }

    def _override():
        return cur

    app.dependency_overrides[get_current_user_optional] = _override

    def _set(**kwargs):
        cur.update(kwargs)

    def _set_anon():
        app.dependency_overrides[get_current_user_optional] = lambda: None

    yield {"set": _set, "anon": _set_anon, "user": cur}
    app.dependency_overrides.pop(get_current_user_optional, None)


# ---------------------------------------------------------------------------
# /api/connections/start
# ---------------------------------------------------------------------------


class TestStartConnection:
    def test_mint_returns_url_and_short_code(self, client, service_auth, test_org_id):
        resp = client.post("/api/connections/start", json={
            "kind": "fake", "scopes": ["scope1", "scope2"],
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["kind"] == "fake"
        assert body["short_code"]
        assert body["connect_url"].endswith(f"/connect/{body['short_code']}")

        # Verify it's actually in the DB
        link = get_connect_link(body["short_code"])
        assert link.org_id == test_org_id
        assert link.kind == "fake"
        assert "scope1" in link.requested_scopes

    def test_unknown_kind_returns_400(self, client, service_auth):
        resp = client.post("/api/connections/start", json={
            "kind": "no_such_provider",
        })
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /api/connections/  (list, revoke)
# ---------------------------------------------------------------------------


class TestListAndRevoke:
    def test_list_excludes_blobs(self, client, service_auth, test_org_id):
        CredentialResolver.store_new(
            org_id=test_org_id, kind="fake", access_token="secret-xyz",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        resp = client.get("/api/connections/")
        assert resp.status_code == 200
        body = resp.json()
        assert any(r["kind"] == "fake" for r in body)
        # No raw token / blob should appear anywhere in the response.
        assert "secret-xyz" not in resp.text

    def test_revoke(self, client, service_auth, test_org_id):
        CredentialResolver.store_new(
            org_id=test_org_id, kind="fake", access_token="abc",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        resp = client.delete("/api/connections/fake")
        assert resp.status_code == 200
        assert resp.json() == {"revoked": True}

        # Second revoke should 404
        resp2 = client.delete("/api/connections/fake")
        assert resp2.status_code == 404


# ---------------------------------------------------------------------------
# /connect/{short_code}  — user-facing
# ---------------------------------------------------------------------------


class TestConnectStart:
    def test_unknown_link_renders_404(self, client, user_auth):
        resp = client.get("/connect/no-such-code")
        assert resp.status_code == 404
        assert "not found" in resp.text.lower()

    def test_anon_user_sees_login_prompt(self, app, client, user_auth, test_org_id):
        link = mint_connect_link(org_id=test_org_id, kind="fake", requested_scopes=[])
        # Make the user-auth fixture return None
        user_auth["anon"]()
        resp = client.get(f"/connect/{link.short_code}")
        assert resp.status_code == 401
        assert "sign in" in resp.text.lower()

    def test_wrong_org_user_is_rejected(self, client, user_auth, test_org_id):
        link = mint_connect_link(org_id=test_org_id, kind="fake", requested_scopes=[])
        user_auth["set"](org_id=test_org_id + 999_999)  # not the org
        resp = client.get(f"/connect/{link.short_code}")
        assert resp.status_code == 403
        assert "different organisation" in resp.text.lower()

    def test_non_admin_is_rejected(self, client, user_auth, test_org_id):
        link = mint_connect_link(org_id=test_org_id, kind="fake", requested_scopes=[])
        user_auth["set"](role="member")
        resp = client.get(f"/connect/{link.short_code}")
        assert resp.status_code == 403
        assert "admin" in resp.text.lower()

    def test_admin_is_redirected_to_provider(self, client, user_auth, test_org_id):
        link = mint_connect_link(
            org_id=test_org_id, kind="fake", requested_scopes=["a", "b"],
        )
        resp = client.get(f"/connect/{link.short_code}", follow_redirects=False)
        assert resp.status_code == 302
        loc = resp.headers["location"]
        assert "fake.example" in loc
        assert link.short_code in loc
        # Scopes appear in the authorize URL.
        assert "a" in loc and "b" in loc

    def test_consumed_link_is_410(self, client, user_auth, test_org_id):
        link = mint_connect_link(org_id=test_org_id, kind="fake", requested_scopes=[])
        from src.credentials import consume_connect_link
        consume_connect_link(link.short_code, consumed_by_user_id=1)
        resp = client.get(f"/connect/{link.short_code}")
        assert resp.status_code == 410


# ---------------------------------------------------------------------------
# /connect/{short_code}/callback
# ---------------------------------------------------------------------------


class TestConnectCallback:
    def test_success_stores_credential_and_consumes_link(
        self, client, user_auth, test_org_id,
    ):
        link = mint_connect_link(org_id=test_org_id, kind="fake", requested_scopes=[])
        resp = client.get(
            f"/connect/{link.short_code}/callback",
            params={"code": "abc-code"},
        )
        assert resp.status_code == 200
        assert "fake connected" in resp.text.lower()

        # Credential present and decryptable
        cred = CredentialResolver(test_org_id, kind="fake").get()
        assert cred.access_token == "fake-token-from-abc-code"

        # Link is consumed
        link_after = get_connect_link(link.short_code)
        assert link_after.is_consumed

    def test_user_denial_renders_error_page(self, client, user_auth, test_org_id):
        link = mint_connect_link(org_id=test_org_id, kind="fake", requested_scopes=[])
        resp = client.get(
            f"/connect/{link.short_code}/callback",
            params={"error": "access_denied"},
        )
        assert resp.status_code == 400
        assert "cancelled" in resp.text.lower() or "access_denied" in resp.text.lower()

    def test_missing_code_renders_error(self, client, user_auth, test_org_id):
        link = mint_connect_link(org_id=test_org_id, kind="fake", requested_scopes=[])
        resp = client.get(f"/connect/{link.short_code}/callback")
        assert resp.status_code == 400

    def test_already_consumed_link_410(self, client, user_auth, test_org_id):
        link = mint_connect_link(org_id=test_org_id, kind="fake", requested_scopes=[])
        from src.credentials import consume_connect_link
        consume_connect_link(link.short_code, consumed_by_user_id=1)
        resp = client.get(
            f"/connect/{link.short_code}/callback",
            params={"code": "abc-code"},
        )
        assert resp.status_code == 410
