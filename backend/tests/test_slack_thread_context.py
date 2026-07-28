"""
Tests for Slack thread continuity.

Two things are covered:

1. handle_app_mention keys conversation memory on the THREAD's root ts, not
   on the ts of the individual mention. Without this, every @-mention inside
   a thread starts a blank conversation and amebo loses what was already said.

2. read_slack_thread reads the thread the conversation is in, and degrades
   with a clear message on channels that are not Slack (email, web, claws) —
   the tool context is optional everywhere else.

Network is mocked throughout; no real Slack calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools import slack_tools


@pytest.fixture(autouse=True)
def _slack_tokens(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")


# ---------------------------------------------------------------------------
# handle_app_mention thread keying
# ---------------------------------------------------------------------------


def _qa_stub():
    """A QAService whose answer_question records the kwargs it was given."""
    calls = {}
    service = MagicMock()

    def _answer(**kwargs):
        calls.update(kwargs)
        return {"answer": "an answer", "sources": [], "confidence": 70}

    service.answer_question.side_effect = _answer
    return service, calls


@pytest.mark.asyncio
async def test_mention_in_thread_uses_thread_root():
    """A mention inside an existing thread continues that thread's conversation."""
    from src.services import slack_commands

    service, calls = _qa_stub()
    fake_web = AsyncMock()

    with patch.object(slack_commands, "QAService", return_value=service), \
         patch.object(slack_commands, "AsyncWebClient", return_value=fake_web), \
         patch.object(slack_commands, "_resolve_org_and_instance", return_value=(1, "whatscookin")), \
         patch.object(slack_commands, "_log_slack_query_usage", MagicMock()):
        await slack_commands.handle_app_mention(
            team_id="T1", channel="C1", text="<@UBOT> what about trusthire?",
            user="U1", ts="200.0", thread_ts="100.0",
        )

    # Conversation memory is keyed on the thread root, not this message.
    assert calls["thread_ref"] == "100.0"
    assert calls["conversation"] == {
        "channel_type": "slack",
        "channel_id": "C1",
        "thread_ref": "100.0",
    }
    # And the reply goes into the same thread.
    assert fake_web.chat_postMessage.await_args.kwargs["thread_ts"] == "100.0"


@pytest.mark.asyncio
async def test_top_level_mention_starts_thread_at_own_ts():
    """No thread_ts (a fresh top-level mention) still works: ts is the root."""
    from src.services import slack_commands

    service, calls = _qa_stub()
    fake_web = AsyncMock()

    with patch.object(slack_commands, "QAService", return_value=service), \
         patch.object(slack_commands, "AsyncWebClient", return_value=fake_web), \
         patch.object(slack_commands, "_resolve_org_and_instance", return_value=(1, "whatscookin")), \
         patch.object(slack_commands, "_log_slack_query_usage", MagicMock()):
        await slack_commands.handle_app_mention(
            team_id="T1", channel="C1", text="<@UBOT> hello there question",
            user="U1", ts="300.0",
        )

    assert calls["thread_ref"] == "300.0"
    assert fake_web.chat_postMessage.await_args.kwargs["thread_ts"] == "300.0"


# ---------------------------------------------------------------------------
# read_slack_thread
# ---------------------------------------------------------------------------


def _replies_response(messages):
    class _R:
        status_code = 200
        text = "ok"

        def json(self_):
            return {"ok": True, "messages": messages}

    return _R()


class TestReadSlackThread:
    def test_reads_thread_from_conversation_context(self):
        messages = [
            {"user": "U1", "ts": "100.0", "text": "I built an HR outreach database"},
            {"user": "UBOT", "ts": "101.0", "text": "Which product is this for?"},
        ]
        with patch.object(slack_tools.requests, "get", return_value=_replies_response(messages)), \
             patch.object(slack_tools, "_resolve_slack_names", return_value={"U1": "golda", "UBOT": "amebo"}):
            out = slack_tools.read_slack_thread_impl(
                {},
                {"conversation": {
                    "channel_type": "slack",
                    "channel_id": "C1",
                    "thread_ref": "100.0",
                }},
            )

        assert "HR outreach database" in out
        assert "golda" in out
        assert "2 message(s)" in out

    def test_explicit_channel_and_ts_override_context(self):
        captured = {}

        def _get(url, params=None, headers=None, timeout=None):
            captured.update(params or {})
            return _replies_response([{"user": "U9", "ts": "5.0", "text": "elsewhere"}])

        with patch.object(slack_tools.requests, "get", side_effect=_get), \
             patch.object(slack_tools, "_resolve_slack_names", return_value={}):
            out = slack_tools.read_slack_thread_impl(
                {"channel": "C2", "thread_ts": "5.0"},
                {"conversation": {"channel_type": "slack", "channel_id": "C1", "thread_ref": "100.0"}},
            )

        assert captured["channel"] == "C2"
        assert captured["ts"] == "5.0"
        assert "elsewhere" in out

    def test_no_conversation_context_is_a_clear_error(self):
        """Claws, CLI runs and scripts have no conversation. Must not crash."""
        out = slack_tools.read_slack_thread_impl({}, {})
        assert out.startswith("Error:")
        assert "no Slack thread in context" in out

    def test_non_slack_channel_says_so(self):
        out = slack_tools.read_slack_thread_impl(
            {}, {"conversation": {"channel_type": "email", "thread_ref": "msg-id"}},
        )
        assert out.startswith("Error:")
        assert "not on Slack" in out

    def test_missing_scope_explains_the_fix(self):
        class _R:
            status_code = 200
            text = "err"

            def json(self_):
                return {"ok": False, "error": "missing_scope", "needed": "channels:history"}

        with patch.object(slack_tools.requests, "get", return_value=_R()):
            out = slack_tools.read_slack_thread_impl(
                {}, {"conversation": {"channel_type": "slack", "channel_id": "C1", "thread_ref": "1.0"}},
            )

        assert "channels:history" in out

    def test_limit_is_clamped(self):
        captured = {}

        def _get(url, params=None, headers=None, timeout=None):
            captured.update(params or {})
            return _replies_response([{"user": "U1", "ts": "1.0", "text": "x"}])

        with patch.object(slack_tools.requests, "get", side_effect=_get), \
             patch.object(slack_tools, "_resolve_slack_names", return_value={}):
            slack_tools.read_slack_thread_impl(
                {"limit": 5000},
                {"conversation": {"channel_type": "slack", "channel_id": "C1", "thread_ref": "1.0"}},
            )

        assert captured["limit"] == slack_tools.MAX_THREAD_MESSAGES
