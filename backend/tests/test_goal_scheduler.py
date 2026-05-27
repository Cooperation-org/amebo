"""
Tests for GoalScheduler. We exercise the synchronous tick() path with a
mock dispatcher, and verify that:

- Only orgs whose instance has `goal_mode == "enabled"` are scanned.
- Trigger evaluation respects manual / event / cron / unspecified.
- Each dispatched goal goes through the injected dispatcher exactly once.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.db.connection import DatabaseConnection
from src.db.repositories.goal_repo import GoalRepo
from src.services.goal_dispatcher import DispatchResult
from src.services.goal_engine import GoalEngine
from src.services.goal_scheduler import GoalScheduler, _should_fire


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def org_with_enabled_instance():
    """Create an org + an instance with goal_mode enabled. Yield org_id."""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES ('Sched Test', 'sched-test-' || md5(random()::text)) "
                "RETURNING org_id"
            )
            org_id = cur.fetchone()[0]
            import json
            cur.execute(
                "INSERT INTO instances (name, slug, org_id, config) "
                "VALUES (%s, %s, %s, %s::jsonb)",
                ("Sched Test Inst", f"sched-test-inst-{org_id}", org_id,
                 json.dumps({"goal_mode": "enabled"})),
            )
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)

    yield org_id

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM goals WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM instances WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


@pytest.fixture
def org_with_disabled_instance():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES ('Sched Test Off', 'sched-test-off-' || md5(random()::text)) "
                "RETURNING org_id"
            )
            org_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO instances (name, slug, org_id, config) "
                "VALUES (%s, %s, %s, '{}'::jsonb)",
                ("Sched Test Off Inst", f"sched-test-off-inst-{org_id}", org_id),
            )
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)

    yield org_id

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM goals WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM instances WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


@pytest.fixture
def engine():
    return GoalEngine(GoalRepo())


def _make_dispatcher_mock():
    d = MagicMock()
    d.dispatch.return_value = DispatchResult(
        goal_id="x", status="completed", summary="ok",
    )
    return d


# ---------------------------------------------------------------------------
# _should_fire
# ---------------------------------------------------------------------------


class TestShouldFire:
    NOW = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)

    def test_no_trigger_fires_immediately(self):
        assert _should_fire({"trigger_config": None,
                             "updated_at": self.NOW}, now=self.NOW) is True

    def test_manual_never_fires(self):
        g = {"trigger_config": {"type": "manual"}, "updated_at": self.NOW}
        assert _should_fire(g, now=self.NOW) is False

    def test_event_does_not_fire_from_ticker(self):
        g = {"trigger_config": {"type": "event", "event": "x"},
             "updated_at": self.NOW}
        assert _should_fire(g, now=self.NOW) is False

    def test_unknown_type_does_not_fire(self):
        g = {"trigger_config": {"type": "bogus"}, "updated_at": self.NOW}
        assert _should_fire(g, now=self.NOW) is False

    def test_cron_fires_when_due(self):
        # cron every minute; last seen 5 minutes ago => due
        g = {
            "trigger_config": {"type": "cron", "expression": "* * * * *"},
            "updated_at": self.NOW - timedelta(minutes=5),
        }
        assert _should_fire(g, now=self.NOW) is True

    def test_cron_does_not_fire_when_not_due(self):
        # cron every day at midnight; last seen 5 minutes ago at noon => not due
        g = {
            "trigger_config": {"type": "cron", "expression": "0 0 * * *"},
            "updated_at": self.NOW - timedelta(minutes=5),
        }
        assert _should_fire(g, now=self.NOW) is False

    def test_invalid_cron_does_not_fire(self):
        g = {
            "trigger_config": {"type": "cron", "expression": "not a cron"},
            "updated_at": self.NOW,
        }
        assert _should_fire(g, now=self.NOW) is False


# ---------------------------------------------------------------------------
# tick()
# ---------------------------------------------------------------------------


class TestTick:
    def test_tick_dispatches_pending_goal_for_enabled_org(
        self, engine, org_with_enabled_instance,
    ):
        g = engine.create_goal(org_with_enabled_instance, "auto goal")
        dispatcher = _make_dispatcher_mock()
        scheduler = GoalScheduler(dispatcher=dispatcher)

        count = scheduler.tick()

        assert count == 1
        dispatcher.dispatch.assert_called_once_with(g["id"])

    def test_tick_ignores_disabled_org(
        self, engine, org_with_disabled_instance,
    ):
        engine.create_goal(org_with_disabled_instance, "should be ignored")
        dispatcher = _make_dispatcher_mock()
        scheduler = GoalScheduler(dispatcher=dispatcher)

        count = scheduler.tick()

        assert count == 0
        dispatcher.dispatch.assert_not_called()

    def test_tick_skips_manual_goals(self, engine, org_with_enabled_instance):
        engine.create_goal(
            org_with_enabled_instance, "manual one",
            trigger_config={"type": "manual"},
        )
        dispatcher = _make_dispatcher_mock()
        scheduler = GoalScheduler(dispatcher=dispatcher)

        count = scheduler.tick()
        assert count == 0
        dispatcher.dispatch.assert_not_called()

    def test_tick_swallows_dispatcher_errors(
        self, engine, org_with_enabled_instance,
    ):
        engine.create_goal(org_with_enabled_instance, "boom")

        dispatcher = MagicMock()
        dispatcher.dispatch.side_effect = RuntimeError("boom")
        scheduler = GoalScheduler(dispatcher=dispatcher)

        # Tick should not raise; the failed goal is not counted as dispatched.
        count = scheduler.tick()
        assert count == 0
        dispatcher.dispatch.assert_called_once()
