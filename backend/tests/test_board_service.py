"""Tests for the read-only dashboard board service.

Pure/deterministic: the parser and directory walk are tested against fixture
text and a temp repo dir. No Odoo, no Slack, no DB, no network. The one git
dependency (the MAIN.md link) is exercised via a real local git repo with a
fake remote, and separately shown to be optional (null when absent).
"""

import subprocess
from pathlib import Path

import pytest

from src.services import board_service as bs

CAMPAIGN_MD = """# Action Engine — Organizer Feedback

> _Facts + links only._

**One-liner:** Get it in front of real organizers before building more.
**Status:** active · **Owner:** Golda
**CRM campaign:** AE Organizer Feedback (Odoo) · **Taiga:** —

## Why this campaign
Some prose that should NOT be parsed as a **Bold:** field.

## Docs & links — the single home

| Item | Link |
|------|------|
| Proposal(s) | |
| Demo / site | https://action.cooperation.org |
| Repo / source | [ae](https://github.com/CivicWorks/ae) |
"""

TEMPLATE_MD = """# [Campaign Name]

**One-liner:** [what we're trying to make happen]
**Status:** [exploring | active] · **Owner:** [name]
**CRM campaign:** [Odoo name] · **Taiga:** [board link]
"""


def test_parse_header_fields():
    fields = bs._parse_header(CAMPAIGN_MD)
    assert fields["one_liner"].startswith("Get it in front")
    assert fields["status"] == "active"
    assert fields["owner"] == "Golda"
    assert fields["crm_campaign"] == "AE Organizer Feedback (Odoo)"
    assert fields["taiga"] == "—"


def test_header_stops_before_body_bold():
    # a **Bold:** inside the body must not leak into header fields
    fields = bs._parse_header(CAMPAIGN_MD)
    assert "bold" not in fields


def test_first_heading_skips_template_placeholder():
    assert bs._first_heading(CAMPAIGN_MD) == "Action Engine — Organizer Feedback"
    assert bs._first_heading(TEMPLATE_MD) is None  # "[Campaign Name]" -> None


def test_clean_value_treats_dashes_and_placeholders_as_empty():
    assert bs._clean_value("—") == ""
    assert bs._clean_value("[name]") == ""
    assert bs._clean_value("  active  ") == "active"


def test_parse_docs_links_only_rows_with_urls():
    rows = bs._parse_docs_links(CAMPAIGN_MD)
    urls = {r["label"]: r["url"] for r in rows}
    assert urls == {
        "Demo / site": "https://action.cooperation.org",
        "Repo / source": "https://github.com/CivicWorks/ae",
    }
    # empty "Proposal(s)" row and header/separator rows are excluded
    assert "Proposal(s)" not in urls
    assert "Item" not in urls


def test_remote_web_base_forms():
    # exercised indirectly; parse both SSH and HTTPS remote shapes
    def fake_git(repo, *args):
        if args[:2] == ("remote", "get-url"):
            return remote
        return None

    for remote, want in [
        ("git@github.com:Cooperation-org/projects.git", "https://github.com/Cooperation-org/projects"),
        ("https://github.com/Cooperation-org/projects.git", "https://github.com/Cooperation-org/projects"),
        ("git@gitlab.com:team/repo", "https://gitlab.com/team/repo"),
    ]:
        bs._git, orig = fake_git, bs._git
        try:
            assert bs._remote_web_base("/x") == want
        finally:
            bs._git = orig


def _init_repo(root: Path):
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin",
                    "git@github.com:Cooperation-org/projects.git"], check=True)
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "-b", "main"], check=True)


def test_read_board_walks_dir_and_skips_archived(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    campaigns = tmp_path / "campaigns"
    (campaigns / "ae-feedback").mkdir(parents=True)
    (campaigns / "ae-feedback" / "MAIN.md").write_text(CAMPAIGN_MD)
    # archived/ is skipped
    (campaigns / "archived").mkdir()
    (campaigns / "archived" / "MAIN.md").write_text(CAMPAIGN_MD)
    # a dir with no MAIN.md is skipped
    (campaigns / "empty").mkdir()

    monkeypatch.setattr(bs, "_org_context_repo", lambda org_id: str(tmp_path))
    monkeypatch.setattr(bs, "_maybe_pull", lambda repo: None)  # no network in tests

    out = bs.read_board(1, {"kind": "campaigns", "dir": "campaigns"})
    assert out["kind"] == "campaigns"
    assert len(out["items"]) == 1
    item = out["items"][0]
    assert item["slug"] == "ae-feedback"
    assert item["name"] == "Action Engine — Organizer Feedback"
    assert item["status"] == "active"
    assert item["owner"] == "Golda"
    assert item["crm_ref"] == "AE Organizer Feedback (Odoo)"
    assert item["taiga"] == ""  # '—' normalized to empty
    assert item["main_md_url"] == (
        "https://github.com/Cooperation-org/projects/blob/main/campaigns/ae-feedback/MAIN.md"
    )


def test_read_board_empty_when_unconfigured(monkeypatch):
    monkeypatch.setattr(bs, "_org_context_repo", lambda org_id: "/nope")
    assert bs.read_board(1, {}) == {"items": []}
    assert bs.read_board(1, {"kind": "campaigns"}) == {"items": []}  # no dir
    assert bs.read_board(0, {"dir": "campaigns"}) == {"items": []}   # no org


def test_read_board_empty_when_no_context_repo(monkeypatch):
    monkeypatch.setattr(bs, "_org_context_repo", lambda org_id: None)
    assert bs.read_board(1, {"kind": "campaigns", "dir": "campaigns"}) == {"items": []}


def test_read_board_dir_traversal_guarded(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "_org_context_repo", lambda org_id: str(tmp_path))
    monkeypatch.setattr(bs, "_maybe_pull", lambda repo: None)
    out = bs.read_board(1, {"kind": "campaigns", "dir": "../../etc"})
    assert out == {"items": []}
