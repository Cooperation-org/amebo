"""
Tests for the cohort-dash auth surface (PLAN-cohort-dash.md, "This repo"):

1. Session cookie — the session JWT is mirrored into an HttpOnly cookie at
   OIDC callback and token refresh, and accepted as a FALLBACK credential
   by get_current_user / get_service_or_user (Authorization header always
   takes precedence).
2. AuthGate — requests stamped ``X-Amebo-Edge: public`` by nginx pass the
   gate with the session cookie alone.
3. GET /api/organizations/links — reachable with a service X-API-Key (org
   resolved from the key's org_id) as well as with a user JWT or the
   session cookie.
4. CORS — origins come from the CORS_ORIGINS env (workers.vc allowlist)
   and are honored by the app with credentials allowed.

Style follows test_changemaker_endpoints / test_goals_api: httpx ASGI
client (no live server), real amebo DB for org/instance/api_key fixtures,
external services mocked at the smallest boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.api.auth_utils import (
    SESSION_COOKIE_NAME,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from src.db.connection import DatabaseConnection


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    from src.api.main import app as fastapi_app
    return fastapi_app


@pytest.fixture(autouse=True)
def _clear_rate_limits():
    """Keep the in-memory rate limiter from coupling tests to suite order
    (auth endpoints allow 20 req/60s per IP; the whole suite shares one IP)."""
    from src.api.middleware.rate_limit import get_rate_limit_store
    get_rate_limit_store()._requests.clear()
    yield


@pytest.fixture
def client(app):
    """Async httpx client backed by an ASGI transport (sync façade)."""
    transport = httpx.ASGITransport(app=app)

    class _Sync:
        def _req(self, method, path, **kw):
            async def go():
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as ac:
                    return await ac.request(method, path, **kw)
            return asyncio.run(go())

        def get(self, p, **kw):
            return self._req("GET", p, **kw)

        def post(self, p, **kw):
            return self._req("POST", p, **kw)

        def options(self, p, **kw):
            return self._req("OPTIONS", p, **kw)

    return _Sync()


@pytest.fixture
def two_orgs():
    """Two real orgs with distinct dashboard links, plus a service API key
    bound to the SECOND org — so tests can prove each credential resolves
    its OWN org, not a client-supplied one."""
    suffix = secrets.token_hex(6)
    raw_key = f"ak_test_{secrets.token_urlsafe(24)}"
    links1 = [{"label": "CRM", "url": "https://crm.example.test"}]
    links2 = [{"label": "Marten", "url": "https://marten.example.test"}]

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) VALUES "
                "('Dash Test One', %s) RETURNING org_id",
                (f"dash-test-1-{suffix}",),
            )
            org1 = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) VALUES "
                "('Dash Test Two', %s) RETURNING org_id",
                (f"dash-test-2-{suffix}",),
            )
            org2 = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO platform_users (org_id, email, password_hash, role) "
                "VALUES (%s, %s, 'x', 'member') RETURNING user_id",
                (org1, f"dash-test-{suffix}@example.test"),
            )
            user_id = cur.fetchone()[0]
            for org, links in ((org1, links1), (org2, links2)):
                cur.execute(
                    "INSERT INTO instances (name, slug, org_id, config) "
                    "VALUES (%s, %s, %s, %s)",
                    (f"dash-test-{org}", f"dash-test-{org}-{suffix}",
                     org, json.dumps({"links": links})),
                )
            cur.execute(
                "INSERT INTO api_keys (org_id, key_name, key_hash, key_prefix, "
                "permissions, created_by) VALUES (%s, %s, %s, %s, %s, %s)",
                (org2, f"dash-test-key-{suffix}",
                 hashlib.sha256(raw_key.encode()).hexdigest(),
                 raw_key[:12], json.dumps(["read"]), user_id),
            )
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)

    token1 = create_access_token({
        "user_id": user_id, "org_id": org1,
        "email": f"dash-test-{suffix}@example.test", "role": "member",
    })
    token2 = create_access_token({
        "user_id": user_id, "org_id": org2,
        "email": f"dash-test-{suffix}@example.test", "role": "member",
    })

    yield {
        "org1": org1, "org2": org2, "links1": links1, "links2": links2,
        "token1": token1, "token2": token2, "api_key": raw_key,
    }

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM api_keys WHERE org_id IN (%s, %s)", (org1, org2))
            cur.execute("DELETE FROM instances WHERE org_id IN (%s, %s)", (org1, org2))
            cur.execute("DELETE FROM platform_users WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM organizations WHERE org_id IN (%s, %s)", (org1, org2))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


def _session_cookies(headers) -> dict:
    """Parse the amebo session Set-Cookie (if any) into {value, attrs}."""
    for raw in headers.get_list("set-cookie"):
        first, _, rest = raw.partition(";")
        name, _, value = first.strip().partition("=")
        if name == SESSION_COOKIE_NAME:
            attrs = {
                p.strip().partition("=")[0].lower(): p.strip().partition("=")[2]
                for p in rest.split(";") if p.strip()
            }
            return {"value": value, "attrs": attrs}
    return {}


# ---------------------------------------------------------------------------
# 1a. Session cookie is SET at OIDC callback and token refresh
# ---------------------------------------------------------------------------


class TestSessionCookieIssued:

    def test_oidc_callback_sets_session_cookie(self, client):
        ident = MagicMock(sub="lt-sub-1", email="cookie@example.test", name="Cookie U")
        user_row = {"user_id": 7, "org_id": 13, "email": "cookie@example.test",
                    "role": "member", "is_active": True}

        db = MagicMock()
        cur = db.get_connection.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = user_row

        tx = create_access_token(
            {"oidc_state": "st1", "oidc_nonce": "n1", "oidc_verifier": "v1"})

        with patch("src.api.routes.auth.OidcConfig") as Cfg, \
             patch("src.api.routes.auth.exchange_code") as ex, \
             patch("src.api.routes.auth.verify_id_token") as vt, \
             patch("src.api.routes.auth.DatabaseConnection", db), \
             patch("src.db.repositories.person_identity_repo.PersonIdentityRepo"):
            Cfg.from_env.return_value = MagicMock(issuer="https://idp.example.test")
            ex.return_value = {"id_token": "idt"}
            vt.return_value = ident

            resp = client.get(
                "/api/auth/oidc/callback",
                params={"code": "abc", "state": "st1"},
                cookies={"amebo_oidc_tx": tx},
            )

        assert resp.status_code == 302
        assert "/auth/callback#access_token=" in resp.headers["location"]

        cookie = _session_cookies(resp.headers)
        assert cookie, "session cookie was not set at OIDC callback"
        attrs = cookie["attrs"]
        assert "httponly" in attrs
        assert "secure" in attrs
        assert attrs.get("samesite", "").lower() == "lax"
        assert attrs.get("path") == "/"
        payload = decode_token(cookie["value"])
        assert payload["type"] == "access"
        assert payload["user_id"] == 7
        assert payload["org_id"] == 13

    def test_refresh_sets_session_cookie(self, client):
        user_row = {"user_id": 7, "org_id": 13, "email": "cookie@example.test",
                    "role": "member", "is_active": True}
        db = MagicMock()
        cur = db.get_connection.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = user_row

        with patch("src.api.routes.auth.DatabaseConnection", db):
            resp = client.post(
                "/api/auth/refresh",
                json={"refresh_token": create_refresh_token({"user_id": 7})},
            )

        assert resp.status_code == 200
        cookie = _session_cookies(resp.headers)
        assert cookie, "session cookie was not set at token refresh"
        assert cookie["value"] == resp.json()["access_token"]
        assert "httponly" in cookie["attrs"]


# ---------------------------------------------------------------------------
# 1c. OIDC login chaining: allowlisted ``next`` redirect after callback
# ---------------------------------------------------------------------------

NEXT_ALLOWLIST = "https://workers.vc,https://www.workers.vc"


class TestOidcNextRedirect:

    def _callback(self, client, next_value):
        """Run the mocked OIDC callback with oidc_next in the tx cookie."""
        ident = MagicMock(sub="lt-sub-2", email="next@example.test", name="Next U")
        user_row = {"user_id": 8, "org_id": 14, "email": "next@example.test",
                    "role": "member", "is_active": True}
        db = MagicMock()
        cur = db.get_connection.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = user_row

        claims = {"oidc_state": "st2", "oidc_nonce": "n2", "oidc_verifier": "v2"}
        if next_value is not None:
            claims["oidc_next"] = next_value
        tx = create_access_token(claims)

        with patch("src.api.routes.auth.OidcConfig") as Cfg, \
             patch("src.api.routes.auth.exchange_code") as ex, \
             patch("src.api.routes.auth.verify_id_token") as vt, \
             patch("src.api.routes.auth.DatabaseConnection", db), \
             patch("src.db.repositories.person_identity_repo.PersonIdentityRepo"):
            Cfg.from_env.return_value = MagicMock(issuer="https://idp.example.test")
            ex.return_value = {"id_token": "idt"}
            vt.return_value = ident
            return client.get(
                "/api/auth/oidc/callback",
                params={"code": "abc", "state": "st2"},
                cookies={"amebo_oidc_tx": tx},
            )

    def test_allowlisted_next_is_honored_without_token_fragment(self, client, monkeypatch):
        monkeypatch.setenv("OIDC_NEXT_ALLOWED_ORIGINS", NEXT_ALLOWLIST)
        resp = self._callback(client, "https://workers.vc/dash/acme/")
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://workers.vc/dash/acme/"
        # amebo tokens must never be handed to another origin
        assert "access_token" not in resp.headers["location"]
        # the session cookie IS still established
        assert _session_cookies(resp.headers), "session cookie missing on next redirect"

    def test_non_allowlisted_next_falls_back_to_default(self, client, monkeypatch):
        monkeypatch.setenv("OIDC_NEXT_ALLOWED_ORIGINS", NEXT_ALLOWLIST)
        resp = self._callback(client, "https://evil.example/phish")
        assert resp.status_code == 302
        assert "/auth/callback#access_token=" in resp.headers["location"]
        assert "evil.example" not in resp.headers["location"]

    def test_protocol_relative_next_rejected(self, client, monkeypatch):
        monkeypatch.setenv("OIDC_NEXT_ALLOWED_ORIGINS", NEXT_ALLOWLIST)
        resp = self._callback(client, "//evil.example/phish")
        assert resp.status_code == 302
        assert "evil.example" not in resp.headers["location"]
        assert "/auth/callback#access_token=" in resp.headers["location"]

    def test_relative_path_next_goes_to_frontend(self, client):
        from src.api.routes.auth import FRONTEND_URL
        resp = self._callback(client, "/somewhere")
        assert resp.status_code == 302
        assert resp.headers["location"] == f"{FRONTEND_URL}/somewhere"

    def test_absent_next_keeps_default_behavior(self, client):
        resp = self._callback(client, None)
        assert resp.status_code == 302
        assert "/auth/callback#access_token=" in resp.headers["location"]

    def test_login_start_only_stores_valid_next(self, client, monkeypatch):
        monkeypatch.setenv("OIDC_NEXT_ALLOWED_ORIGINS", NEXT_ALLOWLIST)
        with patch("src.api.routes.auth.OidcConfig") as Cfg, \
             patch("src.api.routes.auth.build_authorize_url") as bau:
            Cfg.from_env.return_value = MagicMock()
            bau.return_value = "https://idp.example.test/authorize?x=1"

            ok = client.get("/api/auth/oidc/login",
                            params={"next": "https://workers.vc/dash/"})
            bad = client.get("/api/auth/oidc/login",
                             params={"next": "https://evil.example/"})

        def tx_claims(resp):
            for raw in resp.headers.get_list("set-cookie"):
                name, _, value = raw.partition(";")[0].strip().partition("=")
                if name == "amebo_oidc_tx":
                    return decode_token(value)
            return {}

        assert tx_claims(ok).get("oidc_next") == "https://workers.vc/dash/"
        assert "oidc_next" not in tx_claims(bad)

    def test_http_scheme_next_rejected(self, monkeypatch):
        monkeypatch.setenv("OIDC_NEXT_ALLOWED_ORIGINS", NEXT_ALLOWLIST)
        from src.api.routes.auth import _safe_next_url
        assert _safe_next_url("http://workers.vc/dash/") is None
        assert _safe_next_url("https://workers.vc/dash/") == "https://workers.vc/dash/"
        assert _safe_next_url("") is None
        assert _safe_next_url(None) is None


# ---------------------------------------------------------------------------
# 1b. Cookie accepted as fallback; Authorization header keeps precedence
#     (dependency level — both auth_utils and middleware variants)
# ---------------------------------------------------------------------------


def _make_request(cookies: dict | None = None):
    from starlette.requests import Request
    headers = []
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers.append((b"cookie", cookie_str.encode()))
    return Request({
        "type": "http", "method": "GET", "path": "/",
        "headers": headers, "query_string": b"",
    })


def _bearer(token: str):
    from fastapi.security import HTTPAuthorizationCredentials
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _token(org_id: int) -> str:
    return create_access_token({
        "user_id": 1, "org_id": org_id, "email": "t@example.test", "role": "member"})


class TestCookieFallbackDependency:

    @pytest.mark.parametrize("module", ["auth_utils", "middleware"])
    def test_cookie_accepted_when_no_header(self, module):
        if module == "auth_utils":
            from src.api.auth_utils import get_current_user
        else:
            from src.api.middleware.auth import get_current_user
        req = _make_request({SESSION_COOKIE_NAME: _token(42)})
        user = asyncio.run(get_current_user(req, None))
        assert user["org_id"] == 42

    @pytest.mark.parametrize("module", ["auth_utils", "middleware"])
    def test_header_takes_precedence_over_cookie(self, module):
        if module == "auth_utils":
            from src.api.auth_utils import get_current_user
        else:
            from src.api.middleware.auth import get_current_user
        req = _make_request({SESSION_COOKIE_NAME: _token(2)})
        user = asyncio.run(get_current_user(req, _bearer(_token(1))))
        assert user["org_id"] == 1

    @pytest.mark.parametrize("module", ["auth_utils", "middleware"])
    def test_no_credential_is_401(self, module):
        from fastapi import HTTPException
        if module == "auth_utils":
            from src.api.auth_utils import get_current_user
        else:
            from src.api.middleware.auth import get_current_user
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_current_user(_make_request(), None))
        assert exc.value.status_code == 401

    def test_invalid_cookie_is_401(self):
        from fastapi import HTTPException
        from src.api.middleware.auth import get_current_user
        req = _make_request({SESSION_COOKIE_NAME: "not-a-jwt"})
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_current_user(req, None))
        assert exc.value.status_code == 401

    def test_refresh_token_in_cookie_rejected(self):
        # Only ACCESS tokens are session credentials.
        from fastapi import HTTPException
        from src.api.middleware.auth import get_current_user
        refresh = create_refresh_token({"user_id": 1})
        req = _make_request({SESSION_COOKIE_NAME: refresh})
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_current_user(req, None))
        assert exc.value.status_code == 401

    def test_service_or_user_accepts_cookie_as_user(self):
        from src.api.middleware.auth import get_service_or_user
        req = _make_request({SESSION_COOKIE_NAME: _token(42)})
        client = asyncio.run(get_service_or_user(req, None, None))
        assert client["auth"] == "user"
        assert client["org_id"] == 42

    def test_service_or_user_header_beats_cookie(self):
        from src.api.middleware.auth import get_service_or_user
        req = _make_request({SESSION_COOKIE_NAME: _token(2)})
        client = asyncio.run(get_service_or_user(req, _bearer(_token(1)), None))
        assert client["auth"] == "user"
        assert client["org_id"] == 1


# ---------------------------------------------------------------------------
# 3. /api/organizations/links — user JWT, session cookie, and service key
# ---------------------------------------------------------------------------


class TestLinksEndpointAuth:

    def test_user_jwt_still_works(self, client, two_orgs):
        resp = client.get(
            "/api/organizations/links",
            headers={"Authorization": f"Bearer {two_orgs['token1']}"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"links": two_orgs["links1"]}

    def test_session_cookie_works(self, client, two_orgs):
        resp = client.get(
            "/api/organizations/links",
            cookies={SESSION_COOKIE_NAME: two_orgs["token1"]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"links": two_orgs["links1"]}

    def test_api_key_resolves_the_keys_org(self, client, two_orgs):
        resp = client.get(
            "/api/organizations/links",
            headers={"X-API-Key": two_orgs["api_key"]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"links": two_orgs["links2"]}

    def test_header_org_wins_over_cookie_org(self, client, two_orgs):
        resp = client.get(
            "/api/organizations/links",
            headers={"Authorization": f"Bearer {two_orgs['token1']}"},
            cookies={SESSION_COOKIE_NAME: two_orgs["token2"]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"links": two_orgs["links1"]}

    def test_api_key_wins_over_cookie(self, client, two_orgs):
        resp = client.get(
            "/api/organizations/links",
            headers={"X-API-Key": two_orgs["api_key"]},
            cookies={SESSION_COOKIE_NAME: two_orgs["token1"]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"links": two_orgs["links2"]}

    def test_unauthenticated_is_401(self, client):
        resp = client.get("/api/organizations/links")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2b. AuthGate: public-edge requests authenticated by the session cookie
# ---------------------------------------------------------------------------

EDGE = {"X-Amebo-Edge": "public"}


class TestAuthGateSessionCookie:

    def test_public_edge_without_credentials_is_blocked(self, client):
        resp = client.get("/api/organizations/links", headers=EDGE)
        assert resp.status_code == 401
        assert "Sign in with LinkedTrust" in resp.json()["detail"]

    def test_public_edge_with_session_cookie_passes(self, client, two_orgs):
        resp = client.get(
            "/api/organizations/links",
            headers=EDGE,
            cookies={SESSION_COOKIE_NAME: two_orgs["token1"]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"links": two_orgs["links1"]}

    def test_public_edge_with_garbage_cookie_is_blocked(self, client):
        resp = client.get(
            "/api/organizations/links",
            headers=EDGE,
            cookies={SESSION_COOKIE_NAME: "garbage"},
        )
        assert resp.status_code == 401

    def test_public_edge_with_refresh_token_cookie_is_blocked(self, client):
        resp = client.get(
            "/api/organizations/links",
            headers=EDGE,
            cookies={SESSION_COOKIE_NAME: create_refresh_token({"user_id": 1})},
        )
        assert resp.status_code == 401

    def test_public_edge_with_api_key_passes(self, client, two_orgs):
        resp = client.get(
            "/api/organizations/links",
            headers={**EDGE, "X-API-Key": two_orgs["api_key"]},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 4. CORS origins from env
# ---------------------------------------------------------------------------

WORKERS_ORIGINS = "https://workers.vc,https://www.workers.vc,https://amebo.workers.vc"


class TestCorsOrigins:

    def test_parse_cors_origins(self):
        from src.api.main import parse_cors_origins
        assert parse_cors_origins(WORKERS_ORIGINS) == [
            "https://workers.vc",
            "https://www.workers.vc",
            "https://amebo.workers.vc",
        ]
        # whitespace / empty segments are dropped
        assert parse_cors_origins(" https://a.example ,, https://b.example ") == [
            "https://a.example", "https://b.example"]
        assert parse_cors_origins("") == []
        assert parse_cors_origins(None) == []

    def test_configured_origin_honored_with_credentials(self, client):
        """The running app honors the origins it booted with (from the
        CORS_ORIGINS env / default), with credentials allowed."""
        from src.api.main import cors_origins
        assert cors_origins, "app booted with no CORS origins"
        origin = cors_origins[0]
        resp = client.options(
            "/api/organizations/links",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == origin
        assert resp.headers["access-control-allow-credentials"] == "true"

    def test_workers_vc_origins_honored_from_env(self, monkeypatch):
        """The app built with CORS_ORIGINS=<workers.vc list> allows a
        credentialed preflight from each origin and refuses others."""
        import importlib
        import src.api.main as main_mod

        monkeypatch.setenv("CORS_ORIGINS", WORKERS_ORIGINS)
        try:
            reloaded = importlib.reload(main_mod)
            transport = httpx.ASGITransport(app=reloaded.app)

            def preflight(origin):
                async def go():
                    async with httpx.AsyncClient(
                        transport=transport, base_url="http://testserver"
                    ) as ac:
                        return await ac.options(
                            "/api/organizations/links",
                            headers={
                                "Origin": origin,
                                "Access-Control-Request-Method": "GET",
                            },
                        )
                return asyncio.run(go())

            for origin in WORKERS_ORIGINS.split(","):
                resp = preflight(origin)
                assert resp.status_code == 200, origin
                assert resp.headers["access-control-allow-origin"] == origin
                assert resp.headers["access-control-allow-credentials"] == "true"

            refused = preflight("https://evil.example")
            assert "access-control-allow-origin" not in refused.headers
        finally:
            monkeypatch.delenv("CORS_ORIGINS", raising=False)
            importlib.reload(main_mod)
