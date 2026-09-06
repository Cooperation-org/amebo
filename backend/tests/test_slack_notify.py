"""The claw's one line reaches Slack, and only Slack-shaped channels go there."""
from unittest import mock

from src.services import slack_notify
from src.services.goal_dispatcher import _default_notifier


def test_looks_like_slack():
    assert slack_notify.looks_like_slack("slack:#ai-workflow-automations")
    assert slack_notify.looks_like_slack("#marketing")
    assert slack_notify.looks_like_slack("C0A3UGN864D")
    assert not slack_notify.looks_like_slack("email:golda@example.org")
    assert not slack_notify.looks_like_slack("")


def test_id_passes_through_without_a_lookup():
    with mock.patch.object(slack_notify.requests, "get") as get:
        assert slack_notify.resolve_channel("slack:C0A3UGN864D", token="t") == "C0A3UGN864D"
        get.assert_not_called()


def test_name_resolves_through_the_bots_channel_list_once():
    slack_notify._cache.clear()
    page = mock.Mock()
    page.json.return_value = {"ok": True, "channels": [
        {"name": "ai-workflow-automations", "id": "C0A3UGN864D"}]}
    with mock.patch.object(slack_notify.requests, "get", return_value=page) as get:
        assert slack_notify.resolve_channel("slack:#ai-workflow-automations", token="t") == "C0A3UGN864D"
        assert slack_notify.resolve_channel("#ai-workflow-automations", token="t") == "C0A3UGN864D"
        assert get.call_count == 1


def test_default_notifier_posts_slack_and_logs_the_rest():
    with mock.patch.object(slack_notify, "post", return_value=True) as post, \
         mock.patch.object(slack_notify, "_token", return_value="t"):
        assert _default_notifier("slack:#x", "one line") is True
        post.assert_called_once_with("slack:#x", "one line")
        assert _default_notifier("email:someone", "one line") is True
        assert post.call_count == 1


def test_post_never_raises():
    with mock.patch.object(slack_notify, "_token", side_effect=RuntimeError("no token")):
        assert slack_notify.post("#x", "hi") is False
