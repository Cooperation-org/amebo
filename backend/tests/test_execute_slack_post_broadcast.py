"""execute_slack_post: a channel broadcast (require_mention=False) must reach
slack_post_impl with the mention requirement relaxed; a normal payload must keep
the default (mention required). No network — the real send is monkeypatched."""

from src.tools import gated_actuators
from src.tools import slack_tools


def _capture(monkeypatch):
    seen = {}

    def fake_post(payload, context):
        seen["payload"] = payload
        seen["context"] = context
        return "posted"

    monkeypatch.setattr(slack_tools, "slack_post_impl", fake_post)
    return seen


def test_broadcast_relaxes_mention_requirement(monkeypatch):
    seen = _capture(monkeypatch)
    action = {"payload": {"channel": "#ai-workflow-automations", "text": "digest",
                          "require_mention": False}}
    assert gated_actuators.execute_slack_post(action) == "posted"
    guardrails = seen["context"].get("guardrails")
    assert guardrails is not None and guardrails.slack_require_mention is False


def test_normal_post_keeps_default_context(monkeypatch):
    seen = _capture(monkeypatch)
    action = {"payload": {"channel": "#x", "text": "hi", "mention_user_id": "U1"}}
    assert gated_actuators.execute_slack_post(action) == "posted"
    assert seen["context"] == {}  # default path untouched → mention still required


def test_missing_channel_is_a_clear_error():
    assert gated_actuators.execute_slack_post(
        {"payload": {"text": "no channel"}}).startswith("Error")
