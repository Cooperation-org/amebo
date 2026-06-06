"""
Unit tests for the two-authority Credential Helper seam.

These tests are DB-free: they exercise the façade, the env-var store, the
ScopedToken secret-safety contract, isolation, and the no-god-token
property using an in-memory CredentialStore. The DB-backed
ResolverCredentialStore is covered for its isolation key-mapping without
hitting a real database (the resolver call is monkeypatched), so no real
credentials or DB rows are touched.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from src.credentials.credential_helper import (
    CredentialHelper,
    CredentialStore,
    EnvCredentialStore,
    ResolverCredentialStore,
    ScopedToken,
    KIND_DELEGATED,
    KIND_SERVICE,
    delegated_author_uri,
    service_author_uri,
)


# ---------------------------------------------------------------------------
# In-memory store for isolation / selection tests
# ---------------------------------------------------------------------------


class InMemoryStore:
    """
    Minimal CredentialStore keyed exactly the way the helper keys it. If
    the helper ever tried to fetch without a full (authority, team,
    owner_key, system) key, these tests would break — which is the point.
    """

    def __init__(self):
        # key: (authority, str(team), owner_key, system) -> secret value
        self._rows: dict[tuple, str] = {}

    def put(self, *, authority, team, owner_key, system, value, scope=()):
        self._rows[(authority, str(team), owner_key, system)] = (value, tuple(scope))

    def fetch(self, *, authority, team, owner_key, system) -> Optional[ScopedToken]:
        hit = self._rows.get((authority, str(team), owner_key, system))
        if hit is None:
            return None
        value, scope = hit
        if authority == KIND_DELEGATED:
            principal = owner_key.split("user:", 1)[-1]
            identity = delegated_author_uri(principal)
        else:
            identity = service_author_uri(team)
        return ScopedToken(
            _value=value,
            system=system,
            scope=scope,
            acting_identity=identity,
            authority=authority,
        )


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def helper(store):
    return CredentialHelper(store)


# ---------------------------------------------------------------------------
# ScopedToken secret-safety
# ---------------------------------------------------------------------------


class TestScopedTokenSecrecy:
    def test_secret_not_in_repr(self):
        tok = ScopedToken(
            _value="super-secret-token-xyz",
            system="github",
            scope=("repo",),
            acting_identity="amebo:1",
            authority=KIND_SERVICE,
        )
        assert "super-secret-token-xyz" not in repr(tok)
        assert "super-secret-token-xyz" not in str(tok)
        assert "<redacted>" in repr(tok)

    def test_secret_not_in_format_or_log(self):
        tok = ScopedToken(_value="leak-me", system="gmail")
        assert "leak-me" not in f"{tok!r}"
        assert "leak-me" not in f"{tok}"
        assert "leak-me" not in "{}".format(tok)

    def test_reveal_returns_value(self):
        tok = ScopedToken(_value="abc123", system="gmail")
        assert tok.reveal() == "abc123"

    def test_expiry_logic(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        assert ScopedToken(_value="x", system="s", expires_at=past).is_expired
        assert not ScopedToken(_value="x", system="s", expires_at=future).is_expired
        assert not ScopedToken(_value="x", system="s", expires_at=None).is_expired

    def test_has_scope(self):
        tok = ScopedToken(_value="x", system="s", scope=("read", "write"))
        assert tok.has_scope("read")
        assert not tok.has_scope("admin")


# ---------------------------------------------------------------------------
# No god-token: the public API offers no unscoped accessor
# ---------------------------------------------------------------------------


class TestNoGodToken:
    def test_no_unscoped_accessor_methods(self):
        public = [
            name for name, _ in inspect.getmembers(CredentialHelper, inspect.isfunction)
            if not name.startswith("_")
        ]
        # Every getter requires either a principal or a team in its signature.
        getters = [n for n in public if n.startswith("get")]
        assert getters, "expected at least one getter"
        for name in getters:
            sig = inspect.signature(getattr(CredentialHelper, name))
            params = set(sig.parameters) - {"self"}
            assert "system" in params, f"{name} must be system-scoped"
            assert (
                "principal" in params or "team" in params
            ), f"{name} must be owner-scoped (principal or team)"
        # No method named/aliased to return an all-powerful token.
        for bad in ("get_token", "get_any", "get_all", "god_token", "root_token"):
            assert bad not in public

    def test_store_protocol_has_no_unscoped_fetch(self):
        sig = inspect.signature(CredentialStore.fetch)
        params = set(sig.parameters) - {"self"}
        # The store contract itself forces a fully qualified key.
        assert {"authority", "team", "owner_key", "system"}.issubset(params)


# ---------------------------------------------------------------------------
# Isolation: team A cannot read team B; principal X cannot read principal Y
# ---------------------------------------------------------------------------


class TestIsolation:
    def test_service_team_isolation(self, store, helper):
        store.put(authority=KIND_SERVICE, team=1, owner_key="service",
                  system="github", value="team1-secret")
        store.put(authority=KIND_SERVICE, team=2, owner_key="service",
                  system="github", value="team2-secret")

        t1 = helper.get_service("github", team=1)
        t2 = helper.get_service("github", team=2)
        assert t1.reveal() == "team1-secret"
        assert t2.reveal() == "team2-secret"
        # Team 3 has nothing — no fallback to another team.
        assert helper.get_service("github", team=3) is None

    def test_service_does_not_leak_across_system(self, store, helper):
        store.put(authority=KIND_SERVICE, team=1, owner_key="service",
                  system="github", value="gh")
        # Asking for a different system the team hasn't connected -> None.
        assert helper.get_service("gmail", team=1) is None

    def test_delegated_principal_isolation(self, store, helper):
        store.put(authority=KIND_DELEGATED, team=str(EnvHelper.SENT("alice")),
                  owner_key="user:alice", system="gmail", value="alice-secret")
        store.put(authority=KIND_DELEGATED, team=str(EnvHelper.SENT("bob")),
                  owner_key="user:bob", system="gmail", value="bob-secret")

        a = helper.get_delegated("gmail", principal="alice")
        b = helper.get_delegated("gmail", principal="bob")
        assert a.reveal() == "alice-secret"
        assert b.reveal() == "bob-secret"
        # Carol has nothing.
        assert helper.get_delegated("gmail", principal="carol") is None

    def test_delegated_for_team_isolation(self, store, helper):
        store.put(authority=KIND_DELEGATED, team=10, owner_key="user:alice",
                  system="gmail", value="alice-on-team10")
        tok = helper.get_delegated_for_team("gmail", principal="alice", team=10)
        assert tok.reveal() == "alice-on-team10"
        # Wrong team -> no leak.
        assert helper.get_delegated_for_team("gmail", principal="alice", team=11) is None


class EnvHelper:
    """Tiny shim so the delegated-isolation test can reproduce the sentinel
    team key the façade uses for principal-only lookups."""

    @staticmethod
    def SENT(principal: str):
        from src.credentials.credential_helper import _principal_team_sentinel
        return _principal_team_sentinel(principal)


# ---------------------------------------------------------------------------
# Delegated vs service selection + acting identity stamping
# ---------------------------------------------------------------------------


class TestAuthoritySelectionAndIdentity:
    def test_service_token_stamps_team_identity(self, store, helper):
        store.put(authority=KIND_SERVICE, team=7, owner_key="service",
                  system="slack", value="svc")
        tok = helper.get_service("slack", team=7)
        assert tok.authority == KIND_SERVICE
        assert tok.acting_identity == "amebo:7"

    def test_delegated_token_stamps_person_identity(self, store, helper):
        store.put(authority=KIND_DELEGATED, team=10, owner_key="user:dana",
                  system="gmail", value="d")
        tok = helper.get_delegated_for_team("gmail", principal="dana", team=10)
        assert tok.authority == KIND_DELEGATED
        assert tok.acting_identity == "urn:amebo:user:dana"

    def test_acting_identity_delegated(self, helper):
        assert helper.acting_identity(principal="erin") == "urn:amebo:user:erin"

    def test_acting_identity_service(self, helper):
        assert helper.acting_identity(team=3) == "amebo:3"

    def test_acting_identity_requires_exactly_one(self, helper):
        with pytest.raises(ValueError):
            helper.acting_identity()
        with pytest.raises(ValueError):
            helper.acting_identity(principal="erin", team=3)

    def test_blank_inputs_rejected(self, helper):
        with pytest.raises(ValueError):
            helper.get_service("", team=1)
        with pytest.raises(ValueError):
            helper.get_delegated("gmail", principal="")
        with pytest.raises(ValueError):
            helper.get_service("github", team=None)


# ---------------------------------------------------------------------------
# EnvCredentialStore
# ---------------------------------------------------------------------------


class TestEnvStore:
    def test_service_lookup_and_isolation(self):
        env = {
            "AMEBO_CRED__SERVICE__1__SERVICE__GITHUB": "team1-gh",
            "AMEBO_CRED__SERVICE__1__SERVICE__GITHUB__SCOPES": "repo,read:org",
            "AMEBO_CRED__SERVICE__2__SERVICE__GITHUB": "team2-gh",
        }
        helper = CredentialHelper(EnvCredentialStore(environ=env))
        t1 = helper.get_service("github", team=1)
        assert t1.reveal() == "team1-gh"
        assert t1.scope == ("repo", "read:org")
        assert t1.acting_identity == "amebo:1"
        assert helper.get_service("github", team=2).reveal() == "team2-gh"
        # No row for team 99 -> None (no god-var).
        assert helper.get_service("github", team=99) is None

    def test_layered_stores_first_hit_wins(self):
        # Env service secret should be returned even though a (deliberately
        # broken) second store would error if reached.
        env = {"AMEBO_CRED__SERVICE__5__SERVICE__SLACK": "env-wins"}

        class Boom:
            def fetch(self, **kw):
                raise AssertionError("second store should not be consulted on a hit")

        helper = CredentialHelper(EnvCredentialStore(environ=env), Boom())
        assert helper.get_service("slack", team=5).reveal() == "env-wins"

    def test_missing_returns_none_not_raise(self):
        helper = CredentialHelper(EnvCredentialStore(environ={}))
        assert helper.get_service("github", team=1) is None
        assert helper.get_delegated("gmail", principal="x") is None


# ---------------------------------------------------------------------------
# ResolverCredentialStore key mapping (DB call monkeypatched — no real DB)
# ---------------------------------------------------------------------------


class TestResolverStoreMapping:
    def test_service_maps_to_org_and_service_label(self, monkeypatch):
        captured = {}

        class FakeStored:
            access_token = "svc-token"
            kind = "github"
            expires_at = None
            granted_scopes = ("repo",)

        class FakeResolver:
            def __init__(self, org_id, kind, label):
                captured["org_id"] = org_id
                captured["kind"] = kind
                captured["label"] = label

            def get(self):
                return FakeStored()

        monkeypatch.setattr(
            "src.credentials.resolver.CredentialResolver", FakeResolver
        )
        helper = CredentialHelper(ResolverCredentialStore())
        tok = helper.get_service("github", team=42)
        assert captured == {"org_id": 42, "kind": "github", "label": "service"}
        assert tok.reveal() == "svc-token"
        assert tok.acting_identity == "amebo:42"
        assert tok.scope == ("repo",)

    def test_delegated_maps_to_user_label(self, monkeypatch):
        captured = {}

        class FakeStored:
            access_token = "del-token"
            kind = "gmail"
            expires_at = None
            granted_scopes = ()

        class FakeResolver:
            def __init__(self, org_id, kind, label):
                captured.update(org_id=org_id, kind=kind, label=label)

            def get(self):
                return FakeStored()

        monkeypatch.setattr(
            "src.credentials.resolver.CredentialResolver", FakeResolver
        )
        helper = CredentialHelper(ResolverCredentialStore())
        tok = helper.get_delegated_for_team("gmail", principal="alice", team=10)
        assert captured == {"org_id": 10, "kind": "gmail", "label": "user:alice"}
        assert tok.acting_identity == "urn:amebo:user:alice"

    def test_missing_credential_becomes_none(self, monkeypatch):
        from src.credentials.resolver import CredentialMissing

        class FakeResolver:
            def __init__(self, org_id, kind, label):
                pass

            def get(self):
                raise CredentialMissing(1, "github", "service")

        monkeypatch.setattr(
            "src.credentials.resolver.CredentialResolver", FakeResolver
        )
        helper = CredentialHelper(ResolverCredentialStore())
        assert helper.get_service("github", team=1) is None

    def test_principal_only_delegated_declines_on_db_store(self, monkeypatch):
        # A principal-only get_delegated() carries a sentinel team that the
        # DB store cannot turn into an org_id -> returns None, steering the
        # caller to get_delegated_for_team(). No resolver call is made.
        def boom(*a, **k):
            raise AssertionError("resolver must not be called for sentinel team")

        monkeypatch.setattr("src.credentials.resolver.CredentialResolver", boom)
        helper = CredentialHelper(ResolverCredentialStore())
        assert helper.get_delegated("gmail", principal="alice") is None
