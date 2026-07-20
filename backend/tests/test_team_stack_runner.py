"""Tests for the earnkit-runner client (src/services/team_stack_runner.py).

No network: requests.post is monkeypatched at the module under test. The
contract is GovKit-reporter-shaped — unset env is a silent no-op, and no
failure mode ever raises into the caller (provisioning must not break because
the runner is down)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services import team_stack_runner


@pytest.fixture
def posts(monkeypatch):
    made = []

    class _Resp:
        status_code = 202
        text = ""

        def json(self):
            return {"job_id": "j-1"}

    def fake_post(url, **kw):
        made.append((url, kw))
        return _Resp()

    monkeypatch.setattr(team_stack_runner.requests, "post", fake_post)
    return made


def test_posts_job_with_bearer(monkeypatch, posts):
    monkeypatch.setenv("TEAM_RUNNER_URL", "http://127.0.0.1:8946/")
    monkeypatch.setenv("TEAM_RUNNER_TOKEN", "rt-token")
    team_stack_runner.trigger_add_team("sunrise", "Sunrise Co-op")
    assert len(posts) == 1
    url, kw = posts[0]
    assert url == "http://127.0.0.1:8946/run/add-team"
    assert kw["json"] == {"team_slug": "sunrise", "team_name": "Sunrise Co-op"}
    assert kw["headers"]["Authorization"] == "Bearer rt-token"


@pytest.mark.parametrize("missing", ["TEAM_RUNNER_URL", "TEAM_RUNNER_TOKEN", "both"])
def test_unset_env_is_a_noop(monkeypatch, posts, missing):
    monkeypatch.setenv("TEAM_RUNNER_URL", "http://127.0.0.1:8946")
    monkeypatch.setenv("TEAM_RUNNER_TOKEN", "rt-token")
    for var in ("TEAM_RUNNER_URL", "TEAM_RUNNER_TOKEN"):
        if missing in (var, "both"):
            monkeypatch.delenv(var)
    team_stack_runner.trigger_add_team("sunrise", "Sunrise Co-op")
    assert posts == []


def test_runner_refusal_never_raises(monkeypatch):
    monkeypatch.setenv("TEAM_RUNNER_URL", "http://127.0.0.1:8946")
    monkeypatch.setenv("TEAM_RUNNER_TOKEN", "rt-token")

    class _Refuse:
        status_code = 409
        text = "crm-sunrise already exists"

        def json(self):
            return {}

    monkeypatch.setattr(team_stack_runner.requests, "post", lambda *a, **k: _Refuse())
    team_stack_runner.trigger_add_team("sunrise", "Sunrise Co-op")  # must not raise


def test_runner_unreachable_never_raises(monkeypatch):
    monkeypatch.setenv("TEAM_RUNNER_URL", "http://127.0.0.1:8946")
    monkeypatch.setenv("TEAM_RUNNER_TOKEN", "rt-token")

    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(team_stack_runner.requests, "post", boom)
    team_stack_runner.trigger_add_team("sunrise", "Sunrise Co-op")  # must not raise
