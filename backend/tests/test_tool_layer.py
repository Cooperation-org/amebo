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
        # Confirmed against the live CLI: read verb is `contact-search <query>`.
        calls, fake = _capture_run()
        with patch.object(cli_read_tools.subprocess, "run", side_effect=fake):
            out = cli_read_tools.odoo_search_impl({"query": "Mozilla"}, {"org_id": 1})
        assert calls == [["odoo-cli", "contact-search", "Mozilla"]]
        assert "result-text" in out

    def test_odoo_search_ignores_unknown_keys(self):
        # No model param any more (CLI has no leads search); extra keys ignored.
        calls, fake = _capture_run()
        with patch.object(cli_read_tools.subprocess, "run", side_effect=fake):
            cli_read_tools.odoo_search_impl({"query": "grant", "model": "leads"}, {})
        assert calls == [["odoo-cli", "contact-search", "grant"]]

    def test_odoo_search_requires_query(self):
        out = cli_read_tools.odoo_search_impl({}, {})
        assert "query is required" in out

    def test_crm_read_latest_email(self):
        # Confirmed against the live CLI: read verb is `comms <name>`.
        calls, fake = _capture_run()
        with patch.object(cli_read_tools.subprocess, "run", side_effect=fake):
            cli_read_tools.crm_read_latest_email_impl(
                {"sender": "jane@example.org"}, {}
            )
        assert calls == [["odoo-cli", "comms", "jane@example.org"]]

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

    def test_taiga_list_requires_project(self):
        # Confirmed against the live CLI: `mcp-taiga list PROJECT` needs a
        # required positional project; refuse (no subprocess) when absent.
        calls, fake = _capture_run()
        with patch.object(cli_read_tools.subprocess, "run", side_effect=fake):
            out = cli_read_tools.taiga_list_impl({}, {})
        assert calls == []
        assert "project is required" in out

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
                {"subject": "Ship tool layer", "project": "amebo",
                 "due_date": "2099-01-15"},
                {"org_id": 7, "draft_gate": gate},
            )

        assert "[held for approval]" in out
        assert "pa-1" in out
        assert len(repo.created) == 1
        rec = repo.created[0]
        assert rec["org_id"] == 7
        assert rec["action_type"] == "taiga_create_task"
        assert rec["payload"]["subject"] == "Ship tool layer"
        assert rec["payload"]["due_date"] == "2099-01-15"
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
            {"subject": "x", "project": "amebo", "due_date": "2099-01-15"},
            {"draft_gate": gate},
        )
        assert "no org context" in out

    def test_actuator_delegated_identity_stamp(self):
        repo, gate = _gate_with_fake_repo()
        gated_actuators.taiga_create_task_impl(
            {"subject": "x", "project": "amebo", "due_date": "2099-01-15"},
            {"org_id": 9, "principal": "golda", "draft_gate": gate},
        )
        assert repo.created[0]["acting_identity"] == "urn:amebo:user:golda"

    def test_taiga_create_requires_due_date(self):
        # Deadlines are required on every task.
        _, gate = _gate_with_fake_repo()
        out = gated_actuators.taiga_create_task_impl(
            {"subject": "x", "project": "amebo"},
            {"org_id": 1, "draft_gate": gate},
        )
        assert "due_date is required" in out

    def test_taiga_create_rejects_bad_due_date(self):
        _, gate = _gate_with_fake_repo()
        out = gated_actuators.taiga_create_task_impl(
            {"subject": "x", "project": "amebo", "due_date": "June 20"},
            {"org_id": 1, "draft_gate": gate},
        )
        assert "not a valid date" in out

    def test_taiga_create_payload_carries_assignee_and_cash(self):
        repo, gate = _gate_with_fake_repo()
        gated_actuators.taiga_create_task_impl(
            {"subject": "x", "project": "amebo", "due_date": "2099-01-15",
             "assignee": "golda", "cash": 50},
            {"org_id": 1, "draft_gate": gate},
        )
        payload = repo.created[0]["payload"]
        assert payload["assignee"] == "golda"
        assert payload["cash"] == 50

    def test_execute_taiga_create_builds_argv(self):
        # The post-approval executor builds the right mcp-taiga argv from payload.
        captured = {}

        def fake_run_cli(argv):
            captured["argv"] = argv
            return "Created #5: Ship X"

        with patch.object(gated_actuators, "run_cli", side_effect=fake_run_cli):
            gated_actuators.execute_taiga_create({"payload": {
                "project": "amebo", "subject": "Ship X", "description": "ctx",
                "due_date": "2099-01-15", "assignee": "golda", "cash": 50,
            }})
        assert captured["argv"] == [
            "mcp-taiga", "create", "amebo", "Ship X",
            "--description", "ctx", "--due", "2099-01-15",
            "--assign", "golda", "--cash", "50",
        ]

    def test_execute_taiga_create_raises_on_failure(self):
        # A failed CLI (run_cli returns an error string, never raises) must
        # surface as an exception so the action is marked failed, not executed.
        import pytest
        with patch.object(gated_actuators, "run_cli",
                          return_value="Error: command not found: mcp-taiga"):
            with pytest.raises(RuntimeError, match="taiga_create_task failed"):
                gated_actuators.execute_taiga_create({"payload": {
                    "project": "amebo", "subject": "x", "due_date": "2099-01-15",
                }})

    def test_taiga_create_executor_is_registered(self):
        from src.services.action_executors import get_executor
        assert get_executor("taiga_create_task") is gated_actuators.execute_taiga_create

    def test_slack_post_executor_is_registered(self):
        from src.services.action_executors import get_executor
        assert get_executor("slack_post") is gated_actuators.execute_slack_post

    def test_execute_slack_post_raises_on_error(self):
        import pytest
        with patch("src.tools.slack_tools.slack_post_impl",
                   return_value="Error: Slack API returned HTTP 500"):
            with pytest.raises(RuntimeError, match="slack_post failed"):
                gated_actuators.execute_slack_post(
                    {"payload": {"channel": "#x", "text": "hi"}}
                )

    def test_execute_slack_post_success(self):
        with patch("src.tools.slack_tools.slack_post_impl", return_value="Posted to #x"):
            out = gated_actuators.execute_slack_post(
                {"payload": {"channel": "#x", "text": "hi"}}
            )
        assert out == "Posted to #x"

    def test_taiga_create_requires_subject(self):
        out = gated_actuators.taiga_create_task_impl({}, {"org_id": 1})
        assert "subject is required" in out

    def test_taiga_create_requires_project(self):
        # Confirmed against the live CLI: `mcp-taiga create PROJECT SUBJECT`
        # requires a project; refuse to draft an unrunnable task.
        out = gated_actuators.taiga_create_task_impl(
            {"subject": "x"}, {"org_id": 1}
        )
        assert "project is required" in out

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


