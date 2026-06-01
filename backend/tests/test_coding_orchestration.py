"""
Tests for the coding-agent orchestration layer (src/coding/*).

Exercises, against the real amebo DB (same as other tests here):
- intention thread -> one coding session, jobs ordered by seq,
- Postgres serialization: at most one job per session in flight,
- end-to-end processing with the stub worker, in order,
- dispatch-time model routing.

Each test creates its own thread with a unique source_ref and deletes it
afterwards (cascades to coding_sessions / coding_jobs), so it leaves no residue.
"""

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.coding.model_router import choose_model
from src.coding.models import Model
from src.coding.orchestrator import CodingOrchestrator
from src.db.connection import DatabaseConnection
from src.db.repositories.coding_job_repo import CodingJobRepo


SOURCE_TYPE = "test"


@pytest.fixture
def orch():
    return CodingOrchestrator()  # defaults to StubCodingWorker


@pytest.fixture
def thread_cleanup():
    created = []
    yield created
    if created:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM threads WHERE id = ANY(%s)", (created,))
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)


def _new_ref():
    return f"coding-test-{uuid.uuid4()}"


def test_submit_creates_one_session_and_orders_jobs(orch, thread_cleanup):
    ref = _new_ref()
    r1 = orch.submit(SOURCE_TYPE, ref, "first message")
    thread_cleanup.append(r1["thread"]["id"])
    r2 = orch.submit(SOURCE_TYPE, ref, "second message")

    # Same thread -> same coding session.
    assert r1["session"]["id"] == r2["session"]["id"]
    # Per-session monotonic ordering.
    assert r1["job"]["seq"] == 1
    assert r2["job"]["seq"] == 2


def test_serialization_one_job_in_flight(thread_cleanup):
    orch = CodingOrchestrator()
    ref = _new_ref()
    r1 = orch.submit(SOURCE_TYPE, ref, "msg one")
    thread_cleanup.append(r1["thread"]["id"])
    orch.submit(SOURCE_TYPE, ref, "msg two")

    jobs = CodingJobRepo()
    first = jobs.claim_next()
    assert first is not None and first["seq"] == 1

    # A second claim must NOT start seq 2 while seq 1 is running.
    assert jobs.claim_next() is None

    # Finish seq 1, then seq 2 becomes claimable, in order.
    jobs.complete(first["id"], "ok")
    second = jobs.claim_next()
    assert second is not None and second["seq"] == 2


def test_drain_processes_in_order_with_stub(orch, thread_cleanup):
    ref = _new_ref()
    r1 = orch.submit(SOURCE_TYPE, ref, "alpha")
    thread_cleanup.append(r1["thread"]["id"])
    orch.submit(SOURCE_TYPE, ref, "beta")

    actions = orch.drain()
    assert len(actions) == 2
    # Stub echoes the prompt; order preserved.
    assert "alpha" in actions[0].text
    assert "beta" in actions[1].text

    jobs = CodingJobRepo().list_for_session(r1["session"]["id"])
    assert [j["status"] for j in jobs] == ["done", "done"]


def test_model_routing():
    # Mechanical task -> cheap tier.
    assert choose_model("please fix the typo in the readme") == Model.HAIKU.value
    # Substantive task -> conservative default.
    assert choose_model("implement OAuth login end to end") == Model.OPUS.value
    # Explicit hint wins.
    assert choose_model("anything", hint="haiku") == Model.HAIKU.value
    assert choose_model("fix typo", hint="opus") == Model.OPUS.value
