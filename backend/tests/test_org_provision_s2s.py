"""Tests for the S2S provisioning endpoint (POST /api/orgs/provision).

Route level: mounts the router on a minimal app (same httpx.ASGITransport sync
shim as test_coding_route.py) at the real prefix. DB-backed tests hit the real
amebo DB like test_org_provisioning.py, with unique slugs + cascade cleanup
(platform_users / org_members / member_tool_accounts all cascade from the org).
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.routes import org_provision
from src.db.connection import DatabaseConnection

TOKEN = "test-s2s-token-not-a-secret"


def _uid():
    return uuid.uuid4().hex[:10]


def _auth(token: str = TOKEN):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("AMEBO_S2S_TOKEN", TOKEN)
    # provisioning precondition (see org_provisioning._require_legacy_pin)
    monkeypatch.setenv("LEGACY_ENV_ORG_ID", "1")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(org_provision.router, prefix="/api/orgs")
    transport = httpx.ASGITransport(app=app)

    class _Sync:
        def post(self, path, **kw):
            async def go():
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as ac:
                    return await ac.post(path, **kw)
            return asyncio.run(go())

    return _Sync()


@pytest.fixture
def cleanup():
    """Track provisioned org slugs; deleting the org cascades everything."""
    slugs = []
    yield slugs
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            for s in slugs:
                cur.execute("DELETE FROM organizations WHERE org_slug = %s", (s,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


def _db_one(sql, params):
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        DatabaseConnection.return_connection(conn)


class TestAuth:
    def test_missing_bearer_is_401(self, client):
        r = client.post("/api/orgs/provision", json={"slug": "x"})
        assert r.status_code == 401

    def test_wrong_bearer_is_401(self, client):
        r = client.post("/api/orgs/provision", json={"slug": "x"},
                        headers=_auth("wrong-token"))
        assert r.status_code == 401

    def test_unset_server_token_is_403(self, client, monkeypatch):
        monkeypatch.delenv("AMEBO_S2S_TOKEN", raising=False)
        r = client.post("/api/orgs/provision", json={"slug": "x"},
                        headers=_auth())
        assert r.status_code == 403
        assert "AMEBO_S2S_TOKEN" in r.json()["detail"]


class TestValidation:
    def test_bad_slug_is_422(self, client):
        r = client.post("/api/orgs/provision",
                        json={"slug": "Bad Slug!", "name": "X"},
                        headers=_auth())
        assert r.status_code == 422

    def test_member_without_identifier_is_422(self, client):
        r = client.post(
            "/api/orgs/provision",
            json={"slug": f"v-{_uid()}", "name": "X",
                  "members": [{"display_name": "No Ids"}]},
            headers=_auth())
        assert r.status_code == 422

    def test_new_org_without_name_is_422(self, client):
        r = client.post("/api/orgs/provision",
                        json={"slug": f"noname-{_uid()}"}, headers=_auth())
        assert r.status_code == 422
        assert "name" in r.json()["detail"]


class TestProvision:
    def test_org_only(self, client, cleanup):
        slug = f"s2s-org-{_uid()}"
        cleanup.append(slug)
        r = client.post("/api/orgs/provision",
                        json={"slug": slug, "name": "Org Only",
                              "source": "add-team"},
                        headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["created"] is True and body["members"] == []
        assert _db_one("SELECT org_name FROM organizations WHERE org_id = %s",
                       (body["org_id"],)) == ("Org Only",)

    def test_org_and_member_with_tool_account(self, client, cleanup):
        slug = f"s2s-full-{_uid()}"
        cleanup.append(slug)
        email = f"s2s-{_uid()}@example.com"
        r = client.post(
            "/api/orgs/provision",
            json={"slug": slug, "name": "Full Org", "source": "govkit-accept",
                  "members": [{"email": email, "display_name": "Pat Member",
                               "role": "admin",
                               "tool_accounts": [{"tool_key": "govkit",
                                                  "external_id": "gk-77",
                                                  "username": "pat"}]}]},
            headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["created"] is True
        assert len(body["members"]) == 1 and body["members"][0]["created"] is True
        uid = body["members"][0]["user_id"]
        # platform_users row shaped like the OIDC/invite writers make them
        assert _db_one(
            "SELECT email, full_name, is_active FROM platform_users WHERE user_id = %s",
            (uid,)) == (email, "Pat Member", True)
        # membership with the requested role
        assert _db_one(
            "SELECT role FROM org_members WHERE org_id = %s AND user_id = %s",
            (body["org_id"], uid)) == ("admin",)
        # tool account linked
        assert _db_one(
            "SELECT external_id, external_username FROM member_tool_accounts "
            "WHERE org_id = %s AND user_id = %s AND tool_key = 'govkit'",
            (body["org_id"], uid)) == ("gk-77", "pat")

    def test_idempotent_repost(self, client, cleanup):
        slug = f"s2s-idem-{_uid()}"
        cleanup.append(slug)
        payload = {"slug": slug, "name": "Idem Org", "source": "add-team",
                   "members": [{"email": f"idem-{_uid()}@example.com",
                                "role": "member",
                                "tool_accounts": [{"tool_key": "govkit",
                                                   "external_id": "gk-1"}]}]}
        a = client.post("/api/orgs/provision", json=payload, headers=_auth())
        b = client.post("/api/orgs/provision", json=payload, headers=_auth())
        assert a.status_code == b.status_code == 200
        a, b = a.json(), b.json()
        assert a["org_id"] == b["org_id"]
        assert a["created"] is True and b["created"] is False
        assert a["members"][0]["user_id"] == b["members"][0]["user_id"]
        assert a["members"][0]["created"] is True
        assert b["members"][0]["created"] is False
        # exactly one membership + one tool-account row
        assert _db_one(
            "SELECT COUNT(*) FROM member_tool_accounts WHERE org_id = %s",
            (a["org_id"],)) == (1,)

    def test_member_matched_by_lt_sub(self, client, cleanup):
        slug = f"s2s-sub-{_uid()}"
        cleanup.append(slug)
        sub = f"lt-sub-{_uid()}"
        first = client.post(
            "/api/orgs/provision",
            json={"slug": slug, "name": "Sub Org",
                  "members": [{"lt_sub": sub}]},
            headers=_auth()).json()
        uid = first["members"][0]["user_id"]
        # placeholder email in the OIDC-callback shape, keyed on the subject
        assert _db_one(
            "SELECT email, auth_provider, auth_provider_id "
            "FROM platform_users WHERE user_id = %s",
            (uid,)) == (f"lt-{sub}@users.amebo.local", "linkedtrust", sub)
        # same lt_sub again (now with an email too) matches, does not duplicate
        second = client.post(
            "/api/orgs/provision",
            json={"slug": slug,
                  "members": [{"lt_sub": sub,
                               "email": f"other-{_uid()}@example.com"}]},
            headers=_auth()).json()
        assert second["members"][0] == {"user_id": uid, "created": False}

    def test_member_matched_by_email_links_lt_sub(self, client, cleanup):
        slug = f"s2s-email-{_uid()}"
        cleanup.append(slug)
        email = f"match-{_uid()}@example.com"
        first = client.post(
            "/api/orgs/provision",
            json={"slug": slug, "name": "Email Org",
                  "members": [{"email": email}]},
            headers=_auth()).json()
        uid = first["members"][0]["user_id"]
        # re-provision by the same email, now carrying the lt_sub: matched by
        # email, and the sub is filled in (row had no auth provider yet).
        sub = f"lt-sub-{_uid()}"
        second = client.post(
            "/api/orgs/provision",
            json={"slug": slug, "members": [{"email": email, "lt_sub": sub}]},
            headers=_auth()).json()
        assert second["members"][0] == {"user_id": uid, "created": False}
        assert _db_one(
            "SELECT auth_provider, auth_provider_id FROM platform_users "
            "WHERE user_id = %s", (uid,)) == ("linkedtrust", sub)

    def test_existing_org_name_and_aliases_preserved(self, client, cleanup):
        slug = f"s2s-keep-{_uid()}"
        cleanup.append(slug)
        # seed an org with aliases the way provision_org does
        from src.services.org_provisioning import provision_org
        org_id = provision_org(slug, "Keep Me", aliases=["km"])["org_id"]
        r = client.post("/api/orgs/provision", json={"slug": slug},
                        headers=_auth())
        assert r.status_code == 200
        assert r.json() == {"org_id": org_id, "created": False, "members": []}
        assert _db_one(
            "SELECT org_name, aliases FROM organizations WHERE org_id = %s",
            (org_id,)) == ("Keep Me", ["km"])


class TestTeamStackTrigger:
    """A BRAND-NEW org from a GovKit accept queues the earnkit runner (add-team
    for the rest of the team stack); everything else must never fire it."""

    @pytest.fixture
    def calls(self, monkeypatch):
        made = []
        monkeypatch.setattr(
            org_provision, "trigger_add_team",
            lambda slug, name: made.append((slug, name)))
        return made

    def test_new_org_from_govkit_accept_fires(self, client, cleanup, calls):
        slug = f"s2s-trig-{_uid()}"
        cleanup.append(slug)
        r = client.post("/api/orgs/provision",
                        json={"slug": slug, "name": "Trig Org",
                              "source": "govkit-accept"},
                        headers=_auth())
        assert r.status_code == 200 and r.json()["created"] is True
        assert calls == [(slug, "Trig Org")]

    def test_repost_does_not_refire(self, client, cleanup, calls):
        slug = f"s2s-retrig-{_uid()}"
        cleanup.append(slug)
        payload = {"slug": slug, "name": "Once Org", "source": "govkit-accept"}
        client.post("/api/orgs/provision", json=payload, headers=_auth())
        client.post("/api/orgs/provision", json=payload, headers=_auth())
        assert calls == [(slug, "Once Org")]

    def test_add_team_source_never_fires(self, client, cleanup, calls):
        # add-team.yml registers the org it is provisioning; firing the runner
        # from that would loop.
        slug = f"s2s-noloop-{_uid()}"
        cleanup.append(slug)
        r = client.post("/api/orgs/provision",
                        json={"slug": slug, "name": "Playbook Org",
                              "source": "add-team"},
                        headers=_auth())
        assert r.status_code == 200 and r.json()["created"] is True
        assert calls == []

    def test_sourceless_post_never_fires(self, client, cleanup, calls):
        slug = f"s2s-nosrc-{_uid()}"
        cleanup.append(slug)
        client.post("/api/orgs/provision",
                    json={"slug": slug, "name": "No Source"}, headers=_auth())
        assert calls == []


class TestMemberSyncTrigger:
    """An invite accept into an ALREADY-EXISTING org fires an instant CRM+Taiga
    member reconcile (latency win over the 5-min timer); the founder bootstrap
    and org-only updates must not (add-team already syncs; nothing to sync)."""

    @pytest.fixture
    def calls(self, monkeypatch):
        """Capture both runner triggers so we can assert which one (if any) fired."""
        add_team, sync = [], []
        monkeypatch.setattr(
            org_provision, "trigger_add_team",
            lambda slug, name: add_team.append((slug, name)))
        monkeypatch.setattr(
            org_provision, "sync_members",
            lambda slug: sync.append(slug))
        return {"add_team": add_team, "sync": sync}

    def test_member_accept_into_existing_org_fires_sync(self, client, cleanup, calls):
        slug = f"s2s-sync-{_uid()}"
        cleanup.append(slug)
        # seed the org first, so this POST is an accept into an existing org
        from src.services.org_provisioning import provision_org
        provision_org(slug, "Sync Org")
        r = client.post(
            "/api/orgs/provision",
            json={"slug": slug, "source": "govkit-accept",
                  "members": [{"email": f"acc-{_uid()}@example.com"}]},
            headers=_auth())
        assert r.status_code == 200 and r.json()["created"] is False
        assert calls["sync"] == [slug]
        assert calls["add_team"] == []

    def test_founder_bootstrap_fires_add_team_not_sync(self, client, cleanup, calls):
        # Brand-new org from a founder accept: add-team provisions (and syncs)
        # the whole stack, so sync_members must NOT also fire.
        slug = f"s2s-boot-{_uid()}"
        cleanup.append(slug)
        r = client.post(
            "/api/orgs/provision",
            json={"slug": slug, "name": "Boot Org", "source": "govkit-accept",
                  "members": [{"email": f"founder-{_uid()}@example.com"}]},
            headers=_auth())
        assert r.status_code == 200 and r.json()["created"] is True
        assert calls["add_team"] == [(slug, "Boot Org")]
        assert calls["sync"] == []

    def test_org_only_update_does_not_sync(self, client, cleanup, calls):
        # No members in the request → nothing to reconcile.
        slug = f"s2s-nomem-{_uid()}"
        cleanup.append(slug)
        from src.services.org_provisioning import provision_org
        provision_org(slug, "No Members")
        client.post("/api/orgs/provision",
                    json={"slug": slug, "source": "govkit-accept"},
                    headers=_auth())
        assert calls["sync"] == [] and calls["add_team"] == []

    def test_add_team_self_registration_does_not_sync(self, client, cleanup, calls):
        # add-team.yml self-registers its members; it already syncs in-playbook,
        # so its POST must not queue a redundant sync.
        slug = f"s2s-selfreg-{_uid()}"
        cleanup.append(slug)
        from src.services.org_provisioning import provision_org
        provision_org(slug, "Self Reg")
        client.post(
            "/api/orgs/provision",
            json={"slug": slug, "source": "add-team",
                  "members": [{"email": f"m-{_uid()}@example.com"}]},
            headers=_auth())
        assert calls["sync"] == [] and calls["add_team"] == []


class TestSharedEnvCredentialsMode:
    """Cohort-VM shape (Golda 2026-07-16): ENV_CREDENTIALS_SHARED=true declares
    the process-env credentials shared by all orgs — provisioning must work
    with NO legacy pin, and the fallback scope helper must report shared."""

    def test_provision_works_without_legacy_pin_when_shared(
            self, client, cleanup, monkeypatch):
        monkeypatch.delenv("LEGACY_ENV_ORG_ID", raising=False)
        monkeypatch.setenv("ENV_CREDENTIALS_SHARED", "true")
        slug = f"s2s-shared-{_uid()}"
        cleanup.append(slug)
        r = client.post("/api/orgs/provision",
                        json={"slug": slug, "name": "Shared Env Team"},
                        headers=_auth())
        assert r.status_code == 200
        assert r.json()["created"] is True

    def test_without_shared_mode_missing_pin_still_refuses(
            self, client, cleanup, monkeypatch):
        monkeypatch.delenv("LEGACY_ENV_ORG_ID", raising=False)
        monkeypatch.delenv("ENV_CREDENTIALS_SHARED", raising=False)
        slug = f"s2s-nopin-{_uid()}"
        cleanup.append(slug)
        r = client.post("/api/orgs/provision",
                        json={"slug": slug, "name": "No Pin"},
                        headers=_auth())
        assert r.status_code == 503
        assert "LEGACY_ENV_ORG_ID" in r.json()["detail"]

    def test_env_scope_helper_parses_operator_values(self, monkeypatch):
        from src.credentials.connections import env_credentials_shared
        for raw, expect in [("true", True), ("1", True), ("YES", True),
                            ("false", False), ("", False), ("0", False)]:
            monkeypatch.setenv("ENV_CREDENTIALS_SHARED", raw)
            assert env_credentials_shared() is expect, raw
        monkeypatch.delenv("ENV_CREDENTIALS_SHARED")
        assert env_credentials_shared() is False
