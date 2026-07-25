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


# --- WP8 tail: knowledge scope passed into KB search / lookup ---------------

from src.tools.registry import _knowledge_scope


class TestKnowledgeScope:
    def test_scope_from_manifest(self, org_with_knowledge_manifest):
        assert _knowledge_scope({"org_id": org_with_knowledge_manifest}) == "rtv-scope"

    def test_scope_none_without_manifest(self):
        assert _knowledge_scope({}) is None


# --- Cross-tenant fallback guard (Fable review finding, 2026-07-05) ---------
#
# The process env holds the LEGACY org's credentials. Only that org (env
# LEGACY_ENV_ORG_ID) may fall back to it; any other org with a missing/broken
# manifest must RAISE, never silently misroute through the legacy org's
# accounts.

from src.credentials.connections import ToolNotConfigured, ManifestInvalid
from src.tools.cli_read_tools import _conn


@pytest.fixture
def org_without_manifest(tmp_path):
    """An org whose context repo exists but has no org.yaml at all."""
    invalidate_cache()
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug, context_repo) "
                "VALUES (%s, %s, %s) RETURNING org_id",
                (f"NoManifest {_uid()}", f"nomanifest-{_uid()}", str(tmp_path)),
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


class TestLegacyFallbackScoping:
    def test_non_legacy_org_never_falls_back(self, org_without_manifest, monkeypatch):
        monkeypatch.setenv("LEGACY_ENV_ORG_ID", "999999")  # someone else
        with pytest.raises((ToolNotConfigured, ManifestInvalid)):
            _conn({"org_id": org_without_manifest}, "crm")

    def test_legacy_org_still_falls_back(self, org_without_manifest, monkeypatch):
        monkeypatch.setenv("LEGACY_ENV_ORG_ID", str(org_without_manifest))
        assert _conn({"org_id": org_without_manifest}, "crm") is None

    def test_unset_means_strict_for_everyone(self, org_without_manifest, monkeypatch):
        monkeypatch.delenv("LEGACY_ENV_ORG_ID", raising=False)
        with pytest.raises((ToolNotConfigured, ManifestInvalid)):
            _conn({"org_id": org_without_manifest}, "crm")

    def test_no_org_context_is_untouched_legacy_path(self):
        assert _conn({}, "crm") is None


# --- SECURITY e2e: cross-tenant credential isolation ------------------------
import src.tools.cli_read_tools as _clir2
from src.tools.cli_read_tools import odoo_search_impl, taiga_list_impl, abra_search_impl


@pytest.fixture
def org_without_manifest():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO organizations (org_name, org_slug) "
                        "VALUES ('OrgB', 'orgb-' || md5(random()::text)) RETURNING org_id")
            oid = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)
    yield oid
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (oid,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


class TestCrossTenantIsolation:
    """The process env holds the LEGACY org's creds. A non-legacy org with no
    manifest must NEVER reach a subprocess with them — it gets a friendly
    'not connected' message, and run_cli is never called."""

    def test_non_legacy_org_never_runs_cli_with_env_creds(self, org_without_manifest, monkeypatch):
        monkeypatch.setenv("LEGACY_ENV_ORG_ID", "1")  # linkedtrust is legacy, org B is not
        calls = []
        monkeypatch.setattr(_clir2, "run_cli",
                            lambda argv, **kw: calls.append((argv, kw.get("env"))) or "SHOULD NOT RUN")
        ctx = {"org_id": org_without_manifest}
        # every routed read must refuse, not misroute
        assert "connected" in odoo_search_impl({"query": "acme"}, ctx).lower()
        assert "connected" in taiga_list_impl({"project": "x"}, ctx).lower()
        assert "connected" in abra_search_impl({"query": "x", "mode": "about"}, ctx).lower()
        assert calls == []   # NO subprocess ran — no chance to use legacy creds

    def test_legacy_org_does_fall_back_to_env(self, monkeypatch):
        # org 1 (linkedtrust) with no manifest IS allowed the env fallback
        monkeypatch.setenv("LEGACY_ENV_ORG_ID", "1")
        calls = []
        monkeypatch.setattr(_clir2, "run_cli",
                            lambda argv, **kw: calls.append((argv, kw.get("env"))) or "ok")
        odoo_search_impl({"query": "acme"}, {"org_id": 1})
        assert len(calls) == 1 and calls[0][1] is None  # ran, with process env (env overlay None)


# --- Per-team CRM database on the shared-credential fallback -----------------
# On a cohort VM every team org shares one set of Odoo credentials, but ODOO_DB
# was a single fixed value, so every team's CRM tools read the SAME database
# instead of their own crm-<slug>. ODOO_TEAM_DB_PATTERN supplies just that one
# variable per team. Dormant unless set — these tests pin both directions.

from src.tools.cli_read_tools import _team_crm_db, _routed_env


@pytest.fixture
def team_org():
    """A plain org with a slug and NO manifest — the cohort shape."""
    slug = f"team-{_uid()}"
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) VALUES (%s, %s) "
                "RETURNING org_id", (f"Team {slug}", slug))
            org_id = cur.fetchone()[0]
            conn.commit()
        yield org_id, slug
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
        DatabaseConnection.return_connection(conn)


