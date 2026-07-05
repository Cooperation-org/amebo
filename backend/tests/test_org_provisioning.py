"""WP17: provisioning — org from nothing to wired, generically, no code change."""
from __future__ import annotations
import uuid
import pytest
from src.db.connection import DatabaseConnection
from src.db.repositories.instance_repo import InstanceRepo
from src.db.repositories.org_member_repo import OrgMemberRepo
from src.db.repositories.member_tool_account_repo import MemberToolAccountRepo
from src.services.org_provisioning import provision_org


def _uid():
    return uuid.uuid4().hex[:10]


@pytest.fixture(autouse=True)
def _pin_legacy(monkeypatch):
    # scoped env-credential fallback must be pinned before provisioning (Fable)
    monkeypatch.setenv("LEGACY_ENV_ORG_ID", "1")



@pytest.fixture
def bootstrap():
    """A home org + user + instance to provision a NEW org against."""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO organizations (org_name, org_slug) "
                        "VALUES ('Home', 'home-' || md5(random()::text)) RETURNING org_id")
            home = cur.fetchone()[0]
            cur.execute("INSERT INTO platform_users (org_id, email, password_hash, full_name, role) "
                        "VALUES (%s, %s, 'x', 'P', 'member') RETURNING user_id",
                        (home, f"prov-{_uid()}@example.com"))
            uid = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)
    inst = InstanceRepo().create(name="Prov Inst", slug=f"prov-inst-{_uid()}")["id"]
    provisioned = {"slugs": []}
    yield {"home": home, "user_id": uid, "instance_id": inst, "provisioned": provisioned}
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            for s in provisioned["slugs"]:
                cur.execute("DELETE FROM organizations WHERE org_slug = %s", (s,))
            cur.execute("DELETE FROM instances WHERE id = %s", (inst,))
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (home,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


class TestProvisioning:
    def test_dry_run_writes_nothing(self):
        slug = f"dry-{_uid()}"
        out = provision_org(slug, "Dry Org", dry_run=True)
        assert "planned" in out
        # org must not exist
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM organizations WHERE org_slug = %s", (slug,))
                assert cur.fetchone() is None
        finally:
            DatabaseConnection.return_connection(conn)

    def test_provision_fake_org_end_to_end(self, bootstrap):
        slug = f"rtv-{_uid()}"
        bootstrap["provisioned"]["slugs"].append(slug)
        result = provision_org(
            slug, "Raise the Voices", context_repo="/tmp/rtv-repo",
            aliases=["rtv"], instance_id=bootstrap["instance_id"],
            members=[{"user_id": bootstrap["user_id"], "role": "owner",
                      "tool_accounts": [{"tool_key": "slack", "external_id": "U999",
                                         "username": "gvelez17"}]}],
        )
        org_id = result["org_id"]
        # org row + context_repo + aliases
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT context_repo, aliases FROM organizations WHERE org_id = %s", (org_id,))
                repo, aliases = cur.fetchone()
                assert repo == "/tmp/rtv-repo" and list(aliases) == ["rtv"]
        finally:
            DatabaseConnection.return_connection(conn)
        # membership
        got = {m["org_id"]: m["role"] for m in OrgMemberRepo().memberships(bootstrap["user_id"])}
        assert got.get(org_id) == "owner"
        # instance serves it
        assert org_id in InstanceRepo().orgs_for_instance(bootstrap["instance_id"])
        # tool account
        assert MemberToolAccountRepo().slack_mention(org_id, bootstrap["user_id"]) == "U999"

    def test_idempotent(self, bootstrap):
        slug = f"idem-{_uid()}"
        bootstrap["provisioned"]["slugs"].append(slug)
        a = provision_org(slug, "Idem", aliases=["i"])
        b = provision_org(slug, "Idem Renamed", aliases=["i", "j"])
        assert a["org_id"] == b["org_id"]  # same org, updated


class TestLegacyPinPrecondition:
    def test_refuses_to_provision_without_legacy_pin(self, monkeypatch):
        monkeypatch.delenv("LEGACY_ENV_ORG_ID", raising=False)
        with pytest.raises(RuntimeError, match="LEGACY_ENV_ORG_ID"):
            provision_org("nope", "Nope")
