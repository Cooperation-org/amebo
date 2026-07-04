"""
WP5 tests: Odoo/CRM tools resolve their connection per-org via the org.yaml
manifest (ToolConnection), falling back to the process env when the org has no
manifest yet (transition). Real DB org + temp context repo.
"""

from __future__ import annotations

import os
import uuid

import pytest

from src.db.connection import DatabaseConnection
from src.credentials.connections import invalidate_cache
from src.tools.cli_read_tools import _crm_conf, _conn_env, _org_id_from_context


def _uid():
    return uuid.uuid4().hex[:10]


@pytest.fixture
def org_with_crm_manifest(tmp_path):
    invalidate_cache()
    with open(os.path.join(str(tmp_path), "org.yaml"), "w") as fh:
        fh.write(
            "schema: 1\norg: rtv\ntools:\n"
            "  crm: {kind: odoo_cli, base_url: 'https://crm.rtv.example', db: rtv_crm}\n"
        )
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug, context_repo) "
                "VALUES (%s, %s, %s) RETURNING org_id",
                (f"RTV {_uid()}", f"rtv-{_uid()}", str(tmp_path)),
            )
            org_id = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)
    yield org_id
    invalidate_cache()
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


class TestCrmRouting:
    def test_org_id_extracted_from_context(self):
        assert _org_id_from_context({"org_id": 5}) == 5
        assert _org_id_from_context({}) is None
        assert _org_id_from_context("nope") is None

    def test_manifest_org_gets_its_own_crm_endpoint(self, org_with_crm_manifest):
        conf = _crm_conf({"org_id": org_with_crm_manifest})
        assert conf["ODOO_URL"] == "https://crm.rtv.example"
        assert conf["ODOO_DB"] == "rtv_crm"

    def test_conn_env_returns_none_without_manifest(self):
        # org with no context repo -> no manifest -> None (tool falls back to env)
        assert _conn_env({"org_id": None}, "crm") is None

    def test_crm_conf_falls_back_to_process_env(self, monkeypatch):
        monkeypatch.setenv("ODOO_URL", "https://fallback.example")
        monkeypatch.setenv("ODOO_DB", "fallback_db")
        conf = _crm_conf({})   # no org -> fallback
        assert conf["ODOO_URL"] == "https://fallback.example"
        assert conf["ODOO_DB"] == "fallback_db"

    def test_two_orgs_hit_different_endpoints(self, org_with_crm_manifest, monkeypatch):
        monkeypatch.setenv("ODOO_URL", "https://linkedtrust.example")
        # org A (manifest) vs the env-fallback org (no manifest)
        a = _crm_conf({"org_id": org_with_crm_manifest})["ODOO_URL"]
        b = _crm_conf({})["ODOO_URL"]
        assert a == "https://crm.rtv.example"
        assert b == "https://linkedtrust.example"
        assert a != b


# --- WP7: projects root per org ---------------------------------------------

from pathlib import Path
from src.tools.main_md_tools import _projects_root, _project_dir, ACTIVE_PROJECTS_ROOT


@pytest.fixture
def org_with_projects_manifest(tmp_path):
    invalidate_cache()
    base = tmp_path / "orgrepo"
    (base / "Active").mkdir(parents=True)
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    with open(ctx / "org.yaml", "w") as fh:
        fh.write(
            "schema: 1\norg: rtv\ntools:\n"
            f"  projects: {{kind: git_repo, path: '{base}', active_dir: Active}}\n"
        )
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug, context_repo) "
                "VALUES (%s, %s, %s) RETURNING org_id",
                (f"Proj {_uid()}", f"proj-{_uid()}", str(ctx)),
            )
            org_id = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)
    yield org_id, base
    invalidate_cache()
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


class TestProjectsRouting:
    def test_root_from_manifest(self, org_with_projects_manifest):
        org_id, base = org_with_projects_manifest
        assert _projects_root({"org_id": org_id}) == (base / "Active").resolve()

    def test_root_falls_back_to_shared(self):
        assert _projects_root({}) == ACTIVE_PROJECTS_ROOT

    def test_project_dir_under_org_root(self, org_with_projects_manifest):
        org_id, base = org_with_projects_manifest
        got = _project_dir("myproj", {"org_id": org_id})
        assert got == (base / "Active" / "myproj").resolve()


# --- WP8: abra scope from the manifest --------------------------------------

import src.tools.cli_read_tools as _clir
from src.tools.cli_read_tools import abra_search_impl


@pytest.fixture
def org_with_knowledge_manifest(tmp_path):
    invalidate_cache()
    with open(os.path.join(str(tmp_path), "org.yaml"), "w") as fh:
        fh.write(
            "schema: 1\norg: rtv\ntools:\n"
            "  knowledge: {kind: abra, scope: rtv-scope}\n"
        )
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug, context_repo) "
                "VALUES (%s, %s, %s) RETURNING org_id",
                (f"Kn {_uid()}", f"kn-{_uid()}", str(tmp_path)),
            )
            org_id = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)
    yield org_id
    invalidate_cache()
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


class TestAbraScope:
    def test_about_applies_org_scope(self, org_with_knowledge_manifest, monkeypatch):
        seen = {}
        monkeypatch.setattr(_clir, "run_cli",
                            lambda argv, timeout=10, env=None: seen.setdefault("argv", argv) or "ok")
        abra_search_impl({"query": "peter", "mode": "about"},
                         {"org_id": org_with_knowledge_manifest})
        assert "--scope" in seen["argv"] and "rtv-scope" in seen["argv"]

    def test_search_never_adds_scope(self, org_with_knowledge_manifest, monkeypatch):
        seen = {}
        monkeypatch.setattr(_clir, "run_cli",
                            lambda argv, timeout=10, env=None: seen.setdefault("argv", argv) or "ok")
        abra_search_impl({"query": "x", "mode": "search"},
                         {"org_id": org_with_knowledge_manifest})
        assert "--scope" not in seen["argv"]