class TestPerTeamCrmDatabase:
    @pytest.fixture(autouse=True)
    def cohort_shape(self, monkeypatch):
        """The cohort VM's declared shape: one shared credential pool, so every
        org reaches the env fallback. Without this a manifest-less org fails
        closed instead (the team-instance shape) and never gets here at all."""
        monkeypatch.setenv("ENV_CREDENTIALS_SHARED", "1")
        invalidate_cache()

    def test_unset_pattern_changes_nothing(self, team_org, monkeypatch):
        """The default: behaviour is exactly what it was before this existed."""
        org_id, _ = team_org
        monkeypatch.delenv("ODOO_TEAM_DB_PATTERN", raising=False)
        monkeypatch.setenv("ODOO_DB", "linkedtrust_crm")
        assert _team_crm_db({"org_id": org_id}) is None
        assert _crm_conf({"org_id": org_id})["ODOO_DB"] == "linkedtrust_crm"

    def test_pattern_gives_each_team_its_own_database(self, team_org, monkeypatch):
        org_id, slug = team_org
        monkeypatch.setenv("ODOO_TEAM_DB_PATTERN", "crm-{slug}")
        monkeypatch.setenv("ODOO_DB", "linkedtrust_crm")
        assert _crm_conf({"org_id": org_id})["ODOO_DB"] == f"crm-{slug}"

    def test_credentials_and_url_are_untouched(self, team_org, monkeypatch):
        """Only the database name is per-team; nothing else is invented."""
        org_id, slug = team_org
        monkeypatch.setenv("ODOO_TEAM_DB_PATTERN", "crm-{slug}")
        monkeypatch.setenv("ODOO_URL", "https://crm.example")
        monkeypatch.setenv("ODOO_USER", "svc")
        monkeypatch.setenv("ODOO_API_KEY", "secret")
        conf = _crm_conf({"org_id": org_id})
        assert conf["ODOO_URL"] == "https://crm.example"
        assert conf["ODOO_USER"] == "svc"
        assert conf["ODOO_API_KEY"] == "secret"
        assert conf["ODOO_DB"] == f"crm-{slug}"

    def test_no_org_in_context_is_left_alone(self, monkeypatch):
        monkeypatch.setenv("ODOO_TEAM_DB_PATTERN", "crm-{slug}")
        monkeypatch.setenv("ODOO_DB", "linkedtrust_crm")
        assert _team_crm_db({}) is None
        assert _crm_conf({})["ODOO_DB"] == "linkedtrust_crm"

    def test_subprocess_path_gets_the_same_database(self, team_org, monkeypatch):
        """The CLI tools take their env from _routed_env, not _crm_conf, so it
        has to carry the override too — as an overlay of that one variable."""
        org_id, slug = team_org
        monkeypatch.setenv("ODOO_TEAM_DB_PATTERN", "crm-{slug}")
        env, err = _routed_env({"org_id": org_id}, "crm")
        assert err is None
        assert env == {"ODOO_DB": f"crm-{slug}"}

    def test_non_crm_tools_are_unaffected(self, team_org, monkeypatch):
        org_id, _ = team_org
        monkeypatch.setenv("ODOO_TEAM_DB_PATTERN", "crm-{slug}")
        env, err = _routed_env({"org_id": org_id}, "tasks")
        assert err is None and env is None


# --- Taiga: a team can only ever touch its own board -------------------------
# Every Taiga tool takes the project as an argument the MODEL writes, and one
# token reaches every team's board, so without this the only thing keeping a
# team's agent off another team's board is prompt wording.

from src.tools.cli_read_tools import _team_project, taiga_list_impl


class TestTeamTaigaProject:
    def test_unset_pattern_honours_the_models_argument(self, team_org, monkeypatch):
        org_id, _ = team_org
        monkeypatch.delenv("TAIGA_TEAM_PROJECT_PATTERN", raising=False)
        assert _team_project({"org_id": org_id}) is None

    def test_pattern_gives_the_acting_team_its_own_board(self, team_org, monkeypatch):
        org_id, slug = team_org
        monkeypatch.setenv("TAIGA_TEAM_PROJECT_PATTERN", "{slug}")
        assert _team_project({"org_id": org_id}) == slug

    def test_no_org_in_context_is_left_alone(self, monkeypatch):
        monkeypatch.setenv("TAIGA_TEAM_PROJECT_PATTERN", "{slug}")
        assert _team_project({}) is None

    def test_asking_for_another_teams_board_is_overridden(self, team_org, monkeypatch):
        """The guard: naming someone else's project simply cannot do anything."""
        org_id, slug = team_org
        monkeypatch.setenv("TAIGA_TEAM_PROJECT_PATTERN", "{slug}")
        monkeypatch.setenv("ENV_CREDENTIALS_SHARED", "1")
        seen = {}

        def fake_run_cli(argv, **kw):
            seen["argv"] = argv
            return "ok"

        monkeypatch.setattr("src.tools.cli_read_tools.run_cli", fake_run_cli)
        taiga_list_impl({"project": "some-other-team"}, {"org_id": org_id})
        assert seen["argv"] == ["mcp-taiga", "list", slug]
        assert "some-other-team" not in seen["argv"]
