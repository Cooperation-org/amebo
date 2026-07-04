"""
WP3 tests: ConnectionResolver (org.yaml manifest + org_credentials -> connection).

as_subprocess_env + manifest validation are pure (temp files, no DB). resolve()
uses a real org row pointing at a temp context repo.
"""

from __future__ import annotations

import os
import uuid

import pytest

from src.db.connection import DatabaseConnection
from src.credentials import connections
from src.credentials.connections import (
    ToolConnection, resolve, ToolNotConfigured, ManifestInvalid, invalidate_cache,
)


def _uid():
    return uuid.uuid4().hex[:10]


# --- pure: per-kind env templates -------------------------------------------

class TestAsSubprocessEnv:
    def test_odoo_merges_manifest_and_secret(self):
        c = ToolConnection(
            org_id=1, tool_key="crm", kind="odoo_cli",
            base_url="https://crm.example",
            credential={"ODOO_USER": "svc", "ODOO_API_KEY": "sekret"},
            config={"db": "rtv_crm"},
        )
        env = c.as_subprocess_env()
        assert env == {"ODOO_URL": "https://crm.example", "ODOO_DB": "rtv_crm",
                       "ODOO_USER": "svc", "ODOO_API_KEY": "sekret"}

    def test_taiga_env(self):
        c = ToolConnection(
            org_id=1, tool_key="tasks", kind="mcp_taiga", base_url="https://taiga.example",
            credential={"TAIGA_USERNAME": "u", "TAIGA_PASSWORD": "p"}, config={"project": "rtv"},
        )
        env = c.as_subprocess_env()
        assert env["TAIGA_URL"] == "https://taiga.example"
        assert env["TAIGA_USERNAME"] == "u" and env["TAIGA_PASSWORD"] == "p"

    def test_no_credential_only_manifest_env(self):
        c = ToolConnection(org_id=1, tool_key="crm", kind="odoo_cli",
                           base_url="https://x", credential=None, config={})
        assert c.as_subprocess_env() == {"ODOO_URL": "https://x"}

    def test_secret_never_leaks_private_keys(self):
        c = ToolConnection(org_id=1, tool_key="tasks", kind="mcp_taiga", base_url=None,
                           credential={"TAIGA_USERNAME": "u", "_internal": "x"}, config={})
        assert "_internal" not in c.as_subprocess_env()


# --- manifest validation (temp files) ---------------------------------------

@pytest.fixture
def ctx_repo(tmp_path):
    invalidate_cache()
    yield str(tmp_path)
    invalidate_cache()


def _write_manifest(path, text):
    with open(os.path.join(path, "org.yaml"), "w") as fh:
        fh.write(text)


class TestManifestValidation:
    def test_missing_file(self, ctx_repo):
        with pytest.raises(ManifestInvalid):
            connections._load_manifest(ctx_repo, org_id=1)

    def test_bad_schema(self, ctx_repo):
        _write_manifest(ctx_repo, "schema: 99\ntools: {}\n")
        with pytest.raises(ManifestInvalid):
            connections._load_manifest(ctx_repo, org_id=1)

    def test_missing_tools(self, ctx_repo):
        _write_manifest(ctx_repo, "schema: 1\norg: x\n")
        with pytest.raises(ManifestInvalid):
            connections._load_manifest(ctx_repo, org_id=1)

    def test_valid(self, ctx_repo):
        _write_manifest(ctx_repo, "schema: 1\norg: x\ntools:\n  crm: {kind: odoo_cli}\n")
        m = connections._load_manifest(ctx_repo, org_id=1)
        assert m["tools"]["crm"]["kind"] == "odoo_cli"


# --- resolve() with a real org + temp context repo --------------------------

@pytest.fixture
def org_with_repo(tmp_path):
    invalidate_cache()
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug, context_repo) "
                "VALUES (%s, %s, %s) RETURNING org_id",
                (f"Conn Org {_uid()}", f"conn-{_uid()}", str(tmp_path)),
            )
            org_id = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)
    yield org_id, str(tmp_path)
    invalidate_cache()
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


class TestResolve:
    def test_resolve_tool_without_cred(self, org_with_repo):
        org_id, repo = org_with_repo
        _write_manifest(repo, "schema: 1\norg: x\ntools:\n"
                              "  projects: {kind: git_repo, path: /opt/shared/projects, active_dir: Active}\n")
        conn = resolve(org_id, "projects")
        assert conn.kind == "git_repo" and conn.credential is None
        assert conn.config["active_dir"] == "Active"

    def test_absent_tool_is_ToolNotConfigured(self, org_with_repo):
        org_id, repo = org_with_repo
        _write_manifest(repo, "schema: 1\norg: x\ntools:\n  crm: {kind: odoo_cli}\n")
        with pytest.raises(ToolNotConfigured):
            resolve(org_id, "tasks")            # not in the manifest

    def test_missing_cred_secret_is_ToolNotConfigured(self, org_with_repo):
        org_id, repo = org_with_repo
        _write_manifest(repo, "schema: 1\norg: x\ntools:\n"
                              "  crm: {kind: odoo_cli, base_url: 'https://x', cred: nope-service}\n")
        # manifest references a cred label with no stored secret -> not configured
        with pytest.raises(ToolNotConfigured):
            resolve(org_id, "crm")

    def test_no_context_repo_is_ToolNotConfigured(self):
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO organizations (org_name, org_slug) VALUES (%s,%s) RETURNING org_id",
                    (f"NoRepo {_uid()}", f"norepo-{_uid()}"),
                )
                org_id = cur.fetchone()[0]
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)
        try:
            with pytest.raises(ToolNotConfigured):
                resolve(org_id, "crm")
        finally:
            conn = DatabaseConnection.get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
                    conn.commit()
            finally:
                DatabaseConnection.return_connection(conn)
