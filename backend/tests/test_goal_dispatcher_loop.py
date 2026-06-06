"""
Tests for the GoalDispatcher tool-use loop and guardrail interaction.

Pattern: script Claude's responses by side_effect-ing
`client.messages.create`. Each "turn" returns either tool_use blocks
that the loop must execute, or a final text block that terminates it.

The actual tools are mocked via monkeypatching the registry's
`get_tool` and `get_all_tools` so we don't run real file I/O or Slack.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.db.connection import DatabaseConnection
from src.db.repositories.goal_repo import GoalRepo
from src.services.goal_dispatcher import GoalDispatcher
from src.services.goal_engine import GoalEngine
from src.tools.registry import Tool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_org_id():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES ('Loop Test', 'loop-test-' || md5(random()::text)) "
                "RETURNING org_id"
            )
            org_id = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)

    yield org_id

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM goals WHERE org_id = %s", (org_id,))
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


@pytest.fixture
def engine():
    return GoalEngine(GoalRepo())


def _usage(in_t=10, out_t=10):
    return SimpleNamespace(
        input_tokens=in_t,
        output_tokens=out_t,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


def _tool_use_resp(tool_uses, stop_reason="tool_use"):
    return SimpleNamespace(
        content=tool_uses,
        stop_reason=stop_reason,
        usage=_usage(),
    )


def _end_resp(text):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=_usage(),
    )


def _tu(name, input_, id_):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id_)


@pytest.fixture
def fake_tools():
    """Replace the registry with deterministic stub tools for the test."""
    calls = []

    def make_tool(name, is_read_only, fn):
        def execute(tool_input, context):
            calls.append((name, tool_input))
            return fn(tool_input, context)
        return Tool(
            name=name,
            description=f"fake {name}",
            input_schema={"type": "object", "properties": {}, "required": []},
            execute=execute,
            is_read_only=is_read_only,
        )

    tools_by_name = {
        "list_projects": make_tool(
            "list_projects", True,
            lambda i, c: "Active projects:\n  - alpha\n  - beta",
        ),
        "read_main_md": make_tool(
            "read_main_md", True,
            lambda i, c: f"# {i.get('project_slug')}\n\nold content",
        ),
        "edit_main_md": make_tool(
            "edit_main_md", False,
            lambda i, c: f"Edited /opt/shared/projects/Active/{i['project_slug']}/MAIN.md",
        ),
        "slack_post": make_tool(
            "slack_post", False,
            lambda i, c: "Posted to #standup (ts=1.2). Mentioned <@U1>.",
        ),
    }

    with patch("src.tools.registry._TOOLS", tools_by_name):
        yield {"calls": calls, "tools": tools_by_name}


# ---------------------------------------------------------------------------
# Happy path: one read, one edit, one ping, end
# ---------------------------------------------------------------------------


class TestLoopHappyPath:
    def test_read_edit_post_then_end(self, engine, test_org_id, fake_tools):
        g = engine.create_goal(
            test_org_id, "Update one MAIN.md",
            config={
                "allowed_tools": ["list_projects", "read_main_md", "edit_main_md", "slack_post"],
                "max_tool_rounds": 6,
                "max_cost_usd": 1.0,
                "allow_multiple_writes": True,  # one edit AND one slack_post
            },
        )

        client = MagicMock()
        client.messages.create.side_effect = [
            _tool_use_resp([_tu("list_projects", {}, "u1")]),
            _tool_use_resp([_tu("read_main_md", {"project_slug": "alpha"}, "u2")]),
            _tool_use_resp([_tu("edit_main_md", {
                "project_slug": "alpha",
                "old_string": "old content",
                "new_string": "new content",
            }, "u3")]),
            _tool_use_resp([_tu("slack_post", {
                "channel": "#standup",
                "text": "edited alpha",
                "mention_user_id": "U1",
            }, "u4")]),
            _end_resp("Updated alpha and pinged Golda."),
        ]

        dispatcher = GoalDispatcher(anthropic_client=client)
        result = dispatcher.dispatch(g["id"])

        assert result.status == "completed", result.error
        assert "Updated alpha" in result.summary
        assert "[loop stats:" in result.summary

        # slack_post is GATED by the draft-approval gate (outbound action): it is
        # held for approval and does NOT execute, so it is absent from the
        # executed-tool calls. The free read/edit tools run normally.
        call_names = [c[0] for c in fake_tools["calls"]]
        assert call_names == ["list_projects", "read_main_md", "edit_main_md"]

        # Each tool call is still recorded as a goal_event (event recording runs
        # whether the action executed or was held), including the held slack_post.
        events = engine.events(g["id"])
        actions = [e["action"] for e in events]
        assert "tool_call:list_projects" in actions
        assert "tool_call:read_main_md" in actions
        assert "tool_call:edit_main_md" in actions
        assert "tool_call:slack_post" in actions


# ---------------------------------------------------------------------------
# Guardrail: tool not in allowed_tools
# ---------------------------------------------------------------------------


class TestNotAllowed:
    def test_tool_outside_allowed_trips(self, engine, test_org_id, fake_tools):
        g = engine.create_goal(
            test_org_id, "Read only",
            config={
                "allowed_tools": ["list_projects", "read_main_md"],
                "max_tool_rounds": 5,
            },
        )

        client = MagicMock()
        client.messages.create.side_effect = [
            _tool_use_resp([_tu("edit_main_md", {
                "project_slug": "alpha",
                "old_string": "x", "new_string": "y",
            }, "u1")]),
        ]
        dispatcher = GoalDispatcher(anthropic_client=client)
        result = dispatcher.dispatch(g["id"])

        assert result.status == "failed"
        assert "guardrail:not_allowed" in (result.error or "")

        # The edit tool MUST NOT have actually been called.
        call_names = [c[0] for c in fake_tools["calls"]]
        assert "edit_main_md" not in call_names

        events = engine.events(g["id"])
        actions = [e["action"] for e in events]
        assert any(a.startswith("guardrail_trip:not_allowed") for a in actions)


# ---------------------------------------------------------------------------
# Guardrail: write-once (the explicit "stop after first edit" rule)
# ---------------------------------------------------------------------------


class TestWriteOnce:
    def test_second_write_in_same_dispatch_trips(
        self, engine, test_org_id, fake_tools,
    ):
        g = engine.create_goal(
            test_org_id, "Update one and stop",
            config={
                "allowed_tools": ["read_main_md", "edit_main_md", "slack_post"],
                "max_tool_rounds": 5,
                "allow_multiple_writes": False,  # the goal says STOP after one
            },
        )

        client = MagicMock()
        client.messages.create.side_effect = [
            _tool_use_resp([_tu("edit_main_md", {
                "project_slug": "alpha",
                "old_string": "x", "new_string": "y",
            }, "u1")]),
            _tool_use_resp([_tu("slack_post", {
                "channel": "#standup", "text": "done",
                "mention_user_id": "U1",
            }, "u2")]),
        ]
        dispatcher = GoalDispatcher(anthropic_client=client)
        result = dispatcher.dispatch(g["id"])

        assert result.status == "failed"
        assert "write_once" in (result.error or "")

        # The first write should have succeeded; the second was blocked.
        call_names = [c[0] for c in fake_tools["calls"]]
        assert call_names == ["edit_main_md"]


# ---------------------------------------------------------------------------
# Guardrail: round cap
# ---------------------------------------------------------------------------


class TestRoundCap:
    def test_loop_stops_at_cap(self, engine, test_org_id, fake_tools):
        g = engine.create_goal(
            test_org_id, "Infinite loop",
            config={
                "allowed_tools": ["list_projects"],
                "max_tool_rounds": 2,
            },
        )

        client = MagicMock()
        # Always return tool_use; never end. Loop should fail after 2 rounds.
        client.messages.create.side_effect = [
            _tool_use_resp([_tu("list_projects", {}, f"u{i}")])
            for i in range(20)
        ]
        dispatcher = GoalDispatcher(anthropic_client=client)
        result = dispatcher.dispatch(g["id"])

        assert result.status == "failed"
        assert "max_tool_rounds" in (result.error or "")
