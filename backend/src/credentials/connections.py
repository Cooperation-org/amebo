"""
ConnectionResolver — org.yaml manifest + org_credentials -> live ToolConnection.

See arch §5 / §2.1. The source of an org's tool config is the **org.yaml
manifest at its context-repo root** (NOT the deprecated org_tools table). This
module turns (org_id, tool_key) into a ToolConnection: base_url + non-secret
config from the manifest, joined with the decrypted secret from org_credentials
via the manifest entry's `cred:` label (through the existing CredentialResolver
seam, arch §4.3 hardening path).

Failures are typed + human-readable (never a silent fallback to stale config, I1):
  - ToolNotConfigured(org_id, tool_key) — the org has no such tool connected.
    Identical shape for a missing CRM, Discord, or email: absent capabilities
    are a DATA condition, never a code branch.
  - ManifestInvalid(org_id, detail) — the manifest is missing/unparseable/bad.

Nothing in the live tool paths reads this yet (tools switch family-by-family in
WP5–8); it is additive and does not change running behavior.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import yaml

from src.db.connection import DatabaseConnection
from src.credentials.resolver import CredentialResolver, CredentialMissing

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "org.yaml"
MANIFEST_TTL_S = 60           # honor "other people edit this file" (arch §2.1)
SUPPORTED_SCHEMA = 1


def env_credentials_shared() -> bool:
    """Whether this DEPLOYMENT declares its process-env credentials shared by
    ALL orgs (env ENV_CREDENTIALS_SHARED, operator-set).

    Two deployment shapes exist (Golda, 2026-07-16):
      - the team instance: orgs are separate tenants; env credentials belong to
        the one legacy org (LEGACY_ENV_ORG_ID pin), everyone else fails closed
        on a missing manifest — the cross-tenant-leak guard stands (arch §5 I1);
      - a cohort VM (earnkit): every team org intentionally runs on the VM's
        shared keys. There is no tenant boundary to leak across, so the env
        fallback is open to all orgs and provisioning needs no legacy pin.
    """
    return os.getenv("ENV_CREDENTIALS_SHARED", "").strip().lower() in ("1", "true", "yes")


class ToolNotConfigured(LookupError):
    """The org has no connection for this tool_key (or its secret is missing).
    This is also how an absent capability (email/Discord/…) presents — uniformly."""

    def __init__(self, org_id: int, tool_key: str, detail: str = ""):
        msg = f"org {org_id} has no '{tool_key}' connected"
        if detail:
            msg += f" ({detail})"
        super().__init__(msg)
        self.org_id = org_id
        self.tool_key = tool_key


class ManifestInvalid(RuntimeError):
    """The org's org.yaml is missing, unparseable, or fails validation."""

    def __init__(self, org_id: int, detail: str):
        super().__init__(f"org {org_id} manifest error: {detail}")
        self.org_id = org_id
        self.detail = detail


@dataclass(frozen=True)
class ToolConnection:
    org_id: int
    tool_key: str
    kind: str                      # adapter/env-template selector from the manifest
    base_url: Optional[str]
    credential: Optional[Dict[str, Any]]   # decrypted secret payload (env-shaped)
    config: Dict[str, Any]         # manifest entry minus kind/base_url/cred

    def as_subprocess_env(self) -> Dict[str, str]:
        """Build the exact env each CLI expects, from a single per-`kind`
        template: non-secret vars from the manifest + the (already env-keyed)
        secret payload. os.environ is never mutated (I5); callers pass this as
        run_cli(env=...)."""
        return _env_for(self.kind, self.base_url, self.config, self.credential)


# --- per-kind env templates --------------------------------------------------
# Non-secret vars are derived from the manifest here; the SECRET vars come from
# the credential payload (get_payload already returns them env-var-keyed, e.g.
# {"TAIGA_USERNAME":…}). Verified against each CLI's docs during WP5–8 wiring.

