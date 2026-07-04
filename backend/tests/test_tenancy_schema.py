"""
Tests for the multi-org tenancy foundations (WP1, migration 020):
org_members + OrgMemberRepo, instance_orgs + InstanceRepo.orgs_for_instance,
and the transitional sync triggers.

Hits the real amebo DB (psycopg2 pool), following test_goal_repo.py. Each test
creates and cleans up its own throw-away orgs / users / instances.
"""

from __future__ import annotations

import uuid

import pytest

from src.db.connection import DatabaseConnection
from src.db.repositories.org_member_repo import OrgMemberRepo
from src.db.repositories.instance_repo import InstanceRepo


def _uid() -> str:
    return uuid.uuid4().hex[:12]


@pytest.fixture
def two_orgs():
    """Two throw-away orgs; cleaned up (cascades to memberships/instance_orgs)."""
    conn = DatabaseConnection.get_connection()
    ids = []
    try:
        with conn.cursor() as cur:
            for n in ("A", "B"):
                cur.execute(
                    "INSERT INTO organizations (org_name, org_slug) "
                    "VALUES (%s, %s) RETURNING org_id",
                    (f"Tenancy Org {n}", f"tenancy-{n.lower()}-{_uid()}"),
                )
                ids.append(cur.fetchone()[0])
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)

    yield ids

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM organizations WHERE org_id = ANY(%s)", (ids,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


def _make_user(org_id: int, role: str = "member") -> int:
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO platform_users (org_id, email, password_hash, full_name, role) "
                "VALUES (%s, %s, 'x', 'Test User', %s) RETURNING user_id",
                (org_id, f"tenancy-{_uid()}@example.com", role),
            )
            uid = cur.fetchone()[0]
            conn.commit()
            return uid
    finally:
        DatabaseConnection.return_connection(conn)


def _make_instance(org_id: int | None = None) -> int:
    return InstanceRepo().create(
        name="Tenancy Test Instance",
        slug=f"tenancy-inst-{_uid()}",
        org_id=org_id,
    )["id"]


def _cleanup_instance(instance_id: int) -> None:
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM instances WHERE id = %s", (instance_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


class TestOrgMembers:
    def test_creating_a_user_mirrors_into_org_members(self, two_orgs):
        """The transitional trigger mirrors platform_users.org_id -> membership."""
        org_a, _ = two_orgs
        uid = _make_user(org_a, role="admin")
        rows = OrgMemberRepo().memberships(uid)
        assert [r["org_id"] for r in rows] == [org_a]
        assert rows[0]["role"] == "admin"
        assert rows[0]["source"] == "manual"

    def test_person_in_two_orgs(self, two_orgs):
        """A person can be a member of N orgs; memberships() returns all."""
        org_a, org_b = two_orgs
        uid = _make_user(org_a)
        OrgMemberRepo().add_member(org_b, uid, role="owner")
        got = {r["org_id"]: r["role"] for r in OrgMemberRepo().memberships(uid)}
        assert got == {org_a: "member", org_b: "owner"}

    def test_add_member_is_idempotent_and_updates_role(self, two_orgs):
        org_a, _ = two_orgs
        uid = _make_user(org_a)
        repo = OrgMemberRepo()
        repo.add_member(org_a, uid, role="member")
        repo.add_member(org_a, uid, role="admin")  # re-add promotes role
        rows = repo.memberships(uid)
        assert len(rows) == 1 and rows[0]["role"] == "admin"

    def test_members_of_and_is_member(self, two_orgs):
        org_a, org_b = two_orgs
        uid = _make_user(org_a)
        repo = OrgMemberRepo()
        assert repo.is_member(org_a, uid) is True
        assert repo.is_member(org_b, uid) is False
        assert [m["user_id"] for m in repo.members_of(org_a)] == [uid]

    def test_invalid_source_rejected(self, two_orgs):
        org_a, _ = two_orgs
        uid = _make_user(org_a)
        with pytest.raises(ValueError):
            OrgMemberRepo().add_member(org_a, uid, source="bogus")


class TestInstanceOrgs:
    def test_creating_instance_with_org_mirrors_into_instance_orgs(self, two_orgs):
        org_a, _ = two_orgs
        inst = _make_instance(org_id=org_a)
        try:
            assert InstanceRepo().orgs_for_instance(inst) == [org_a]
        finally:
            _cleanup_instance(inst)

    def test_instance_serving_two_orgs(self, two_orgs):
        org_a, org_b = two_orgs
        repo = InstanceRepo()
        inst = _make_instance(org_id=org_a)
        try:
            repo.add_org(inst, org_b)
            assert sorted(repo.orgs_for_instance(inst)) == sorted([org_a, org_b])
            # get_by_org resolves an instance for EITHER served org
            assert repo.get_by_org(org_a)["id"] == inst
            assert repo.get_by_org(org_b)["id"] == inst
        finally:
            _cleanup_instance(inst)

    def test_add_org_is_idempotent(self, two_orgs):
        org_a, _ = two_orgs
        repo = InstanceRepo()
        inst = _make_instance(org_id=org_a)
        try:
            repo.add_org(inst, org_a)  # already present via trigger
            assert repo.orgs_for_instance(inst) == [org_a]
        finally:
            _cleanup_instance(inst)


class TestAcceptanceScenario:
    """The WP1 acceptance case: a person with two memberships and an instance
    serving two orgs resolve correctly together."""

    def test_two_memberships_and_two_org_instance(self, two_orgs):
        org_a, org_b = two_orgs
        uid = _make_user(org_a)
        OrgMemberRepo().add_member(org_b, uid)
        inst = _make_instance(org_id=org_a)
        try:
            InstanceRepo().add_org(inst, org_b)
            member_orgs = {r["org_id"] for r in OrgMemberRepo().memberships(uid)}
            served_orgs = set(InstanceRepo().orgs_for_instance(inst))
            # candidate orgs for this person on this instance = intersection
            assert member_orgs & served_orgs == {org_a, org_b}
        finally:
            _cleanup_instance(inst)
