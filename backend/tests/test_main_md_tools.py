"""
Tests for read_main_md / list_projects / edit_main_md.

The tools point at the real /opt/shared/projects/Active/ root on this VM.
To stay isolated, we monkey-patch ACTIVE_PROJECTS_ROOT to a tmp dir per
test class. That exercises the same code path as production without
risking the real projects/ repo.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.tools import main_md_tools


@pytest.fixture
def fake_active_root(tmp_path, monkeypatch):
    """Redirect ACTIVE_PROJECTS_ROOT to a tmp dir for the test."""
    root = tmp_path / "Active"
    root.mkdir()
    monkeypatch.setattr(main_md_tools, "ACTIVE_PROJECTS_ROOT", root.resolve())

    # Seed a couple of projects
    (root / "alpha").mkdir()
    (root / "alpha" / "MAIN.md").write_text(
        "# Alpha\n\n**Team Lead:** Someone\n**Slack Channel:**\n",
        encoding="utf-8",
    )
    (root / "beta").mkdir()
    (root / "beta" / "MAIN.md").write_text(
        "# Beta\n\nLine A\nLine B\nLine C\n",
        encoding="utf-8",
    )
    # A directory without MAIN.md should not show up in list_projects
    (root / "no-main").mkdir()
    yield root


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------


class TestListProjects:
    def test_lists_only_dirs_with_main_md(self, fake_active_root):
        out = main_md_tools.list_projects_impl({}, {})
        assert "alpha" in out
        assert "beta" in out
        assert "no-main" not in out


# ---------------------------------------------------------------------------
# read_main_md
# ---------------------------------------------------------------------------


class TestReadMainMd:
    def test_returns_content(self, fake_active_root):
        out = main_md_tools.read_main_md_impl({"project_slug": "alpha"}, {})
        assert "Team Lead" in out
        assert "Path:" in out

    def test_missing_project(self, fake_active_root):
        out = main_md_tools.read_main_md_impl({"project_slug": "missing"}, {})
        assert "no main.md" in out.lower()

    def test_empty_slug(self, fake_active_root):
        out = main_md_tools.read_main_md_impl({"project_slug": ""}, {})
        assert "Error" in out

    def test_invalid_slug_chars(self, fake_active_root):
        out = main_md_tools.read_main_md_impl({"project_slug": "../etc"}, {})
        assert "Error" in out

    def test_absolute_path_rejected(self, fake_active_root):
        out = main_md_tools.read_main_md_impl({"project_slug": "/etc/passwd"}, {})
        assert "Error" in out


# ---------------------------------------------------------------------------
# edit_main_md
# ---------------------------------------------------------------------------


class TestEditMainMd:
    def test_happy_path(self, fake_active_root):
        out = main_md_tools.edit_main_md_impl(
            {
                "project_slug": "alpha",
                "old_string": "**Slack Channel:**",
                "new_string": "**Slack Channel:** #c-alpha",
            },
            {},
        )
        assert "Edited" in out and "Diff:" in out
        content = (fake_active_root / "alpha" / "MAIN.md").read_text()
        assert "#c-alpha" in content

    def test_old_string_not_found(self, fake_active_root):
        out = main_md_tools.edit_main_md_impl(
            {"project_slug": "alpha", "old_string": "ZZZ", "new_string": "yy"},
            {},
        )
        assert "not found" in out.lower()

    def test_old_string_not_unique(self, fake_active_root):
        (fake_active_root / "alpha" / "MAIN.md").write_text(
            "foo\nfoo\nfoo\n", encoding="utf-8",
        )
        out = main_md_tools.edit_main_md_impl(
            {"project_slug": "alpha", "old_string": "foo", "new_string": "bar"},
            {},
        )
        assert "unique" in out.lower()

    def test_identical_strings_rejected(self, fake_active_root):
        out = main_md_tools.edit_main_md_impl(
            {"project_slug": "alpha", "old_string": "x", "new_string": "x"},
            {},
        )
        assert "identical" in out.lower()

    def test_path_escape_via_slug_rejected(self, fake_active_root):
        out = main_md_tools.edit_main_md_impl(
            {
                "project_slug": "../../../tmp/evil",
                "old_string": "x",
                "new_string": "y",
            },
            {},
        )
        assert "error" in out.lower()

    def test_symlink_escape_rejected(self, fake_active_root, tmp_path):
        # Create a symlink inside Active/ pointing outside, then try to edit
        outside = tmp_path / "outside_target"
        outside.mkdir()
        (outside / "MAIN.md").write_text("# outside\n", encoding="utf-8")
        symlink_dir = fake_active_root / "escape"
        os.symlink(outside, symlink_dir)

        out = main_md_tools.edit_main_md_impl(
            {
                "project_slug": "escape",
                "old_string": "outside",
                "new_string": "PWNED",
            },
            {},
        )
        # The path resolves outside the root → must refuse
        assert "outside" in out.lower() or "error" in out.lower()
        # Verify the outside file was NOT modified
        assert (outside / "MAIN.md").read_text() == "# outside\n"

    def test_writes_diff_in_response(self, fake_active_root):
        out = main_md_tools.edit_main_md_impl(
            {
                "project_slug": "beta",
                "old_string": "Line B",
                "new_string": "Line BBB",
            },
            {},
        )
        assert "-Line B" in out
        assert "+Line BBB" in out


# ---------------------------------------------------------------------------
# Cross-tenant fallback guard for the filesystem root (Fable, 2026-07-05) —
# same rule as cli_read_tools._conn: only the LEGACY_ENV_ORG_ID org may fall
# back to the shared ACTIVE_PROJECTS_ROOT; every other org with a missing/
# broken projects config must RAISE. These tools WRITE, so a silent fallback
# would land org B's files in org A's repo.
# ---------------------------------------------------------------------------

from src.credentials.connections import ToolNotConfigured


class _FakeConn:
    def __init__(self, config):
        self.config = config


class TestProjectsRootLegacyScoping:
    def _raise_not_configured(self, org_id, tool_key):
        raise ToolNotConfigured(org_id, tool_key)

    def test_non_legacy_org_never_falls_back(self, monkeypatch):
        import src.credentials.connections as connections
        monkeypatch.setenv("LEGACY_ENV_ORG_ID", "999999")  # someone else
        monkeypatch.setattr(connections, "resolve", self._raise_not_configured)
        with pytest.raises(ToolNotConfigured):
            main_md_tools._projects_root({"org_id": 2})

    def test_legacy_org_still_falls_back(self, monkeypatch):
        import src.credentials.connections as connections
        monkeypatch.setenv("LEGACY_ENV_ORG_ID", "2")
        monkeypatch.setattr(connections, "resolve", self._raise_not_configured)
        root = main_md_tools._projects_root({"org_id": 2})
        assert root == main_md_tools.ACTIVE_PROJECTS_ROOT

    def test_unset_means_strict_for_everyone(self, monkeypatch):
        import src.credentials.connections as connections
        monkeypatch.delenv("LEGACY_ENV_ORG_ID", raising=False)
        monkeypatch.setattr(connections, "resolve", self._raise_not_configured)
        with pytest.raises(ToolNotConfigured):
            main_md_tools._projects_root({"org_id": 2})

    def test_no_org_context_is_untouched_legacy_path(self, monkeypatch):
        monkeypatch.delenv("LEGACY_ENV_ORG_ID", raising=False)
        assert main_md_tools._projects_root({}) == main_md_tools.ACTIVE_PROJECTS_ROOT
        assert main_md_tools._projects_root(None) == main_md_tools.ACTIVE_PROJECTS_ROOT

    def test_configured_org_gets_its_own_root(self, monkeypatch, tmp_path):
        import src.credentials.connections as connections
        monkeypatch.delenv("LEGACY_ENV_ORG_ID", raising=False)
        own = tmp_path / "their-repo"
        own.mkdir()
        monkeypatch.setattr(
            connections, "resolve",
            lambda org_id, tool_key: _FakeConn({"path": str(own), "active_dir": "Active"}),
        )
        assert main_md_tools._projects_root({"org_id": 2}) == (own / "Active").resolve()

    def test_config_without_path_raises_for_non_legacy(self, monkeypatch):
        import src.credentials.connections as connections
        monkeypatch.delenv("LEGACY_ENV_ORG_ID", raising=False)
        monkeypatch.setattr(connections, "resolve", lambda org_id, tool_key: _FakeConn({}))
        with pytest.raises(ToolNotConfigured):
            main_md_tools._projects_root({"org_id": 2})

    def test_resolver_crash_raises_for_non_legacy(self, monkeypatch):
        import src.credentials.connections as connections
        monkeypatch.delenv("LEGACY_ENV_ORG_ID", raising=False)

        def boom(org_id, tool_key):
            raise RuntimeError("db down")
        monkeypatch.setattr(connections, "resolve", boom)
        with pytest.raises(RuntimeError):
            main_md_tools._projects_root({"org_id": 2})
