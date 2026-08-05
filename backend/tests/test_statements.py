"""
Tests for org statements — the org's named pointers to what it is aiming at.

Storage runs against the real DB (same as the other repo tests). Pointer
resolution is exercised without the network: the URL reader is patched, and the
repo/abra readers are checked for their refusal cases, which are the ones that
matter (a pointer must not become a way to read the VM's filesystem).
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.db.connection import DatabaseConnection
from src.db.repositories.statement_repo import StatementRepo
from src.services import statements as svc


@pytest.fixture
def org_id():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) "
                "VALUES ('Statements Test', 'stmt-test-' || md5(random()::text)) "
                "RETURNING org_id"
            )
            oid = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)

    yield oid

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM org_statements WHERE org_id = %s", (oid,))
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (oid,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


# ------------------------------------------------------------------ storage

def test_words_and_pointer_are_exclusive(org_id):
    """A row is either the words or where they live. Both, or neither, is a
    statement that cannot be read one way."""
    repo = StatementRepo()
    with pytest.raises(Exception):
        repo.add(org_id, "mission", body="we do the thing",
                 pointer="https://example.org/mission")
    with pytest.raises(Exception):
        repo.add(org_id, "mission")


def test_a_person_writing_one_accepts_it(org_id):
    row = StatementRepo().add(org_id, "mission", body="we do the thing",
                              written_by="golda@example.org", accepted=True)
    assert row["accepted_at"] is not None
    assert row["holder"] == "org"


def test_a_proposal_is_inert_until_accepted(org_id):
    """Amebo may propose. Until a human keeps it, nothing reads it."""
    repo = StatementRepo()
    row = repo.add(org_id, "mission", body="a guess from a transcript",
                   written_by="claw", accepted=False, informs_priority=True)
    assert row["accepted_at"] is None
    assert repo.live_for_org(org_id) == []

    repo.update(row["id"], org_id, {}, written_by="golda@example.org", accept=True)
    assert [r["id"] for r in repo.live_for_org(org_id)] == [row["id"]]


def test_switched_off_does_not_steer(org_id):
    repo = StatementRepo()
    repo.add(org_id, "values", body="kindness", accepted=True,
             informs_priority=False)
    assert repo.live_for_org(org_id) == []


def test_another_org_cannot_read_or_change_it(org_id):
    repo = StatementRepo()
    row = repo.add(org_id, "mission", body="ours", accepted=True)
    assert repo.get(row["id"], org_id + 999_999) is None
    assert repo.update(row["id"], org_id + 999_999, {"name": "theirs"}) is None
    assert repo.delete(row["id"], org_id + 999_999) is False
    assert repo.get(row["id"], org_id)["name"] == "mission"


def test_editing_carries_authorship(org_id):
    """A proposal a person corrected becomes that person's words."""
    repo = StatementRepo()
    row = repo.add(org_id, "mission", body="amebo's phrasing",
                   written_by="claw", accepted=False)
    fixed = repo.update(row["id"], org_id, {"body": "her phrasing"},
                        written_by="golda@example.org", accept=True)
    assert fixed["body"] == "her phrasing"
    assert fixed["written_by"] == "golda@example.org"


def test_delete_removes_it(org_id):
    repo = StatementRepo()
    row = repo.add(org_id, "old mission", body="outgrown", accepted=True)
    assert repo.delete(row["id"], org_id) is True
    assert repo.get(row["id"], org_id) is None


# --------------------------------------------------------------- resolution

def test_pasted_words_come_back_verbatim():
    assert svc.resolve({"body": "  we help people prove what they did  "}, 1) \
        == "we help people prove what they did"


def test_url_pointer_is_read(org_id):
    with patch("src.tools.http_fetch.http_fetch", return_value="from the web"):
        assert svc.resolve({"pointer": "https://example.org/m"}, org_id) == "from the web"


def test_unreadable_url_contributes_nothing(org_id):
    with patch("src.tools.http_fetch.http_fetch", return_value="Error: refused"):
        assert svc.resolve({"pointer": "https://example.org/m"}, org_id) is None


def test_unknown_scheme_is_not_an_error(org_id):
    """A pointer nobody can follow yet is still worth writing down."""
    assert svc.resolve({"pointer": "gdoc:1a2b3c"}, org_id) is None


def test_repo_pointer_cannot_escape_the_context_repo(org_id, tmp_path):
    """The pointer is a URI a person types. It must not become a way to read
    /etc/passwd."""
    (tmp_path / "mission.md").write_text("inside the repo")
    with patch("src.db.repositories.org_repo.OrgRepo.get",
               return_value={"context_repo": str(tmp_path)}):
        assert svc.resolve({"pointer": "repo:mission.md"}, org_id) == "inside the repo"
        assert svc.resolve({"pointer": "repo:../../etc/passwd"}, org_id) is None
        assert svc.resolve({"pointer": "repo:/etc/passwd"}, org_id) is None


def test_no_context_repo_reads_nothing(org_id):
    with patch("src.db.repositories.org_repo.OrgRepo.get", return_value={}):
        assert svc.resolve({"pointer": "repo:mission.md"}, org_id) is None


def test_long_documents_are_capped(org_id):
    assert len(svc.resolve({"body": "x" * (svc.MAX_CHARS * 2)}, org_id)) == svc.MAX_CHARS


# ------------------------------------------------------------------ context

def test_live_context_is_name_words_and_id(org_id):
    row = StatementRepo().add(org_id, "Q3 OKRs", body="ship the thing",
                              accepted=True, informs_priority=True)
    assert svc.live_context(org_id) == [("Q3 OKRs", "ship the thing", row["id"])]


def test_a_pointer_nobody_can_read_drops_out(org_id):
    """It stays on the page so it can be fixed; it just contributes no words."""
    StatementRepo().add(org_id, "strategy", pointer="gdoc:missing",
                        accepted=True, informs_priority=True)
    assert svc.live_context(org_id) == []


def test_saying_nothing_is_a_normal_state(org_id):
    assert svc.live_context(org_id) == []


def test_headings_are_the_teams_own_words():
    out = svc.as_prompt_sections([("operating principles", "be kind", 1)])
    assert out == "## operating principles\nbe kind"


def test_store_being_down_does_not_stop_a_goal(org_id):
    with patch("src.db.repositories.statement_repo.StatementRepo.live_for_org",
               side_effect=RuntimeError("db down")):
        assert svc.live_context(org_id) == []
