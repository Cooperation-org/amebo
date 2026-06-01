"""
Unit tests for the coding-agent orchestration layer.

No database, no network: the orchestrator's collaborators are injected as
in-memory fakes, so these exercise the logic (session-once, ordering,
serialization, success/error handling, the runner loop) in isolation and fast.
DB-backed integration coverage lives in test_coding_orchestration.py.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.channels.contract import ActionKind
from src.coding.model_router import choose_model
from src.coding.models import Model
from src.coding.orchestrator import CodingOrchestrator
from src.coding.runner import CodingRunner
from src.coding.worker import CodingWorker, StubCodingWorker, WorkerResult


# --------------------------------------------------------------------------
# In-memory fakes (match only the methods the orchestrator calls)
# --------------------------------------------------------------------------

class FakeThreadRepo:
    def __init__(self):
        self._by_ref = {}
        self._next = 1

    def get_or_create_thread(self, source_type, source_ref, workspace_id=None, instance_id=None):
        key = (source_type, source_ref, workspace_id)
        if key not in self._by_ref:
            self._by_ref[key] = {"id": self._next, "source_type": source_type, "source_ref": source_ref}
            self._next += 1
        return self._by_ref[key]


class FakeSessionRepo:
    def __init__(self):
        self._by_thread = {}
        self._by_id = {}
        self._n = 0

    def get_by_thread(self, thread_id):
        return self._by_thread.get(thread_id)

    def get_or_create_session(self, thread_id, model, instance_id=None):
        if thread_id in self._by_thread:
            return self._by_thread[thread_id]
        self._n += 1
        s = {"id": f"sess-{self._n}", "thread_id": thread_id, "model": model,
             "instance_id": instance_id, "sdk_session_id": None, "status": "active"}
        self._by_thread[thread_id] = s
        self._by_id[s["id"]] = s
        return s

    def get_session(self, session_id):
        return self._by_id.get(session_id)

    def attach_sdk_session(self, session_id, sdk_session_id):
        self._by_id[session_id]["sdk_session_id"] = sdk_session_id

    def set_status(self, session_id, status):
        self._by_id[session_id]["status"] = status


class FakeJobRepo:
    """Minimal queue that honors ordering and one-in-flight-per-session."""
    def __init__(self):
        self._jobs = []
        self._n = 0

    def enqueue(self, session_id, prompt, payload=None):
        self._n += 1
        seq = 1 + max([j["seq"] for j in self._jobs if j["session_id"] == session_id], default=0)
        job = {"id": f"job-{self._n}", "session_id": session_id, "seq": seq,
               "prompt": prompt, "payload": payload or {}, "status": "queued",
               "result": None, "error": None, "attempts": 0}
        self._jobs.append(job)
        return job

    def claim_next(self):
        running = {j["session_id"] for j in self._jobs if j["status"] == "running"}
        candidates = [j for j in self._jobs if j["status"] == "queued" and j["session_id"] not in running]
        if not candidates:
            return None
        job = sorted(candidates, key=lambda j: (j["session_id"], j["seq"]))[0]
        job["status"] = "running"
        job["attempts"] += 1
        return job

    def complete(self, job_id, result):
        self._get(job_id).update(status="done", result=result)

    def fail(self, job_id, error):
        self._get(job_id).update(status="error", error=error)

    def list_for_session(self, session_id):
        return sorted([j for j in self._jobs if j["session_id"] == session_id], key=lambda j: j["seq"])

    def _get(self, job_id):
        return next(j for j in self._jobs if j["id"] == job_id)


class BoomWorker(CodingWorker):
    def run(self, session, prompt):
        raise RuntimeError("boom")


def _orch(worker=None):
    return CodingOrchestrator(
        worker=worker or StubCodingWorker(),
        thread_repo=FakeThreadRepo(),
        session_repo=FakeSessionRepo(),
        job_repo=FakeJobRepo(),
    )


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------

def test_submit_reuses_session_and_increments_seq():
    o = _orch()
    a = o.submit("test", "ref-1", "one")
    b = o.submit("test", "ref-1", "two")
    assert a["session"]["id"] == b["session"]["id"]
    assert a["job"]["seq"] == 1 and b["job"]["seq"] == 2


def test_model_chosen_once_at_session_creation():
    o = _orch()
    # First message is mechanical -> cheap tier picked for the session.
    a = o.submit("test", "ref-x", "fix a typo")
    assert a["session"]["model"] == Model.HAIKU.value
    # A later, harder message must NOT change the established session model.
    b = o.submit("test", "ref-x", "now implement the whole auth system")
    assert b["session"]["model"] == Model.HAIKU.value


def test_run_next_success_returns_reply_and_completes_job():
    o = _orch()
    sub = o.submit("test", "ref-2", "do a thing")
    action = o.run_next()
    assert action is not None
    assert action.kind == ActionKind.REPLY
    assert action.thread_ref == "ref-2"
    assert "do a thing" in action.text
    jobs = o.jobs.list_for_session(sub["session"]["id"])
    assert jobs[0]["status"] == "done"
    # sdk_session_id from the stub got persisted on the session.
    assert o.sessions.get_session(sub["session"]["id"])["sdk_session_id"]


def test_run_next_worker_error_is_contained():
    o = _orch(worker=BoomWorker())
    sub = o.submit("test", "ref-3", "explode please")
    action = o.run_next()
    assert action is not None and "failed" in action.text.lower()
    assert o.jobs.list_for_session(sub["session"]["id"])[0]["status"] == "error"


def test_run_next_empty_queue_returns_none():
    assert _orch().run_next() is None


def test_serialization_in_orchestrator_drain_order():
    o = _orch()
    o.submit("test", "ref-4", "first")
    o.submit("test", "ref-4", "second")
    actions = o.drain()
    assert [("first" in a.text, "second" in a.text) for a in actions] == [(True, False), (False, True)]


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

class FakeOrchestrator:
    def __init__(self, batches):
        self._batches = list(batches)

    def drain(self, max_jobs=25):
        return self._batches.pop(0) if self._batches else []


def test_runner_tick_delivers_each_action_in_order():
    from src.channels.contract import OutboundAction
    a1 = OutboundAction(kind=ActionKind.REPLY, text="r1", thread_ref="t")
    a2 = OutboundAction(kind=ActionKind.REPLY, text="r2", thread_ref="t")
    delivered = []
    runner = CodingRunner(orchestrator=FakeOrchestrator([[a1, a2]]), deliver=delivered.append)
    assert runner.tick() == 2
    assert [a.text for a in delivered] == ["r1", "r2"]


def test_runner_tick_empty_returns_zero():
    runner = CodingRunner(orchestrator=FakeOrchestrator([]), deliver=lambda a: None)
    assert runner.tick() == 0


def test_runner_delivery_error_does_not_break_tick():
    from src.channels.contract import OutboundAction
    a = OutboundAction(kind=ActionKind.REPLY, text="r", thread_ref="t")

    def boom(_):
        raise RuntimeError("delivery down")

    runner = CodingRunner(orchestrator=FakeOrchestrator([[a]]), deliver=boom)
    assert runner.tick() == 1  # counted as processed; error swallowed and logged


# --------------------------------------------------------------------------
# Model router (pure)
# --------------------------------------------------------------------------

def test_model_router_unknown_hint_falls_back_to_heuristic():
    assert choose_model("fix typo", hint="bogus-model") == Model.HAIKU.value
    assert choose_model("build a feature", hint="bogus-model") == Model.OPUS.value


def test_model_router_accepts_full_model_id_hint():
    assert choose_model("anything", hint=Model.SONNET.value) == Model.SONNET.value


def test_stub_worker_echoes_prompt_and_makes_session_id():
    res = StubCodingWorker().run({"id": "s1", "model": Model.OPUS.value, "sdk_session_id": None}, "hello world")
    assert isinstance(res, WorkerResult)
    assert "hello world" in res.text
    assert res.sdk_session_id == "stub-s1"
