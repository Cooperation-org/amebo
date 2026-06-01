"""
Tests for the coding HTTP route (src/api/routes/coding.py).

Mounts the router on a fresh minimal app (no real app startup, no DB) and
overrides the auth + orchestrator dependencies, so these are fast and isolated.
Uses the same httpx.ASGITransport sync shim as the other API tests here.
"""

import asyncio
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.auth_utils import get_current_user
from src.api.routes import coding
from src.channels.contract import ActionKind, OutboundAction


class _FakeJobs:
    def list_for_session(self, session_id):
        return [{"id": "job-1", "seq": 1, "status": "done", "prompt": "p"}]


class _FakeOrchestrator:
    def __init__(self):
        self.jobs = _FakeJobs()
        self.submitted = []

    def submit(self, source_type, source_ref, prompt, workspace_id=None, model_hint=None):
        self.submitted.append({"source_ref": source_ref, "prompt": prompt, "hint": model_hint})
        return {"session": {"id": "sess-1"}, "job": {"id": "job-1", "seq": 1}}

    def drain(self, max_jobs=100):
        return [OutboundAction(kind=ActionKind.REPLY, text="[stub] ran: hi", thread_ref="ref-1")]


def _sync_client(app):
    transport = httpx.ASGITransport(app=app)

    class _Sync:
        def _req(self, method, path, **kw):
            async def go():
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
                    return await ac.request(method, path, **kw)
            return asyncio.run(go())

        def get(self, p, **kw):
            return self._req("GET", p, **kw)

        def post(self, p, **kw):
            return self._req("POST", p, **kw)

    return _Sync()


@pytest.fixture
def fake():
    return _FakeOrchestrator()


@pytest.fixture
def client(fake):
    app = FastAPI()
    app.include_router(coding.router, prefix="/api/coding")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "org_id": 1, "role": "admin"}
    app.dependency_overrides[coding.get_orchestrator] = lambda: fake
    return _sync_client(app)


def test_post_message_runs_and_returns_results(client, fake):
    resp = client.post("/api/coding/message", json={"source_ref": "ref-1", "prompt": "hi"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == "sess-1"
    assert body["job_id"] == "job-1"
    assert body["seq"] == 1
    assert body["ran"] is True
    assert len(body["results"]) == 1
    assert "stub" in body["results"][0]["text"]
    assert fake.submitted[0]["prompt"] == "hi"


def test_post_message_no_run_enqueues_only(client, fake):
    resp = client.post("/api/coding/message", json={"source_ref": "ref-1", "prompt": "later", "run": False})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ran"] is False
    assert body["results"] == []
    assert fake.submitted[0]["prompt"] == "later"


def test_post_message_passes_model_hint(client, fake):
    client.post("/api/coding/message", json={"source_ref": "r", "prompt": "fix", "model_hint": "haiku"})
    assert fake.submitted[0]["hint"] == "haiku"


def test_post_message_validates_required_fields(client):
    resp = client.post("/api/coding/message", json={"source_ref": "ref-1"})
    assert resp.status_code == 422


def test_list_session_jobs(client):
    resp = client.get("/api/coding/sessions/sess-1/jobs")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == "sess-1"
    assert body["jobs"][0]["status"] == "done"


def test_message_requires_auth():
    # No auth override -> the real get_current_user rejects an unauthenticated call.
    app = FastAPI()
    app.include_router(coding.router, prefix="/api/coding")
    app.dependency_overrides[coding.get_orchestrator] = lambda: _FakeOrchestrator()
    resp = _sync_client(app).post("/api/coding/message", json={"source_ref": "r", "prompt": "p"})
    assert resp.status_code in (401, 403)
