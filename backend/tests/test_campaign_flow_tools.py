"""
Tests for the create-campaign flow tools (board 2026-07-05):
read_org_file, area-aware MAIN.md tools, and the gated CRM
contact/campaign writes (argv correctness — the side effect itself is
gated and only runs on human approval).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tools import main_md_tools, gated_actuators
from src.credentials.connections import ToolNotConfigured


# ---------------------------------------------------------------------------
# read_org_file
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """A fake org context repo, wired as org 7's context_repo pointer."""
    (tmp_path / "Active" / "alpha").mkdir(parents=True)
    (tmp_path / "Active" / "alpha" / "MAIN.md").write_text("# Alpha\n")
    (tmp_path / "proposals").mkdir()
    (tmp_path / "proposals" / "pitch.md").write_text("# Pitch\nbody\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n")
    import src.credentials.connections as connections
    monkeypatch.setattr(
        connections, "_org_context_repo",
        lambda org_id: str(tmp_path) if org_id == 7 else None,
    )
    return tmp_path


class TestReadOrgFile:
    def test_reads_a_file(self, fake_repo):
        out = main_md_tools.read_org_file_impl({"path": "proposals/pitch.md"}, {"org_id": 7})
        assert "# Pitch" in out and "body" in out

    def test_lists_a_directory(self, fake_repo):
        out = main_md_tools.read_org_file_impl({"path": "."}, {"org_id": 7})
        assert "proposals/" in out and "Active/" in out
        assert ".git" not in out

    def test_escape_rejected(self, fake_repo):
        out = main_md_tools.read_org_file_impl({"path": "../../etc/passwd"}, {"org_id": 7})
        assert "outside" in out.lower()

    def test_git_dir_refused(self, fake_repo):
        out = main_md_tools.read_org_file_impl({"path": ".git/config"}, {"org_id": 7})
        assert ".git is not readable" in out

    def test_missing_file(self, fake_repo):
        out = main_md_tools.read_org_file_impl({"path": "nope.md"}, {"org_id": 7})
        assert "no such file" in out.lower()

    def test_requires_org_context(self, fake_repo):
        out = main_md_tools.read_org_file_impl({"path": "proposals/pitch.md"}, {})
        assert "requires an org context" in out

    def test_org_without_repo_pointer_refused(self, fake_repo):
        out = main_md_tools.read_org_file_impl({"path": "x"}, {"org_id": 8})
        assert "no context repo" in out


# ---------------------------------------------------------------------------
# area-aware _projects_root
# ---------------------------------------------------------------------------

class _FakeConn:
    def __init__(self, config):
        self.config = config


class TestNamedAreas:
    def _wire(self, monkeypatch, tmp_path):
        import src.credentials.connections as connections
        (tmp_path / "campaigns").mkdir(exist_ok=True)
        monkeypatch.setattr(
            connections, "resolve",
            lambda org_id, tool_key: _FakeConn({
                "path": str(tmp_path), "active_dir": "Active",
                "named_dirs": {"campaigns": "campaigns"},
            }),
        )

    def test_area_resolves_named_dir(self, monkeypatch, tmp_path):
        self._wire(monkeypatch, tmp_path)
        root = main_md_tools._projects_root({"org_id": 7}, "campaigns")
        assert root == (tmp_path / "campaigns").resolve()

    def test_undeclared_area_refused(self, monkeypatch, tmp_path):
        self._wire(monkeypatch, tmp_path)
        with pytest.raises(ToolNotConfigured):
            main_md_tools._projects_root({"org_id": 7}, "secrets")

    def test_area_never_uses_legacy_fallback(self, monkeypatch):
        import src.credentials.connections as connections
        monkeypatch.setenv("LEGACY_ENV_ORG_ID", "7")
        def boom(org_id, tool_key):
            raise ToolNotConfigured(org_id, tool_key)
        monkeypatch.setattr(connections, "resolve", boom)
        # default root: legacy falls back; a named area NEVER does
        assert main_md_tools._projects_root({"org_id": 7}) == main_md_tools.ACTIVE_PROJECTS_ROOT
        with pytest.raises(ToolNotConfigured):
            main_md_tools._projects_root({"org_id": 7}, "campaigns")

    def test_create_main_md_in_area(self, monkeypatch, tmp_path):
        self._wire(monkeypatch, tmp_path)
        out = main_md_tools.create_main_md_impl(
            {"project_slug": "crewcomm", "area": "campaigns",
             "content": ("# CrewComm\n\n**One-liner:** SMS intake for contractor crews\n"
                         "**Status:** exploring · **Owner:** Golda\n\n## Why this campaign\n"
                         "Jefferson will partner on representing the contractor tool.\n")},
            {"org_id": 7},
        )
        assert (tmp_path / "campaigns" / "crewcomm" / "MAIN.md").is_file()
        assert "crewcomm" in out