def _env_for(kind: str, base_url: Optional[str], config: Dict[str, Any],
             credential: Optional[Dict[str, Any]]) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if kind == "odoo_cli":
        if base_url:
            env["ODOO_URL"] = base_url
        if config.get("db"):
            env["ODOO_DB"] = str(config["db"])
    elif kind == "mcp_taiga":
        if base_url:
            env["TAIGA_URL"] = base_url
    elif kind == "abra":
        # abra's scope is a CLI flag (config['scope']), not env; only the DB URL
        # is env, and it may be carried on the credential or the manifest config.
        if config.get("database_url"):
            env["ABRA_DATABASE_URL"] = str(config["database_url"])
    # slack_app / git_repo: no non-secret env vars (token/path handled elsewhere).

    for k, v in (credential or {}).items():
        if not k.startswith("_") and isinstance(v, (str, int, float)):
            env[k] = str(v)
    return env


# --- manifest read (pull + parse + validate, TTL) ----------------------------

_manifest_cache: Dict[str, tuple] = {}   # {context_repo: (loaded_at, parsed)}


def _org_context_repo(org_id: int) -> Optional[str]:
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT context_repo FROM organizations WHERE org_id = %s", (org_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else None
    finally:
        DatabaseConnection.return_connection(conn)


def _load_manifest(context_repo: str, org_id: int) -> Dict[str, Any]:
    """Read + parse + validate the org.yaml at the context repo root, cached for
    MANIFEST_TTL_S. (Git-pull-before-read is a deploy-time discipline — see the
    module note; auto-pulling a shared repo on every resolve is left to the
    provisioning/deploy layer to avoid disrupting concurrent human edits.)"""
    now = time.monotonic()
    cached = _manifest_cache.get(context_repo)
    if cached and (now - cached[0]) < MANIFEST_TTL_S:
        return cached[1]

    path = os.path.join(context_repo, MANIFEST_FILENAME)
    try:
        with open(path) as fh:
            parsed = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        raise ManifestInvalid(org_id, f"no {MANIFEST_FILENAME} at {context_repo}")
    except yaml.YAMLError as exc:
        raise ManifestInvalid(org_id, f"unparseable {MANIFEST_FILENAME}: {exc}")

    if not isinstance(parsed, dict):
        raise ManifestInvalid(org_id, "manifest is not a mapping")
    schema = parsed.get("schema")
    if schema != SUPPORTED_SCHEMA:
        raise ManifestInvalid(org_id, f"unsupported schema {schema!r} (want {SUPPORTED_SCHEMA})")
    if not isinstance(parsed.get("tools"), dict):
        raise ManifestInvalid(org_id, "missing or invalid 'tools' mapping")

    _manifest_cache[context_repo] = (now, parsed)
    return parsed


def invalidate_cache(context_repo: Optional[str] = None) -> None:
    if context_repo is None:
        _manifest_cache.clear()
    else:
        _manifest_cache.pop(context_repo, None)


# --- the resolve entrypoint ---------------------------------------------------

def resolve(org_id: int, tool_key: str) -> ToolConnection:
    context_repo = _org_context_repo(org_id)
    if not context_repo:
        raise ToolNotConfigured(org_id, tool_key, "org has no context repo")

    manifest = _load_manifest(context_repo, org_id)
    entry = manifest.get("tools", {}).get(tool_key)
    if not isinstance(entry, dict):
        raise ToolNotConfigured(org_id, tool_key)

    kind = entry.get("kind")
    if not kind:
        raise ManifestInvalid(org_id, f"tool '{tool_key}' has no 'kind'")

    base_url = entry.get("base_url")
    cred_label = entry.get("cred")
    config = {k: v for k, v in entry.items() if k not in ("kind", "base_url", "cred")}

    credential: Optional[Dict[str, Any]] = None
    if cred_label:
        try:
            credential = CredentialResolver(org_id, kind, cred_label).get_payload()
        except CredentialMissing:
            raise ToolNotConfigured(
                org_id, tool_key,
                f"manifest references cred '{cred_label}' (kind {kind}) but no such secret is stored",
            )

    return ToolConnection(
        org_id=org_id, tool_key=tool_key, kind=kind,
        base_url=base_url, credential=credential, config=config,
    )