class TestTaigaWriteTools:
    """WP6: gated Taiga writes — update / comment / close. Each drafts through
    the gate (no side effect) and its executor builds the right argv + routes the
    org's Taiga env."""

    def test_all_three_are_gated(self):
        for a in ("taiga_update_task", "taiga_add_comment", "taiga_close_task"):
            assert gated_actions.requires_approval(a)

    def test_executors_registered(self):
        from src.services.action_executors import get_executor
        assert get_executor("taiga_update_task") is gated_actuators.execute_taiga_update
        assert get_executor("taiga_add_comment") is gated_actuators.execute_taiga_comment
        assert get_executor("taiga_close_task") is gated_actuators.execute_taiga_close

    # -- update --
    def test_update_routes_through_gate_no_side_effect(self):
        repo, gate = _gate_with_fake_repo()
        with patch.object(gated_actuators, "run_cli",
                          side_effect=AssertionError("no side effect for a gated action")):
            out = gated_actuators.taiga_update_task_impl(
                {"project": "amebo", "ref": 42, "status": "In progress"},
                {"org_id": 7, "draft_gate": gate})
        assert "[held for approval]" in out
        rec = repo.created[0]
        assert rec["action_type"] == "taiga_update_task"
        assert rec["payload"]["ref"] == 42
        assert rec["payload"]["org_id"] == 7
        assert rec["payload"]["status"] == "In progress"

    def test_update_requires_a_field(self):
        _, gate = _gate_with_fake_repo()
        out = gated_actuators.taiga_update_task_impl(
            {"project": "amebo", "ref": 42}, {"org_id": 1, "draft_gate": gate})
        assert "nothing to update" in out

    def test_execute_update_builds_argv_and_passes_org_env(self):
        seen = {}
        with patch.object(gated_actuators, "run_cli",
                          side_effect=lambda a, env=None: seen.update(argv=a, env=env) or "moved #42"), \
             patch.object(gated_actuators, "_taiga_env", return_value={"TAIGA_URL": "rtv"}):
            gated_actuators.execute_taiga_update({"payload": {
                "project": "amebo", "ref": 42, "status": "Done",
                "assignee": "golda", "due_date": "2026-07-01", "org_id": 7}})
        assert seen["argv"] == ["mcp-taiga", "update", "amebo", "42",
                                "--status", "Done", "--assign", "golda", "--due", "2026-07-01"]
        assert seen["env"] == {"TAIGA_URL": "rtv"}

    def test_execute_update_raises_on_failure(self):
        import pytest
        with patch.object(gated_actuators, "run_cli",
                          side_effect=lambda a, env=None: "Error: mcp-taiga exited 1: nope"), \
             patch.object(gated_actuators, "_taiga_env", return_value=None):
            with pytest.raises(RuntimeError, match="taiga_update_task failed"):
                gated_actuators.execute_taiga_update({"payload": {"project": "a", "ref": 1}})

    # -- comment --
    def test_comment_routes_through_gate(self):
        repo, gate = _gate_with_fake_repo()
        with patch.object(gated_actuators, "run_cli",
                          side_effect=AssertionError("no side effect")):
            out = gated_actuators.taiga_add_comment_impl(
                {"project": "amebo", "ref": 42, "text": "great work"},
                {"org_id": 3, "draft_gate": gate})
        assert "[held for approval]" in out
        assert repo.created[0]["payload"]["text"] == "great work"

    def test_execute_comment_builds_argv(self):
        seen = {}
        with patch.object(gated_actuators, "run_cli",
                          side_effect=lambda a, env=None: seen.update(argv=a) or "ok"), \
             patch.object(gated_actuators, "_taiga_env", return_value=None):
            gated_actuators.execute_taiga_comment({"payload": {
                "project": "amebo", "ref": 42, "text": "nice"}})
        assert seen["argv"] == ["mcp-taiga", "comment", "amebo", "42", "nice"]

    # -- close --
    def test_close_routes_through_gate(self):
        repo, gate = _gate_with_fake_repo()
        with patch.object(gated_actuators, "run_cli",
                          side_effect=AssertionError("no side effect")):
            out = gated_actuators.taiga_close_task_impl(
                {"project": "amebo", "ref": 42}, {"org_id": 3, "draft_gate": gate})
        assert "[held for approval]" in out
        assert repo.created[0]["action_type"] == "taiga_close_task"

    def test_execute_close_builds_move_argv(self):
        seen = {}
        with patch.object(gated_actuators, "run_cli",
                          side_effect=lambda a, env=None: seen.update(argv=a) or "moved"), \
             patch.object(gated_actuators, "_taiga_env", return_value=None):
            gated_actuators.execute_taiga_close({"payload": {
                "project": "amebo", "ref": 42, "status": "Done"}})
        assert seen["argv"] == ["mcp-taiga", "move", "amebo", "42", "Done"]

    def test_write_tools_require_org_context(self):
        _, gate = _gate_with_fake_repo()
        for impl, inp in (
            (gated_actuators.taiga_update_task_impl, {"project": "a", "ref": 1, "status": "x"}),
            (gated_actuators.taiga_add_comment_impl, {"project": "a", "ref": 1, "text": "x"}),
            (gated_actuators.taiga_close_task_impl, {"project": "a", "ref": 1}),
        ):
            out = impl(inp, {"draft_gate": gate})
            assert "no org context" in out


