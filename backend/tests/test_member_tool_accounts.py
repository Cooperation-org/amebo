"""WP13: attribution — resolve a person's handle inside a tool (member_tool_accounts)."""
from __future__ import annotations
import uuid
import pytest
from src.db.connection import DatabaseConnection
from src.db.repositories.member_tool_account_repo import MemberToolAccountRepo


def _uid():
    return uuid.uuid4().hex[:10]


@pytest.fixture
def org_user():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO organizations (org_name, org_slug) "
                        "VALUES ('MTA', 'mta-' || md5(random()::text)) RETURNING org_id")
            org_id = cur.fetchone()[0]
            cur.execute("INSERT INTO platform_users (org_id, email, password_hash, full_name, role) "
                        "VALUES (%s, %s, 'x', 'M', 'member') RETURNING user_id",
                        (org_id, f"mta-{_uid()}@example.com"))
            uid = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)
    yield org_id, uid
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


class TestAttribution:
    def test_link_and_resolve_slack_mention(self, org_user):
        org_id, uid = org_user
        repo = MemberToolAccountRepo()
        repo.link(org_id, uid, "slack", "UHUUD9ERZ", external_username="gvelez17")
        assert repo.slack_mention(org_id, uid) == "UHUUD9ERZ"
        assert repo.external_id(org_id, uid, "slack") == "UHUUD9ERZ"
        assert repo.by_username(org_id, "slack", "gvelez17") == "UHUUD9ERZ"

    def test_unmapped_returns_none(self, org_user):
        org_id, uid = org_user
        assert MemberToolAccountRepo().slack_mention(org_id, uid) is None

    def test_multi_tool(self, org_user):
        org_id, uid = org_user
        repo = MemberToolAccountRepo()
        repo.link(org_id, uid, "slack", "U1")
        repo.link(org_id, uid, "taiga", "434", external_username="amebo")
        assert repo.external_id(org_id, uid, "taiga") == "434"
        assert {a["tool_key"] for a in repo.accounts_for(org_id, uid)} == {"slack", "taiga"}
