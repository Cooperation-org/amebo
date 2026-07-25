"""
Tests for /api/auth/google.

The Google library's id-token verifier is patched out — we feed it a
fixed payload and check that:
- An unknown email is refused 403 and creates NOTHING (a login never mints an
  org; that comes from a founder's venture or an operator run).
- A returning Google user is matched by (provider, provider_id) and gets a
  new session.
- A user with the same email but different provider history gets their
  Google identity linked.
- Unverified emails are rejected.
- Bad tokens return 401.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict
from unittest.mock import patch

import httpx
import pytest

from src.db.connection import DatabaseConnection


# Set BEFORE the route module imports the Google client id.
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")


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
        def post(self, p, **kw): return self._req("POST", p, **kw)
    return _Sync()


def _clean_user_and_org(email: str):
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, org_id FROM platform_users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
            if row:
                user_id, org_id = row
                cur.execute("DELETE FROM audit_logs WHERE user_id = %s", (user_id,))
                cur.execute("DELETE FROM platform_users WHERE user_id = %s", (user_id,))
                cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
                conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


def _user_row(email: str) -> Dict[str, Any] | None:
    from psycopg2 import extras as pg_extras
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=pg_extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM platform_users WHERE email = %s", (email,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        DatabaseConnection.return_connection(conn)


# ---------------------------------------------------------------------------
# Happy path: new user
# ---------------------------------------------------------------------------


class TestGoogleLoginNewUser:
    EMAIL = "test-google-newuser@example.com"

    def setup_method(self):
        _clean_user_and_org(self.EMAIL)

    def teardown_method(self):
        _clean_user_and_org(self.EMAIL)

    def test_unknown_identity_is_refused_and_mints_nothing(self, client):
        """A login is not a reason to create an org (golda 2026-07-25).

        This used to mint "<name>'s workspace" + an owner row for any verified
        Google identity. Orgs now come only from a founder bringing a venture
        or a deliberate operator/add-team run, so an unknown identity is simply
        told it has no team here — and leaves NO rows behind.
        """
        fake_payload = {
            "sub": "google-sub-newuser-1",
            "email": self.EMAIL,
            "email_verified": True,
            "name": "Test Newuser",
            "picture": "https://example.com/avatar.png",
        }
        with patch(
            "src.auth_oauth.google_login.google_id_token.verify_oauth2_token",
            return_value=fake_payload,
        ):
            resp = client.post("/api/auth/google", json={"id_token": "fake.id.token"})

        assert resp.status_code == 403, resp.text
        assert "not a member of any team" in resp.json()["detail"]
        assert _user_row(self.EMAIL) is None


# ---------------------------------------------------------------------------
# Returning user
# ---------------------------------------------------------------------------


class TestGoogleLoginReturning:
    EMAIL = "test-google-returning@example.com"

    SUB = "google-sub-returning-1"

    def setup_method(self):
        _clean_user_and_org(self.EMAIL)
        # A returning user is by definition already a member — seed the row the
        # way provisioning would (login no longer creates one, see above).
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO organizations (org_name, org_slug) "
                    "VALUES ('Returning Org', 'returning-' || md5(random()::text)) "
                    "RETURNING org_id"
                )
                org_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO platform_users (
                        org_id, email, full_name, role, is_active,
                        email_verified, auth_provider, auth_provider_id
                    ) VALUES (%s, %s, 'Returning User', 'member', true,
                              true, 'google', %s)
                    """,
                    (org_id, self.EMAIL, self.SUB),
                )
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)

    def teardown_method(self):
        _clean_user_and_org(self.EMAIL)

    def test_second_login_finds_existing_user(self, client):
        payload = {
            "sub": self.SUB,
            "email": self.EMAIL,
            "email_verified": True,
            "name": "Returning User",
        }
        with patch(
            "src.auth_oauth.google_login.google_id_token.verify_oauth2_token",
            return_value=payload,
        ):
            r1 = client.post("/api/auth/google", json={"id_token": "fake.id.token"})
            r2 = client.post("/api/auth/google", json={"id_token": "fake.id.token"})

        assert r1.status_code == 200
        assert r2.status_code == 200

        # Only one user row exists for this email.
        from psycopg2 import extras as pg_extras
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=pg_extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT count(*) AS n FROM platform_users WHERE email = %s",
                    (self.EMAIL,),
                )
                assert cur.fetchone()["n"] == 1
        finally:
            DatabaseConnection.return_connection(conn)


# ---------------------------------------------------------------------------
# Link Google identity to a pre-existing (password) user
# ---------------------------------------------------------------------------


class TestGoogleLoginLinking:
    EMAIL = "test-google-linking@example.com"

    def setup_method(self):
        _clean_user_and_org(self.EMAIL)
        # Seed a password-only user with the target email.
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO organizations (org_name, org_slug) "
                    "VALUES ('Existing Org', 'existing-' || md5(random()::text)) "
                    "RETURNING org_id"
                )
                org_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO platform_users (
                        org_id, email, password_hash, full_name,
                        role, auth_provider
                    ) VALUES (%s, %s, 'fake-hash', 'Already Here',
                              'owner', 'password')
                    """,
                    (org_id, self.EMAIL),
                )
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)

    def teardown_method(self):
        _clean_user_and_org(self.EMAIL)

    def test_google_login_links_to_existing_email(self, client):
        payload = {
            "sub": "google-sub-link-1",
            "email": self.EMAIL,
            "email_verified": True,
            "name": "Already Here",
        }
        with patch(
            "src.auth_oauth.google_login.google_id_token.verify_oauth2_token",
            return_value=payload,
        ):
            resp = client.post("/api/auth/google", json={"id_token": "fake.id.token"})

        assert resp.status_code == 200
        row = _user_row(self.EMAIL)
        assert row["auth_provider"] == "google"
        assert row["auth_provider_id"] == "google-sub-link-1"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestGoogleLoginErrors:
    def test_missing_token_and_code(self, client):
        resp = client.post("/api/auth/google", json={})
        assert resp.status_code == 401

    def test_unverified_email_rejected(self, client):
        payload = {
            "sub": "google-sub-x",
            "email": "unverified@example.com",
            "email_verified": False,
        }
        with patch(
            "src.auth_oauth.google_login.google_id_token.verify_oauth2_token",
            return_value=payload,
        ):
            resp = client.post("/api/auth/google", json={"id_token": "fake"})
        assert resp.status_code == 401
        assert "not verified" in resp.text.lower()

    def test_bad_token_returns_401(self, client):
        with patch(
            "src.auth_oauth.google_login.google_id_token.verify_oauth2_token",
            side_effect=ValueError("bad signature"),
        ):
            resp = client.post("/api/auth/google", json={"id_token": "garbage"})
        assert resp.status_code == 401
