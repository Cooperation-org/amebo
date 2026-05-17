"""
Tests for the dispatcher's CredentialMissing path and the scheduler's
"skip blocked goals" behavior.

We mock the pursuit step to raise a credential exception, then verify:
- A connect link is minted.
- A blocked_on_credential event is recorded.
- DispatchResult.status == "blocked_on_credential".
- The goal stays in active state (not failed).
- Scheduler.tick skips the goal on subsequent runs until an "unblocked"
  event appears.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet

from src.credentials import CredentialMissing, encryption as cred_encryption
from src.db.connection import DatabaseConnection
from src.db.repositories.goal_repo import GoalRepo
from src.services.goal_dispatcher import GoalDispatcher, DispatchResult
from src.services.goal_engine import GoalEngine
from src.services.goal_scheduler import GoalScheduler


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


@pytest.fixture
def org_with_enabled_instance():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES ('Disp Cred Test', 'disp-cred-' || md5(random()::text)) "
                "RETURNING org_id"
            )
            org_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO instances (name, slug, org_id, config) "
                "VALUES (%s, %s, %s, %s::jsonb)",
                ("Inst", f"inst-{org_id}", org_id,
                 json.dumps({"goal_mode": "enabled"})),
            )
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)

    yield org_id

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM connect_links WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM goals WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM instances WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


@pytest.fixture
def engine():
    return GoalEngine(GoalRepo())


def _make_credential_missing_dispatcher(org_id: int) -> GoalDispatcher:
    """A dispatcher whose pursuit step always raises CredentialMissing(gmail)."""

    class _MissingClient:
        def messages_create(self, *a, **kw):
            raise CredentialMissing(org_id=org_id, kind="gmail")

    class _RaisingDispatcher(GoalDispatcher):
        def _pursue(self, goal, instance, org_context):
            raise CredentialMissing(org_id=goal["org_id"], kind="gmail")

    return _RaisingDispatcher(anthropic_client=None)


# ---------------------------------------------------------------------------
# Dispatcher catches CredentialMissing
# ---------------------------------------------------------------------------


class TestDispatcherCredentialPath:
    def test_credential_missing_returns_blocked(self, engine, org_with_enabled_instance):
        g = engine.create_goal(org_with_enabled_instance, "Send a status email")

        dispatcher = _make_credential_missing_dispatcher(org_with_enabled_instance)
        result = dispatcher.dispatch(g["id"])

        assert isinstance(result, DispatchResult)
        assert result.status == "blocked_on_credential"
        assert "gmail" in (result.summary or "")
        assert "/connect/" in (result.summary or "")

        # Goal NOT marked failed — it stays active (waiting for credential).
        goal_after = engine.get(g["id"])
        assert goal_after["status"] == "active"

        # An event records the block.
        events = engine.events(g["id"])
        actions = [e["action"] for e in events]
        assert any(a == "blocked_on_credential:gmail" for a in actions)

    def test_blocked_event_contains_short_code(self, engine, org_with_enabled_instance):
        g = engine.create_goal(org_with_enabled_instance, "X")
        dispatcher = _make_credential_missing_dispatcher(org_with_enabled_instance)
        dispatcher.dispatch(g["id"])

        events = engine.events(g["id"])
        block_event = next(
            e for e in events if e["action"] == "blocked_on_credential:gmail"
        )
        meta = block_event.get("metadata") or {}
        assert meta.get("kind") == "gmail"
        assert meta.get("short_code")


# ---------------------------------------------------------------------------
# Scheduler skips blocked goals
# ---------------------------------------------------------------------------


class TestSchedulerSkipsBlocked:
    def test_skip_when_most_recent_event_is_block(
        self, engine, org_with_enabled_instance,
    ):
        g = engine.create_goal(org_with_enabled_instance, "blocked one")

        # Pre-block the goal by running the credential-missing dispatcher.
        blocking_dispatcher = _make_credential_missing_dispatcher(org_with_enabled_instance)
        blocking_dispatcher.dispatch(g["id"])

        # Now use a separate scheduler with a different dispatcher that
        # records calls. The blocked goal must NOT be dispatched.
        from unittest.mock import MagicMock
        next_dispatcher = MagicMock()
        scheduler = GoalScheduler(dispatcher=next_dispatcher)

        scheduler.tick()
        next_dispatcher.dispatch.assert_not_called()

    def test_resumes_after_unblocked_event(self, engine, org_with_enabled_instance):
        g = engine.create_goal(org_with_enabled_instance, "to be unblocked")

        blocking_dispatcher = _make_credential_missing_dispatcher(org_with_enabled_instance)
        blocking_dispatcher.dispatch(g["id"])

        # Simulate the OAuth callback's unblock event.
        repo = GoalRepo()
        repo.append_event(
            g["id"], actor_type="system", action="unblocked",
            result_summary="credential gmail connected",
        )

        from unittest.mock import MagicMock
        next_dispatcher = MagicMock()
        next_dispatcher.dispatch.return_value = DispatchResult(
            goal_id=g["id"], status="completed", summary="ok",
        )
        scheduler = GoalScheduler(dispatcher=next_dispatcher)

        scheduler.tick()
        next_dispatcher.dispatch.assert_called_once_with(g["id"])
