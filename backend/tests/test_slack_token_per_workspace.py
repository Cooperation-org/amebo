"""WP4: Slack bot token resolves per-workspace from the credential store, with
env fallback (no more single global SLACK_BOT_TOKEN)."""
from __future__ import annotations
from unittest.mock import patch
import pytest
from src.tools import slack_tools
from src.tools.slack_tools import _bot_token, _workspace_from_context
from src.services.org_context import OrgContext, Venue


class TestSlackTokenResolution:
    def test_per_workspace_credential_used(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-ENV")
        with patch("src.services.credential_service.CredentialService") as CS:
            CS.return_value.get_credentials.return_value = {"bot_token": "xoxb-WS"}
            assert _bot_token({"workspace_id": "T123"}) == "xoxb-WS"
            CS.return_value.get_credentials.assert_called_once_with("T123")

    def test_env_fallback_when_no_stored_credential(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-ENV")
        with patch("src.services.credential_service.CredentialService") as CS:
            CS.return_value.get_credentials.return_value = None
            assert _bot_token({"workspace_id": "T123"}) == "xoxb-ENV"

    def test_web_workspace_skips_lookup_uses_env(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-ENV")
        with patch("src.services.credential_service.CredentialService") as CS:
            assert _bot_token({"workspace_id": "web-demo"}) == "xoxb-ENV"
            CS.return_value.get_credentials.assert_not_called()

    def test_workspace_from_org_context_venue(self):
        ctx = {"org_context": OrgContext(org_id=1, instance_id=1, actor_type="claw",
                                         venue=Venue(channel_kind="slack", workspace_ref="TXYZ"))}
        assert _workspace_from_context(ctx) == "TXYZ"

    def test_no_token_anywhere_raises(self, monkeypatch):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        with patch("src.services.credential_service.CredentialService") as CS:
            CS.return_value.get_credentials.return_value = None
            with pytest.raises(slack_tools.SlackPostError):
                _bot_token({"workspace_id": "T123"})
