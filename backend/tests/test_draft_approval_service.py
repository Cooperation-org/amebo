"""
Tests for the draft-approval gate service. Hits the real amebo DB (psycopg2
pool), following the test_goal_repo.py / test_goal_engine.py pattern: each test
creates and cleans up its own throw-away org.

Migration 015 is FILE-only and not applied to the DB, so a session-scoped
fixture creates the pending_actions table from the migration SQL and DROPs it
afterward. This is fully reversible and never leaves schema behind. If the DB
is unreachable, the whole module is skipped (matching how the suite degrades).

Covered:
  - gated vs free classification through the service
  - create → approve → executed
  - create → reject
  - isolation: one org cannot approve / see / reject another org's action
"""

from __future__ import annotations

import os
import pathlib

import pytest

from src.db.connection import DatabaseConnection
from src.db.repositories.pending_action_repo import PendingActionRepo
from src.services.draft_approval_service import (
    DraftApprovalService, PendingActionNotFound,
)

_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations" / "015_pending_actions.sql"
)


def _db_available() -> bool:
    try:
        conn = DatabaseConnection.get_connection()
    except Exception:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False
    finally:
        try:
            DatabaseConnection.return_connection(conn)
        except Exception:
            pass


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="amebo DB not reachable for pending_actions tests"
)


@pytest.fixture(scope="module", autouse=True)
def pending_actions_table():
    """Create pending_actions from the migration SQL, drop it after the module.

    The migration is idempotent (CREATE TABLE IF NOT EXISTS). We drop on
    teardown so the schema change is not persisted. If the table already exists
    (e.g. the migration was applied), we leave it in place.
    """
    sql = _MIGRATION.read_text()

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_regclass('public.pending_actions') AS t"
            )
            pre_existing = cur.fetchone()[0] is not None
            if not pre_existing:
                cur.execute(sql)
        conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)

    yield

    if pre_existing:
        return  # was already there before us; do not drop someone else's table
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS pending_actions")
        conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


def _make_org(label: str) -> int:
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES (%s, %s || md5(random()::text)) RETURNING org_id",
                (f"Draft Gate {label}", f"draft-gate-{label}-"),
            )
            org_id = cur.fetchone()[0]
            conn.commit()
            return org_id
    finally:
        DatabaseConnection.return_connection(conn)


def _drop_org(org_id: int) -> None:
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pending_actions WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


@pytest.fixture
def org_id():
    oid = _make_org("a")
    yield oid
    _drop_org(oid)


@pytest.fixture
def other_org_id():
    oid = _make_org("b")
    yield oid
    _drop_org(oid)


@pytest.fixture
def svc():
    # goal_id stays None in these tests, so the goal_events audit branch is not
    # exercised here (it needs a real goal); the gate's own state machine is.
    return DraftApprovalService(repo=PendingActionRepo())


class TestClassificationThroughService:
    def test_free_action_not_gated(self, svc):
        assert svc.requires_approval("search_knowledge_base") is False

    def test_gated_action_requires_approval(self, svc):
        assert svc.requires_approval("slack_post") is True

    def test_unknown_action_default_denied(self, svc):
        assert svc.requires_approval("mystery_outbound") is True


class TestGateOrExecute:
    def test_free_action_executes_immediately(self, svc, org_id):
        calls = []

        def executor(ctx):
            calls.append(ctx)
            return "ran"

        result = svc.gate_or_execute(
            org_id=org_id,
            action_type="search_knowledge_base",
            acting_identity="amebo:test",
            executor=executor,
        )
        assert result.executed is True
        assert result.gated is False
        assert result.result == "ran"
        assert len(calls) == 1
        # Nothing should have been recorded as pending.
        assert svc.list_pending(org_id) == []

    def test_gated_action_is_held_not_executed(self, svc, org_id):
        ran = []

        def executor(ctx):
            ran.append(ctx)
            return "should not run"

        result = svc.gate_or_execute(
            org_id=org_id,
            action_type="slack_post",
            acting_identity="amebo:test",
            executor=executor,
            target="#general",
            payload={"text": "hello"},
            preview="Post hello to #general",
        )
        assert result.gated is True
        assert result.executed is False
        assert ran == []  # executor was NOT called
        assert result.pending_action is not None
        assert result.pending_action["status"] == "pending"

        pending = svc.list_pending(org_id)
        assert len(pending) == 1
        assert pending[0]["action_type"] == "slack_post"
        assert pending[0]["target"] == "#general"