# ---------------------------------------------------------------------------
# gated CRM writes — executor argv correctness (run_cli captured, not run)
# ---------------------------------------------------------------------------

class TestCampaignCrmExecutors:
    @pytest.fixture
    def cli(self, monkeypatch):
        calls = []
        def fake_run_cli(argv, env=None, **kw):
            calls.append(argv)
            return "ok"
        monkeypatch.setattr(gated_actuators, "run_cli", fake_run_cli)
        monkeypatch.setattr(gated_actuators, "_crm_env", lambda p: None)
        return calls

    def test_create_contact_argv(self, cli):
        out = gated_actuators.execute_crm_create_contact(
            {"payload": {"name": "Jefferson Davis", "email": "j@x.com", "org_id": 1}})
        assert cli == [["odoo-cli", "contact-create", "Jefferson Davis", "j@x.com"]]
        assert out == "ok"

    def test_campaign_create_argv_with_ref(self, cli):
        gated_actuators.execute_campaign_create(
            {"payload": {"name": "CrewComm", "project_ref": "campaigns/crewcomm/MAIN.md", "org_id": 1}})
        assert cli == [["odoo-cli", "campaign-create", "CrewComm", "campaigns/crewcomm/MAIN.md"]]

    def test_campaign_link_argv(self, cli):
        gated_actuators.execute_campaign_link(
            {"payload": {"campaign": "CrewComm", "contact": "Jefferson", "summary": "SMS pilot", "org_id": 1}})
        assert cli == [["odoo-cli", "campaign-link", "CrewComm", "Jefferson", "SMS pilot"]]

    def test_missing_payload_fields_error(self, cli):
        out = gated_actuators.execute_crm_create_contact({"payload": {"name": "x"}})
        assert out.startswith("Error:") and cli == []


class TestCampaignCrmImplsAreGated:
    """The impls must route through the gate (draft), never execute directly."""

    @pytest.fixture
    def gate_spy(self, monkeypatch):
        drafts = []
        def fake_route(**kw):
            drafts.append(kw)
            return f"DRAFTED: {kw['preview']}"
        monkeypatch.setattr(gated_actuators, "_route_through_gate", fake_route)
        return drafts

    def test_create_contact_drafts(self, gate_spy):
        out = gated_actuators.crm_create_contact_impl(
            {"name": "Jefferson", "email": "j@x.com"}, {"org_id": 1})
        assert out.startswith("DRAFTED:")
        assert gate_spy[0]["action_type"] == "crm_create_contact"
        assert gate_spy[0]["payload"]["email"] == "j@x.com"

    def test_campaign_create_drafts(self, gate_spy):
        gated_actuators.campaign_create_impl(
            {"name": "CrewComm", "project_ref": "campaigns/crewcomm/MAIN.md"}, {"org_id": 1})
        assert gate_spy[0]["action_type"] == "campaign_create"
        assert gate_spy[0]["payload"]["project_ref"] == "campaigns/crewcomm/MAIN.md"

    def test_campaign_link_drafts(self, gate_spy):
        gated_actuators.campaign_link_impl(
            {"campaign": "CrewComm", "contact": "Jefferson"}, {"org_id": 1})
        assert gate_spy[0]["action_type"] == "campaign_link"

    def test_input_validation(self, gate_spy):
        out = gated_actuators.crm_create_contact_impl({"name": "x"}, {"org_id": 1})
        assert out.startswith("Error:") and gate_spy == []


def test_new_action_types_are_gated_by_default():
    from src.services.gated_actions import requires_approval
    for t in ("crm_create_contact", "campaign_create", "campaign_link"):
        assert requires_approval(t)
