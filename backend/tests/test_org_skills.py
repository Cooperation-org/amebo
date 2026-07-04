"""WP9: org-scoped skills. file_skill writes VERBATIM to the resolved org's
context-repo skills/ dir; list_skills / load_skill read core + org overlay."""

from __future__ import annotations

import uuid
import pytest

from src.db.connection import DatabaseConnection
from src.tools.cli_read_tools import (
    file_skill_impl, list_skills_impl, load_skill_impl,
)


def _uid():
    return uuid.uuid4().hex[:10]


@pytest.fixture
def org_ctx(tmp_path):
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug, context_repo) "
                "VALUES (%s, %s, %s) RETURNING org_id",
                (f"Skills {_uid()}", f"sk-{_uid()}", str(tmp_path)),
            )
            org_id = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)
    yield {"org_id": org_id}, tmp_path
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


class TestOrgSkills:
    def test_file_list_load_roundtrip(self, org_ctx):
        ctx, repo = org_ctx
        out = file_skill_impl(
            {"name": "Corporate Question",
             "content": "Lead with the 3-tier co-op structure, not price.",
             "status": "active"}, ctx)
        assert "Filed skill" in out
        f = repo / "skills" / "corporate-question.md"
        assert f.exists()
        body = f.read_text()
        assert "Lead with the 3-tier co-op structure, not price." in body  # verbatim
        assert "description:" in body and "status: active" in body          # summary separate
        assert "corporate-question" in list_skills_impl({}, ctx)
        loaded = load_skill_impl({"name": "corporate-question"}, ctx)
        assert "Lead with the 3-tier co-op structure, not price." in loaded

    def test_verbatim_preserved_exactly(self, org_ctx):
        ctx, _ = org_ctx
        content = "EXACT words matter.\n- first\n- second"
        file_skill_impl({"name": "verbatim test", "content": content}, ctx)
        loaded = load_skill_impl({"name": "verbatim-test"}, ctx)
        assert loaded.strip() == content.strip()

    def test_file_requires_an_org(self):
        out = file_skill_impl({"name": "x", "content": "y"}, {})
        assert "org" in out.lower()

    def test_status_validated(self, org_ctx):
        ctx, _ = org_ctx
        out = file_skill_impl({"name": "x", "content": "y", "status": "bogus"}, ctx)
        assert "status must be" in out

    def test_summary_defaults_to_first_line(self, org_ctx):
        ctx, repo = org_ctx
        file_skill_impl({"name": "auto sum", "content": "First line is the gist.\nmore"}, ctx)
        body = (repo / "skills" / "auto-sum.md").read_text()
        assert "description: First line is the gist." in body
