"""
Unit tests for coding credential config (env-based, for now).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.coding.config import get_anthropic_credential


def test_prefers_oauth_token_over_api_key(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sub-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xyz")
    cred = get_anthropic_credential()
    assert cred is not None
    assert cred.kind == "oauth_token"
    assert cred.token == "sub-token"


def test_falls_back_to_api_key(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xyz")
    cred = get_anthropic_credential()
    assert cred is not None
    assert cred.kind == "api_key"
    assert cred.token == "sk-ant-xyz"


def test_none_when_unset(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert get_anthropic_credential() is None


def test_sdk_worker_errors_clearly_without_credential(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from src.coding.worker import AgentSdkCodingWorker
    with pytest.raises(RuntimeError, match="No Anthropic credential"):
        AgentSdkCodingWorker().run({"id": "s", "model": "m"}, "do it")
