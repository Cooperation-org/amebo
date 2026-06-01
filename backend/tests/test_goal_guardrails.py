"""
Tests for GuardrailContext. No DB, no network, fully unit-level.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.services.goal_guardrails import GuardrailContext, GuardrailTripped


def _make(**overrides):
    base = dict(
        max_tool_rounds=3,
        max_cost_usd=0.10,
        wall_clock_seconds=60,
        allowed_tools={"read_main_md", "edit_main_md", "slack_post", "search_slack_history"},
        write_tools={"edit_main_md", "slack_post"},
        allow_multiple_writes=False,
    )
    base.update(overrides)
    return GuardrailContext(**base)


class TestRounds:
    def test_increments_per_round(self):
        g = _make()
        g.begin_round(); g.begin_round(); g.begin_round()
        assert g.rounds_used == 3

    def test_round_cap_trips(self):
        g = _make(max_tool_rounds=2)
        g.begin_round(); g.begin_round()
        with pytest.raises(GuardrailTripped) as exc:
            g.begin_round()
        assert exc.value.which == "max_tool_rounds"


class TestCost:
    def test_input_output_tokens_sum(self):
        g = _make(max_cost_usd=10.0)
        usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=0,
                                cache_creation_input_tokens=0, cache_read_input_tokens=0)
        spent = g.record_usage(usage, "claude-sonnet-4-20250514")
        # 1M input tokens at $3/Mtok = $3.00
        assert pytest.approx(spent, abs=1e-6) == 3.0

    def test_output_more_expensive(self):
        g = _make(max_cost_usd=100.0)
        usage = SimpleNamespace(input_tokens=0, output_tokens=1_000_000,
                                cache_creation_input_tokens=0, cache_read_input_tokens=0)
        spent = g.record_usage(usage, "claude-sonnet-4-20250514")
        # 1M output tokens at $15/Mtok = $15.00
        assert pytest.approx(spent, abs=1e-6) == 15.0

    def test_cost_cap_trips(self):
        g = _make(max_cost_usd=0.001)
        usage = SimpleNamespace(input_tokens=10000, output_tokens=10000,
                                cache_creation_input_tokens=0, cache_read_input_tokens=0)
        with pytest.raises(GuardrailTripped) as exc:
            g.record_usage(usage, "claude-sonnet-4-20250514")
        assert exc.value.which == "max_cost_usd"

    def test_unknown_model_uses_default(self):
        g = _make(max_cost_usd=10.0)
        usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=0,
                                cache_creation_input_tokens=0, cache_read_input_tokens=0)
        # Should still record without raising
        assert g.record_usage(usage, "minimax-m2.7") > 0


class TestToolAuthorization:
    def test_read_tool_allowed(self):
        g = _make()
        g.permit_tool("read_main_md", is_read_only=True)
        assert g.write_tools_used == 0

    def test_not_in_allowed_set(self):
        g = _make(allowed_tools={"read_main_md"})
        with pytest.raises(GuardrailTripped) as exc:
            g.permit_tool("edit_main_md", is_read_only=False)
        assert exc.value.which == "not_allowed"

    def test_write_once_then_blocked(self):
        g = _make()
        g.permit_tool("edit_main_md", is_read_only=False)
        # A second write attempt — even of a DIFFERENT write tool — trips
        with pytest.raises(GuardrailTripped) as exc:
            g.permit_tool("slack_post", is_read_only=False)
        assert exc.value.which == "write_once"

    def test_multiple_writes_when_explicitly_enabled(self):
        g = _make(allow_multiple_writes=True)
        g.permit_tool("edit_main_md", is_read_only=False)
        g.permit_tool("slack_post", is_read_only=False)
        assert g.write_tools_used == 2

    def test_read_tools_do_not_count_toward_write_budget(self):
        g = _make()
        for _ in range(5):
            g.permit_tool("read_main_md", is_read_only=True)
        assert g.write_tools_used == 0


class TestWallClock:
    def test_already_past_deadline_on_begin_round(self):
        g = _make(wall_clock_seconds=1)
        g.started_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        with pytest.raises(GuardrailTripped) as exc:
            g.begin_round()
        assert exc.value.which == "wall_clock"

    def test_already_past_deadline_on_permit_tool(self):
        g = _make(wall_clock_seconds=1)
        g.started_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        with pytest.raises(GuardrailTripped) as exc:
            g.permit_tool("read_main_md", is_read_only=True)
        assert exc.value.which == "wall_clock"


class TestFromGoalConfig:
    def test_default_when_empty(self):
        g = GuardrailContext.from_goal_config(None)
        assert g.max_tool_rounds == 5
        assert g.max_cost_usd == 0.50

    def test_reads_config(self):
        g = GuardrailContext.from_goal_config({
            "max_tool_rounds": 7,
            "max_cost_usd": 1.25,
            "wall_clock_seconds": 120,
            "allowed_tools": ["read_main_md", "edit_main_md"],
            "allow_multiple_writes": True,
            "slack_require_mention": False,
        })
        assert g.max_tool_rounds == 7
        assert g.max_cost_usd == 1.25
        assert g.wall_clock_seconds == 120
        assert g.allowed_tools == {"read_main_md", "edit_main_md"}
        # write_tools is intersected with allowed_tools
        assert g.write_tools == {"edit_main_md"}
        assert g.allow_multiple_writes is True
        assert g.slack_require_mention is False
