"""
Tests for slack_post. Network is mocked — no real Slack calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.tools import slack_tools


@pytest.fixture(autouse=True)
def _bot_token(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")


def _resp(status=200, body=None):
    class _R:
        status_code = status
        text = "ok"
        def json(self_):
            return body or {"ok": True, "channel": "C123", "ts": "1.2"}
    return _R()


class TestArgValidation:
    def test_missing_channel(self):
        out = slack_tools.slack_post_impl({"text": "hi", "mention_user_id": "U1"}, {})
        assert "channel" in out.lower()

    def test_missing_text(self):
        out = slack_tools.slack_post_impl({"channel": "#x", "mention_user_id": "U1"}, {})
        assert "text" in out.lower()

    def test_no_mention_rejected_by_default(self):
        out = slack_tools.slack_post_impl(
            {"channel": "#standup", "text": "hello"},
            {},
        )
        assert "mention_user_id" in out


class TestMentionEnforcement:
    def test_mention_prepended_when_not_present(self):
        captured = {}

        def fake_post(url, json, headers, timeout):
            captured["payload"] = json
            return _resp()

        with patch.object(slack_tools.requests, "post", side_effect=fake_post):
            out = slack_tools.slack_post_impl(
                {"channel": "#x", "text": "hello", "mention_user_id": "UHUUD9ERZ"},
                {},
            )
        assert "Posted to" in out
        assert captured["payload"]["text"].startswith("<@UHUUD9ERZ>")

    def test_mention_not_duplicated_when_present(self):
        captured = {}
        def fake_post(url, json, headers, timeout):
            captured["payload"] = json
            return _resp()
        with patch.object(slack_tools.requests, "post", side_effect=fake_post):
            slack_tools.slack_post_impl(
                {
                    "channel": "#x",
                    "text": "<@UHUUD9ERZ> hello",
                    "mention_user_id": "UHUUD9ERZ",
                },
                {},
            )
        # Should appear exactly once
        assert captured["payload"]["text"].count("<@UHUUD9ERZ>") == 1

    def test_guardrails_can_relax_mention_requirement(self):
        # When the goal explicitly opts out, plain channel posts are OK
        guardrails = SimpleNamespace(slack_require_mention=False)
        with patch.object(slack_tools.requests, "post", return_value=_resp()):
            out = slack_tools.slack_post_impl(
                {"channel": "#fyi", "text": "broadcast"},
                {"guardrails": guardrails},
            )
        assert "Posted to" in out


class TestErrorPaths:
    def test_slack_api_error(self):
        with patch.object(
            slack_tools.requests, "post",
            return_value=_resp(body={"ok": False, "error": "channel_not_found"}),
        ):
            out = slack_tools.slack_post_impl(
                {"channel": "#nope", "text": "hi", "mention_user_id": "U1"},
                {},
            )
        assert "channel_not_found" in out

    def test_http_error(self):
        with patch.object(
            slack_tools.requests, "post",
            return_value=_resp(status=500, body={}),
        ):
            out = slack_tools.slack_post_impl(
                {"channel": "#x", "text": "hi", "mention_user_id": "U1"},
                {},
            )
        assert "HTTP 500" in out

    def test_network_exception(self):
        import requests as r
        with patch.object(
            slack_tools.requests, "post",
            side_effect=r.exceptions.ConnectTimeout("boom"),
        ):
            out = slack_tools.slack_post_impl(
                {"channel": "#x", "text": "hi", "mention_user_id": "U1"},
                {},
            )
        assert "Slack API request failed" in out


class TestThread:
    def test_thread_ts_passed_through(self):
        captured = {}
        def fake_post(url, json, headers, timeout):
            captured["payload"] = json
            return _resp()
        with patch.object(slack_tools.requests, "post", side_effect=fake_post):
            slack_tools.slack_post_impl(
                {
                    "channel": "#x", "text": "reply",
                    "thread_ts": "1234.5678",
                    "mention_user_id": "U1",
                },
                {},
            )
        assert captured["payload"]["thread_ts"] == "1234.5678"
