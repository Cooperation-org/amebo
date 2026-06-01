"""
Tests for the thread-reply path: amebo treats a reply in a thread it
started as an implicit message to itself.

We unit-test the parent-detection helper and the handle_thread_reply
function — both async. No HTTP transport involved.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _slack_tokens(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")


# ---------------------------------------------------------------------------
# is_thread_parent_our_bot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parent_is_our_bot_returns_true():
    from src.services import slack_commands

    fake_web = AsyncMock()
    fake_web.conversations_history.return_value = {
        "messages": [{"user": "U_BOT", "ts": "1.0", "text": "hi"}],
    }
    with patch.object(slack_commands, "AsyncWebClient", return_value=fake_web):
        ok = await slack_commands.is_thread_parent_our_bot(
            "C1", "1.0", bot_user_id="U_BOT",
        )
    assert ok is True


@pytest.mark.asyncio
async def test_parent_is_other_user_returns_false():
    from src.services import slack_commands

    fake_web = AsyncMock()
    fake_web.conversations_history.return_value = {
        "messages": [{"user": "U_HUMAN", "ts": "1.0", "text": "hi"}],
    }
    with patch.object(slack_commands, "AsyncWebClient", return_value=fake_web):
        ok = await slack_commands.is_thread_parent_our_bot(
            "C1", "1.0", bot_user_id="U_BOT",
        )
    assert ok is False


@pytest.mark.asyncio
async def test_no_messages_returns_false():
    from src.services import slack_commands

    fake_web = AsyncMock()
    fake_web.conversations_history.return_value = {"messages": []}
    with patch.object(slack_commands, "AsyncWebClient", return_value=fake_web):
        ok = await slack_commands.is_thread_parent_our_bot(
            "C1", "1.0", bot_user_id="U_BOT",
        )
    assert ok is False


@pytest.mark.asyncio
async def test_api_error_returns_false():
    from src.services import slack_commands
    from slack_sdk.errors import SlackApiError

    fake_web = AsyncMock()
    fake_web.conversations_history.side_effect = SlackApiError(
        message="err", response=MagicMock(),
    )
    with patch.object(slack_commands, "AsyncWebClient", return_value=fake_web):
        ok = await slack_commands.is_thread_parent_our_bot(
            "C1", "1.0", bot_user_id="U_BOT",
        )
    assert ok is False


@pytest.mark.asyncio
async def test_empty_args_short_circuit():
    from src.services import slack_commands
    assert await slack_commands.is_thread_parent_our_bot("", "x", "U") is False
    assert await slack_commands.is_thread_parent_our_bot("C1", "", "U") is False


# ---------------------------------------------------------------------------
# handle_thread_reply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_thread_reply_routes_through_qa_service():
    from src.services import slack_commands

    fake_web = AsyncMock()
    fake_web.chat_postMessage.return_value = {"ok": True}

    fake_qa = MagicMock()
    fake_qa.return_value.answer_question.return_value = {
        "answer": "yep, I see your reply",
        "sources": [{"channel": "standup"}],
        "confidence": 75,
    }

    with patch.object(slack_commands, "AsyncWebClient", return_value=fake_web), \
         patch.object(slack_commands, "QAService", fake_qa), \
         patch.object(slack_commands, "_log_slack_query_usage"):
        await slack_commands.handle_thread_reply(
            team_id="TJ5RZJT52",
            channel="C1",
            text="anything new?",
            user="UHUUD9ERZ",
            ts="2.0",
            thread_ts="1.0",
        )

    # QA service called with thread_ts as thread_ref and source_type=slack
    qa_call_kwargs = fake_qa.return_value.answer_question.call_args.kwargs
    assert qa_call_kwargs["thread_ref"] == "1.0"
    assert qa_call_kwargs["source_type"] == "slack"
    assert qa_call_kwargs["question"] == "anything new?"
    assert "UHUUD9ERZ" in qa_call_kwargs["author_info"]

    # Reply posted in the same thread
    post_kwargs = fake_web.chat_postMessage.call_args.kwargs
    assert post_kwargs["channel"] == "C1"
    assert post_kwargs["thread_ts"] == "1.0"
    assert "yep, I see your reply" in post_kwargs["text"]


@pytest.mark.asyncio
async def test_handle_thread_reply_skips_empty_text():
    from src.services import slack_commands

    fake_web = AsyncMock()
    with patch.object(slack_commands, "AsyncWebClient", return_value=fake_web), \
         patch.object(slack_commands, "QAService") as qa:
        await slack_commands.handle_thread_reply(
            team_id="T", channel="C", text="   ", user="U", ts="2", thread_ts="1",
        )
    qa.assert_not_called()
    fake_web.chat_postMessage.assert_not_called()
