"""Approve-executes wiring: approving a pending action runs its registered
executor and transitions it to 'executed'.

Tests the route handler directly (it takes `client` as a kwarg, so we bypass
the Depends/auth + DB harness) with a fake service and a real registry lookup.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from src.api.routes import pending_actions as pa


def _action(status, **over):
    base = {
        "id": "pa-1", "org_id": 7, "instance_id": None, "goal_id": None,
        "action_type": "taiga_create_task", "target": "amebo",
        "payload": {"project": "amebo", "subject": "x", "due_date": "2026-06-20"},
        "preview": "Create Taiga task", "status": status,
        "acting_identity": "amebo:7", "requested_at": datetime.now(timezone.utc),
        "approver": "urn:amebo:user:golda", "executed_at": None,
    }
    base.update(over)
    return base


class FakeService:
    """Records the executor it was handed and simulates execute_approved."""

    def __init__(self):
        self.ran_executor = None

    def approve(self, action_id, approver, org_id):
        return _action("approved")

    def get(self, action_id, org_id):
        return _action("approved")

    def execute_approved(self, action_id, org_id, executor):
        # Prove the route handed us a real executor by running it.
        self.ran_executor = executor
        with patch("src.tools.gated_actuators.run_cli", return_value="Created #99: x"):
            self.result = executor(_action("approved"))
        return _action("executed", executed_at=datetime.now(timezone.utc))


def test_approve_runs_registered_executor_and_marks_executed():
    fake = FakeService()
    with patch.object(pa, "_service", return_value=fake):
        resp = asyncio.run(
            pa.approve_pending_action("pa-1", client={"org_id": 7, "sub": "golda"})
        )
    # The route executed the action via the registered taiga_create_task executor.
    from src.tools.gated_actuators import execute_taiga_create
    assert fake.ran_executor is execute_taiga_create
    assert fake.result == "Created #99: x"
    assert resp.status == "executed"
    assert resp.executed_at is not None


def test_approve_without_executor_leaves_approved():
    """An action type with no registered executor stays 'approved' (not run)."""
    fake = FakeService()

    def approve_unknown(action_id, approver, org_id):
        return _action("approved", action_type="some_unwired_action")
    fake.approve = approve_unknown

    with patch.object(pa, "_service", return_value=fake), \
         patch.object(pa, "get_executor", return_value=None):
        resp = asyncio.run(
            pa.approve_pending_action("pa-1", client={"org_id": 7, "sub": "golda"})
        )
    assert fake.ran_executor is None
    assert resp.status == "approved"