class TestCrmWriteTools:
    """WP15: gated CRM writes on the real odoo-cli verbs. Each drafts through
    the gate (no side effect); its executor builds the right argv + org env."""

    def test_all_gated(self):
        for a in ("crm_schedule", "crm_tag_contact", "crm_log_contacted"):
            assert gated_actions.requires_approval(a)

    def test_executors_registered(self):
        from src.services.action_executors import get_executor
        assert get_executor("crm_schedule") is gated_actuators.execute_crm_schedule
        assert get_executor("crm_tag_contact") is gated_actuators.execute_crm_tag
        assert get_executor("crm_log_contacted") is gated_actuators.execute_crm_contacted

    def test_schedule_routes_through_gate(self):
        repo, gate = _gate_with_fake_repo()
        with patch.object(gated_actuators, "run_cli",
                          side_effect=AssertionError("no side effect")):
            out = gated_actuators.crm_schedule_impl(
                {"contact": "Acme", "when": "2026-07-10", "summary": "send pilot terms"},
                {"org_id": 5, "draft_gate": gate})
        assert "[held for approval]" in out
        rec = repo.created[0]
        assert rec["action_type"] == "crm_schedule"
        assert rec["payload"]["contact"] == "Acme"
        assert rec["payload"]["org_id"] == 5

    def test_execute_schedule_builds_argv_and_env(self):
        seen = {}
        with patch.object(gated_actuators, "run_cli",
                          side_effect=lambda a, env=None: seen.update(argv=a, env=env) or "scheduled"), \
             patch.object(gated_actuators, "_crm_env", return_value={"ODOO_URL": "rtv"}):
            gated_actuators.execute_crm_schedule({"payload": {
                "contact": "Acme", "when": "2026-07-10", "summary": "terms", "org_id": 5}})
        assert seen["argv"] == ["odoo-cli", "schedule", "Acme", "2026-07-10", "terms"]
        assert seen["env"] == {"ODOO_URL": "rtv"}

    def test_execute_tag_builds_argv(self):
        seen = {}
        with patch.object(gated_actuators, "run_cli",
                          side_effect=lambda a, env=None: seen.update(argv=a) or "tagged"), \
             patch.object(gated_actuators, "_crm_env", return_value=None):
            gated_actuators.execute_crm_tag({"payload": {"contact": "Acme", "tag": "ally"}})
        assert seen["argv"] == ["odoo-cli", "contact-tag", "Acme", "ally"]

    def test_execute_schedule_raises_on_failure(self):
        import pytest
        with patch.object(gated_actuators, "run_cli",
                          side_effect=lambda a, env=None: "Error: odoo-cli exited 1"), \
             patch.object(gated_actuators, "_crm_env", return_value=None):
            with pytest.raises(RuntimeError, match="crm_schedule failed"):
                gated_actuators.execute_crm_schedule({"payload": {"contact": "X", "when": "2026-01-01"}})

    def test_write_tools_require_org_context(self):
        _, gate = _gate_with_fake_repo()
        for impl, inp in (
            (gated_actuators.crm_schedule_impl, {"contact": "A", "when": "2026-01-01"}),
            (gated_actuators.crm_tag_contact_impl, {"contact": "A", "tag": "x"}),
            (gated_actuators.crm_log_contacted_impl, {"contact": "A"}),
        ):
            assert "no org context" in impl(inp, {"draft_gate": gate})