class TestApproveExecuteReject:
    def test_create_approve_then_executed(self, svc, org_id):
        action = svc.create_pending_action(
            org_id=org_id,
            action_type="slack_post",
            acting_identity="amebo:test",
            target="#general",
            payload={"text": "hi"},
            preview="post hi",
        )
        approved = svc.approve(action["id"], approver="alice@example.com", org_id=org_id)
        assert approved["status"] == "approved"
        assert approved["approver"] == "alice@example.com"
        assert approved["decided_at"] is not None

        # Execute via the pluggable executor.
        ran = []
        final = svc.execute_approved(
            action["id"], org_id, executor=lambda a: ran.append(a) or "sent",
        )
        assert len(ran) == 1
        assert final["status"] == "executed"
        assert final["executed_at"] is not None
        assert final["error"] is None

    def test_create_then_reject(self, svc, org_id):
        action = svc.create_pending_action(
            org_id=org_id,
            action_type="send_email",
            acting_identity="amebo:test",
            target="ceo@example.com",
            preview="email the CEO",
        )
        rejected = svc.reject(
            action["id"], approver="bob@example.com", org_id=org_id,
            reason="not appropriate",
        )
        assert rejected["status"] == "rejected"
        assert rejected["approver"] == "bob@example.com"
        assert rejected["decision_reason"] == "not appropriate"

        # A rejected action cannot be approved or executed.
        with pytest.raises(PendingActionNotFound):
            svc.approve(action["id"], approver="bob@example.com", org_id=org_id)
        with pytest.raises(PendingActionNotFound):
            svc.execute_approved(action["id"], org_id, executor=lambda a: "x")

    def test_double_approve_is_rejected(self, svc, org_id):
        action = svc.create_pending_action(
            org_id=org_id, action_type="slack_post", acting_identity="amebo:test",
        )
        svc.approve(action["id"], approver="alice@example.com", org_id=org_id)
        # Second approve finds nothing pending → raises.
        with pytest.raises(PendingActionNotFound):
            svc.approve(action["id"], approver="alice@example.com", org_id=org_id)

    def test_mark_failed_records_error(self, svc, org_id):
        action = svc.create_pending_action(
            org_id=org_id, action_type="slack_post", acting_identity="amebo:test",
        )
        svc.approve(action["id"], approver="a@example.com", org_id=org_id)

        def boom(_a):
            raise RuntimeError("slack down")

        final = svc.execute_approved(action["id"], org_id, executor=boom)
        assert final["status"] == "failed"
        assert "slack down" in final["error"]


class TestIsolation:
    def test_other_org_cannot_see_or_approve(self, svc, org_id, other_org_id):
        action = svc.create_pending_action(
            org_id=org_id, action_type="slack_post", acting_identity="amebo:test",
            target="#a-only",
        )

        # Other org's pending list must not contain it.
        assert svc.list_pending(other_org_id) == []
        # Owning org sees it.
        assert any(p["id"] == action["id"] for p in svc.list_pending(org_id))

        # Other org cannot fetch it (404-equivalent).
        with pytest.raises(PendingActionNotFound):
            svc.get(action["id"], other_org_id)

        # Other org cannot approve or reject it.
        with pytest.raises(PendingActionNotFound):
            svc.approve(action["id"], approver="intruder@example.com", org_id=other_org_id)
        with pytest.raises(PendingActionNotFound):
            svc.reject(action["id"], approver="intruder@example.com", org_id=other_org_id)

        # And it is still pending and owned by the original org.
        still = svc.get(action["id"], org_id)
        assert still["status"] == "pending"
        assert still["org_id"] == org_id
