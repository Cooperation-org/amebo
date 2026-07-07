"""
_default_notifier behavior: Slack when a channel is configured, log-only
fallback otherwise. Slack calls mocked — no real posts.
"""

from __future__ import annotations

from unittest.mock import patch

from src.services import draft_approval_service as das


class TestDefaultNotifier:
    def test_no_channel_no_env_logs_and_reports_sent(self, monkeypatch):
        monkeypatch.delenv("AMEBO_APPROVALS_CHANNEL", raising=False)
        assert das._default_notifier(None, "msg") is True

    def test_env_channel_posts_to_slack(self, monkeypatch):
        monkeypatch.setenv("AMEBO_APPROVALS_CHANNEL", "#approvals")
        with patch("src.tools.slack_tools.slack_post_impl",
                   return_value="Posted to #approvals (ts=1).") as m:
            assert das._default_notifier(None, "msg") is True
        args = m.call_args.args[0]
        assert args["channel"] == "#approvals"
        assert args["text"] == "msg"

    def test_explicit_channel_beats_env(self, monkeypatch):
        monkeypatch.setenv("AMEBO_APPROVALS_CHANNEL", "#approvals")
        with patch("src.tools.slack_tools.slack_post_impl",
                   return_value="Posted to #other (ts=1).") as m:
            assert das._default_notifier("#other", "msg") is True
        assert m.call_args.args[0]["channel"] == "#other"

    def test_failed_post_returns_false(self, monkeypatch):
        monkeypatch.setenv("AMEBO_APPROVALS_CHANNEL", "#approvals")
        with patch("src.tools.slack_tools.slack_post_impl",
                   return_value="Error: channel not found."):
            assert das._default_notifier(None, "msg") is False

    def test_raising_post_returns_false(self, monkeypatch):
        monkeypatch.setenv("AMEBO_APPROVALS_CHANNEL", "#approvals")
        with patch("src.tools.slack_tools.slack_post_impl",
                   side_effect=RuntimeError("boom")):
            assert das._default_notifier(None, "msg") is False
