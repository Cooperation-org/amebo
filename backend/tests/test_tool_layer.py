"""
Tests for the Amebo tool layer (eyes + hands).

Everything external is mocked: no real CLI subprocess runs, no real Slack /
Taiga calls, no DB. We assert:

  * read tools shell out to the right CLI with the right argv (list args);
  * gated actuators route through the draft-approval gate, creating a
    pending_action and NOT performing the side effect;
  * a tool not in allowed_tools is never exposed by get_tools_for_instance
    and never executed.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from src.tools import cli_read_tools, gated_actuators
from src.tools.registry import get_tools_for_instance, _TOOLS
from src.services import gated_actions
from src.services.draft_approval_service import DraftApprovalService, GateResult


# ---------------------------------------------------------------------------
# Subprocess capture helper for read tools
# ---------------------------------------------------------------------------


class _CompletedProc:
    def __init__(self, stdout="ok", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _capture_run():
    """Patch subprocess.run inside cli_read_tools and capture argv."""
    calls: List[List[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        # Assert subprocess discipline at the boundary.
        assert isinstance(argv, list), "argv must be a list (no shell word-split)"
        assert kwargs.get("shell") is False, "must never use shell=True"
        assert "timeout" in kwargs, "every CLI call must have a timeout"
        return _CompletedProc(stdout="result-text")

    return calls, fake_run


# ---------------------------------------------------------------------------
# Read tools — right CLI, right argv
# ---------------------------------------------------------------------------


class TestReadTools:
    def test_odoo_search_contacts(self):
        calls, fake = _capture_run()
        with patch.object(cli_read_tools.subprocess, "run", side_effect=fake):
            out = cli_read_tools.odoo_search_impl({"query": "Mozilla"}, {"org_id": 1})
        assert calls == [["odoo-cli", "search", "contacts", "Mozilla"]]
        assert "result-text" in out

    def test_odoo_search_leads_model(self):
        calls, fake = _capture_run()
        with patch.object(cli_read_tools.subprocess, "run", side_effect=fake):
            cli_read_tools.odoo_search_impl({"query": "grant", "model": "leads"}, {})
        assert calls == [["odoo-cli", "search", "leads", "grant"]]

    def test_odoo_search_rejects_bad_model(self):
        out = cli_read_tools.odoo_search_impl({"query": "x", "model": "evil"}, {})
        assert "model must be" in out

    def test_odoo_search_requires_query(self):
        out = cli_read_tools.odoo_search_impl({}, {})
        assert "query is required" in out

    def test_crm_read_latest_email(self):
        calls, fake = _capture_run()
        with patch.object(cli_read_tools.subprocess, "run", side_effect=fake):
            cli_read_tools.crm_read_latest_email_impl(
                {"sender": "jane@example.org"}, {}
            )
        assert calls == [["odoo-cli", "show", "contact", "jane@example.org"]]

    def test_crm_read_latest_email_requires_sender(self):
        out = cli_read_tools.crm_read_latest_email_impl({}, {})
        assert "sender is required" in out

    def test_abra_search_default_mode(self):
        calls, fake = _capture_run()
        with patch.object(cli_read_tools.subprocess, "run", side_effect=fake):
            cli_read_tools.abra_search_impl({"query": "claim lexicon"}, {})
        assert calls == [["abra", "search", "claim lexicon"]]

    def test_abra_search_about_mode(self):
        calls, fake = _capture_run()
        with patch.object(cli_read_tools.subprocess, "run", side_effect=fake):
            cli_read_tools.abra_search_impl(
                {"query": "Sarah Chen", "mode": "about"}, {}
            )
        assert calls == [["abra", "about", "Sarah Chen"]]

    def test_abra_search_rejects_bad_mode(self):
        out = cli_read_tools.abra_search_impl({"query": "x", "mode": "delete"}, {})
        assert "mode must be" in out

    def test_taiga_list_no_project(self):
        calls, fake = _capture_run()
        with patch.object(cli_read_tools.subprocess, "run", side_effect=fake):
            cli_read_tools.taiga_list_impl({}, {})
        assert calls == [["mcp-taiga", "list"]]

    def test_taiga_list_with_project(self):
        calls, fake = _capture_run()
        with patch.object(cli_read_tools.subprocess, "run", side_effect=fake):
            cli_read_tools.taiga_list_impl({"project": "lexistats"}, {})
        assert calls == [["mcp-taiga", "list", "lexistats"]]

    def test_run_cli_missing_executable(self):
        with patch.object(
            cli_read_tools.subprocess, "run", side_effect=FileNotFoundError()
        ):
            out = cli_read_tools.run_cli(["nope-cli", "x"])
        assert "not found in PATH" in out

    def test_run_cli_timeout(self):
        import subprocess as sp

        with patch.object(
            cli_read_tools.subprocess,
            "run",
            side_effect=sp.TimeoutExpired(cmd="abra", timeout=10),
        ):
            out = cli_read_tools.run_cli(["abra", "search", "x"])
        assert "timed out" in out

    def test_read_tools_classified_free(self):
        for name in ("odoo_search", "crm_read_latest_email", "abra_search", "taiga_list"):
            assert gated_actions.is_free(name), f"{name} should be FREE"
            assert not gated_actions.requires_approval(name)


# ---------------------------------------------------------------------------
# Gated actuators — route through the gate, no side effect
# ---------------------------------------------------------------------------


class _FakeRepo:
    """Stand-in PendingActionRepo: records create() calls in memory."""

    def __init__(self):
        self.created: List[Dict[str, Any]] = []

    def create(self, **kwargs):
        row = dict(kwargs)
        row["id"] = "pa-%d" % (len(self.created) + 1)
        row["status"] = "pending"
        self.created.append(row)
        return row


class _FakeGoalRepo:
    def append_event(self, **kwargs):  # never called when goal_id is None
        raise AssertionError("append_event should not run without a goal_id")


def _gate_with_fake_repo():
    repo = _FakeRepo()
    svc = DraftApprovalService(repo=repo, goal_repo=_FakeGoalRepo())
    return repo, svc


class TestGatedActuators:
    def test_actuator_action_types_are_gated(self):
        assert gated_actions.requires_approval("taiga_create_task")
        assert gated_actions.requires_approval("slack_post")

    def test_taiga_create_task_routes_through_gate_no_side_effect(self):
        repo, gate = _gate_with_fake_repo()

        # If the real CLI ever ran, this would explode the test.
        with patch.object(
            gated_actuators, "run_cli",
            side_effect=AssertionError("side effect must NOT run for a gated action"),
        ):
            out = gated_actuators.taiga_create_task_impl(
                {"subject": "Ship tool layer", "project": "amebo"},
                {"org_id": 7, "draft_gate": gate},
            )

        assert "[held for approval]" in out
        assert "pa-1" in out
        assert len(repo.created) == 1
        rec = repo.created[0]
        assert rec["org_id"] == 7
        assert rec["action_type"] == "taiga_create_task"
        assert rec["payload"]["subject"] == "Ship tool layer"
        assert rec["acting_identity"] == "amebo:7"

    def test_slack_post_gated_routes_through_gate_no_side_effect(self):
        repo, gate = _gate_with_fake_repo()

        # The real Slack post would import slack_tools; assert it's never called.
        with patch("src.tools.slack_tools.slack_post_impl",
                   side_effect=AssertionError("Slack post must NOT run for a gated action")):
            out = gated_actuators.slack_post_impl(
                {"channel": "#general", "text": "status update",
                 "mention_user_id": "U123"},
                {"org_id": 3, "draft_gate": gate},
            )

        assert "[held for approval]" in out
        assert len(repo.created) == 1
        rec = repo.created[0]
        assert rec["action_type"] == "slack_post"
        assert rec["target"] == "#general"
        assert rec["payload"]["mention_user_id"] == "U123"

    def test_actuator_requires_org_context(self):
        _, gate = _gate_with_fake_repo()
        out = gated_actuators.taiga_create_task_impl(
            {"subject": "x"}, {"draft_gate": gate}
        )
        assert "no org context" in out

    def test_actuator_delegated_identity_stamp(self):
        repo, gate = _gate_with_fake_repo()
        gated_actuators.taiga_create_task_impl(
            {"subject": "x"},
            {"org_id": 9, "principal": "golda", "draft_gate": gate},
        )
        assert repo.created[0]["acting_identity"] == "urn:amebo:user:golda"

    def test_taiga_create_requires_subject(self):
        out = gated_actuators.taiga_create_task_impl({}, {"org_id": 1})
        assert "subject is required" in out

    def test_slack_post_requires_channel_and_text(self):
        assert "channel is required" in gated_actuators.slack_post_impl(
            {"text": "hi"}, {"org_id": 1}
        )
        assert "text is required" in gated_actuators.slack_post_impl(
            {"channel": "#x"}, {"org_id": 1}
        )

    def test_gate_creates_pending_for_unclassified_action(self):
        """Default-deny: an unlisted action type is still gated (the executor
        is never run)."""
        repo, gate = _gate_with_fake_repo()
        ran = {"called": False}

        def executor(_a):
            ran["called"] = True
            return "did it"

        result: GateResult = gate.gate_or_execute(
            org_id=1,
            action_type="some_brand_new_outbound_thing",
            acting_identity="amebo:1",
            executor=executor,
        )
        assert result.gated is True
        assert result.executed is False
        assert ran["called"] is False
        assert len(repo.created) == 1


# ---------------------------------------------------------------------------
# allowed_tools — exposure + execution gating
# ---------------------------------------------------------------------------


class TestAllowedTools:
    def test_registered(self):
        for name in (
            "odoo_search", "crm_read_latest_email", "abra_search", "taiga_list",
            "taiga_create_task", "slack_post_gated",
        ):
            assert name in _TOOLS, f"{name} not registered"

    def test_tool_not_in_allowed_tools_is_not_exposed(self):
        instance = {"config": {"allowed_tools": ["odoo_search", "abra_search"]}}
        exposed = {t["name"] for t in get_tools_for_instance(instance)}
        assert "odoo_search" in exposed
        assert "abra_search" in exposed
        # Outbound actuators were NOT allowed → never offered to the model.
        assert "slack_post_gated" not in exposed
        assert "taiga_create_task" not in exposed

    def test_allowed_actuator_is_exposed(self):
        instance = {"config": {"allowed_tools": ["taiga_create_task"]}}
        exposed = {t["name"] for t in get_tools_for_instance(instance)}
        assert "taiga_create_task" in exposed

    def test_config_as_json_string(self):
        instance = {"config": '{"allowed_tools": ["taiga_list"]}'}
        exposed = {t["name"] for t in get_tools_for_instance(instance)}
        assert "taiga_list" in exposed
        assert "slack_post_gated" not in exposed
