"""
Tests for the gated-action registry — pure classification, no DB.

Covers the strategic rule: outbound/destructive actions are gated, read-only
and internal/reversible actions are free, and the default is to gate anything
unclassified (default-deny).
"""

from __future__ import annotations

import pytest

from src.services import gated_actions


class TestFreeActions:
    @pytest.mark.parametrize("action", [
        "search_knowledge_base",
        "search_slack_history",
        "lookup_contact",
        "abra",
        "http_fetch",
        "list_goals",
        "get_goal_events",
        "list_hot_tags",
        "list_projects",
        "read_main_md",
        "edit_main_md",   # internal: lands uncommitted, human reviews git diff
    ])
    def test_free_actions_do_not_require_approval(self, action):
        assert gated_actions.is_free(action) is True
        assert gated_actions.is_gated(action) is False
        assert gated_actions.requires_approval(action) is False


class TestGatedActions:
    @pytest.mark.parametrize("action", [
        "slack_post",
        "send_email",
        "odoo_cli",
        "mcp_taiga",
        "open_pr",
        "merge_pr",
    ])
    def test_outbound_destructive_actions_require_approval(self, action):
        assert gated_actions.is_gated(action) is True
        assert gated_actions.requires_approval(action) is True
        assert gated_actions.is_free(action) is False


class TestDefaultDeny:
    def test_unknown_action_is_gated(self):
        # An action type nobody has classified must be gated, not free.
        assert gated_actions.requires_approval("some_brand_new_outbound_thing") is True
        assert gated_actions.is_gated("") is True

    def test_free_and_gated_are_complementary(self):
        # Sanity: nothing is both free and gated.
        for action in gated_actions.FREE_ACTIONS:
            assert not gated_actions.is_gated(action)
        for action in gated_actions.GATED_ACTIONS:
            assert gated_actions.is_gated(action)
            assert action not in gated_actions.FREE_ACTIONS
