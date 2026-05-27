"""
Tests for the credentials package.

Hits real DB rows (real org_credentials table) but never talks to a real
OAuth provider — uses the fake adapter for refresh and the requests
library is mocked for the client tests.

The encryption key is overridden per test module so we don't depend on
or interfere with any deployed key.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from cryptography.fernet import Fernet

from src.db.connection import DatabaseConnection
from src.credentials import (
    CredentialResolver,
    CredentialMissing,
    CredentialExpired,
    client,
)
from src.credentials import encryption


# ---------------------------------------------------------------------------
# Set a test key BEFORE any encryption usage in this module.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def _test_encryption_key():
    prior = os.environ.get("AMEBO_CRED_KEY")
    os.environ["AMEBO_CRED_KEY"] = Fernet.generate_key().decode()
    encryption.reset_for_tests()
    yield
    if prior is None:
        os.environ.pop("AMEBO_CRED_KEY", None)
    else:
        os.environ["AMEBO_CRED_KEY"] = prior
    encryption.reset_for_tests()


@pytest.fixture
def test_org_id():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES ('Cred Test', 'cred-test-' || md5(random()::text)) "
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
            cur.execute("DELETE FROM org_credentials WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


# ---------------------------------------------------------------------------
# Encryption module
# ---------------------------------------------------------------------------


class TestEncryption:
    def test_round_trip(self):
        blob = encryption.encrypt_json({"access_token": "abc", "extra": [1, 2]})
        assert isinstance(blob, bytes)
        decoded = encryption.decrypt_json(blob)
        assert decoded == {"access_token": "abc", "extra": [1, 2]}

    def test_decrypt_with_wrong_key_raises(self):
        blob = encryption.encrypt_json({"x": 1})
        os.environ["AMEBO_CRED_KEY"] = Fernet.generate_key().decode()
        encryption.reset_for_tests()
        from src.credentials.encryption import CredentialEncryptionError
        with pytest.raises(CredentialEncryptionError):
            encryption.decrypt_json(blob)

    def test_missing_key_raises(self):
        prior = os.environ.pop("AMEBO_CRED_KEY", None)
        encryption.reset_for_tests()
        try:
            from src.credentials.encryption import CredentialEncryptionError
            with pytest.raises(CredentialEncryptionError):
                encryption.encrypt_json({"x": 1})
        finally:
            if prior:
                os.environ["AMEBO_CRED_KEY"] = prior
            encryption.reset_for_tests()


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class TestResolverFetchPath:
    def test_get_unknown_raises_missing(self, test_org_id):
        r = CredentialResolver(test_org_id, kind="fake")
        with pytest.raises(CredentialMissing):
            r.get()

    def test_store_then_get(self, test_org_id):
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        CredentialResolver.store_new(
            org_id=test_org_id,
            kind="fake",
            access_token="abc",
            refresh_token="refresh-abc",
            expires_at=expires,
            granted_scopes=["scope1", "scope2"],
        )
        cred = CredentialResolver(test_org_id, kind="fake").get()
        assert cred.access_token == "abc"
        assert "scope1" in cred.granted_scopes

    def test_revoked_credential_is_missing(self, test_org_id):
        CredentialResolver.store_new(
            org_id=test_org_id, kind="fake", access_token="abc",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        ok = CredentialResolver.revoke(test_org_id, "fake")
        assert ok is True

        with pytest.raises(CredentialMissing):
            CredentialResolver(test_org_id, kind="fake").get()


class TestResolverRefresh:
    def test_pre_flight_refresh_when_expiring(self, test_org_id):
        # Store an already-expiring credential
        expires = datetime.now(timezone.utc) + timedelta(seconds=10)
        CredentialResolver.store_new(
            org_id=test_org_id, kind="fake",
            access_token="initial",
            refresh_token="r",
            expires_at=expires,
        )
        cred = CredentialResolver(test_org_id, kind="fake").get()
        # Fake adapter appends "-r" to the token on refresh
        assert cred.access_token == "initial-r"
        # Expiry has been pushed out
        assert cred.expires_at and cred.expires_at > datetime.now(timezone.utc) + timedelta(minutes=10)

    def test_no_refresh_when_fresh(self, test_org_id):
        expires = datetime.now(timezone.utc) + timedelta(hours=2)
        CredentialResolver.store_new(
            org_id=test_org_id, kind="fake",
            access_token="fresh", refresh_token="r", expires_at=expires,
        )
        cred = CredentialResolver(test_org_id, kind="fake").get()
        assert cred.access_token == "fresh"

    def test_no_refresh_for_unbounded_token(self, test_org_id):
        CredentialResolver.store_new(
            org_id=test_org_id, kind="fake",
            access_token="long-lived", expires_at=None,
        )
        cred = CredentialResolver(test_org_id, kind="fake").get()
        assert cred.access_token == "long-lived"

    def test_refresh_failure_marks_revoked_and_raises_expired(self, test_org_id):
        CredentialResolver.store_new(
            org_id=test_org_id, kind="fake",
            access_token="x", refresh_token="r",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=10),
        )
        with patch("src.credentials.adapters.fake_adapter.FakeAdapter.refresh",
                   side_effect=RuntimeError("boom")):
            with pytest.raises(CredentialExpired):
                CredentialResolver(test_org_id, kind="fake").get()

        # Subsequent attempts should see no active credential.
        with pytest.raises(CredentialMissing):
            CredentialResolver(test_org_id, kind="fake").get()


class TestResolverAdminAPI:
    def test_store_new_upserts(self, test_org_id):
        id1 = CredentialResolver.store_new(
            org_id=test_org_id, kind="fake", access_token="v1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        id2 = CredentialResolver.store_new(
            org_id=test_org_id, kind="fake", access_token="v2",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert id1 == id2  # same row, updated in place
        cred = CredentialResolver(test_org_id, kind="fake").get()
        assert cred.access_token == "v2"

    def test_list_for_org_excludes_blobs(self, test_org_id):
        CredentialResolver.store_new(
            org_id=test_org_id, kind="fake", access_token="secret",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        rows = CredentialResolver.list_for_org(test_org_id)
        assert len(rows) == 1
        # Confirm no encrypted_value (or any token) appears in the public view.
        assert "encrypted_value" not in rows[0]
        assert "secret" not in str(rows[0])


# ---------------------------------------------------------------------------
# client() wrapper — auth header + 401 retry
# ---------------------------------------------------------------------------


class TestClientWrapper:
    def test_adds_bearer_header(self, test_org_id):
        CredentialResolver.store_new(
            org_id=test_org_id, kind="fake", access_token="abc",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        captured = {}

        def fake_request(self, method, url, **kwargs):
            captured["headers"] = kwargs.get("headers", {})
            resp = MagicMock()
            resp.status_code = 200
            resp.ok = True
            return resp

        with patch("requests.Session.request", new=fake_request):
            with client(test_org_id, "fake") as c:
                c.get("https://api.example.com/x")

        assert captured["headers"]["Authorization"] == "Bearer abc"

    def test_401_triggers_force_refresh_and_retry(self, test_org_id):
        CredentialResolver.store_new(
            org_id=test_org_id, kind="fake", access_token="abc",
            refresh_token="r",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        calls = []

        def fake_request(self, method, url, **kwargs):
            calls.append(kwargs["headers"]["Authorization"])
            resp = MagicMock()
            resp.status_code = 401 if len(calls) == 1 else 200
            resp.ok = (resp.status_code == 200)
            return resp

        with patch("requests.Session.request", new=fake_request):
            with client(test_org_id, "fake") as c:
                c.get("https://api.example.com/x")

        assert len(calls) == 2
        # First call uses the original token; second uses the refreshed one.
        assert calls[0] == "Bearer abc"
        assert calls[1] == "Bearer abc-r"

    def test_persistent_401_does_not_loop(self, test_org_id):
        CredentialResolver.store_new(
            org_id=test_org_id, kind="fake", access_token="abc",
            refresh_token="r",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        calls = []

        def fake_request(self, method, url, **kwargs):
            calls.append(1)
            resp = MagicMock()
            resp.status_code = 401
            resp.ok = False
            return resp

        with patch("requests.Session.request", new=fake_request):
            with client(test_org_id, "fake") as c:
                resp = c.get("https://api.example.com/x")
                assert resp.status_code == 401

        # Exactly two attempts: the original + one retry.
        assert len(calls) == 2

    def test_client_unknown_credential_raises_missing(self, test_org_id):
        with pytest.raises(CredentialMissing):
            with client(test_org_id, "fake") as c:
                c.get("https://api.example.com/x")
