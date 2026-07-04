"""
Org provisioning (WP17) — take an org from nothing to working, generically, with
NO code change (arch §11.5, UC-9). One call wires the amebo-owned pointers:

  - organizations row (slug, name, aliases, context_repo pointer)
  - attach to an instance (instance_orgs)
  - members (org_members) + their tool accounts (member_tool_accounts)

Everything else about the org — its actual tool config — lives in its context
repo's org.yaml (arch §5); its secrets live in org_credentials. Those are seeded
separately (they carry real credentials); this service wires the DB pointers.

Idempotent. `dry_run=True` returns the plan without writing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from psycopg2 import extras
from src.db.connection import DatabaseConnection
from src.db.repositories.instance_repo import InstanceRepo
from src.db.repositories.org_member_repo import OrgMemberRepo
from src.db.repositories.member_tool_account_repo import MemberToolAccountRepo

logger = logging.getLogger(__name__)


def _upsert_org(slug: str, name: str, aliases: List[str],
                context_repo: Optional[str]) -> int:
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO organizations (org_name, org_slug, aliases, context_repo)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (org_slug) DO UPDATE
                    SET org_name = EXCLUDED.org_name,
                        aliases = EXCLUDED.aliases,
                        context_repo = COALESCE(EXCLUDED.context_repo, organizations.context_repo)
                RETURNING org_id
                """,
                (name, slug, extras.Json(list(aliases or [])), context_repo),
            )
            org_id = cur.fetchone()[0]
            conn.commit()
            return org_id
    finally:
        DatabaseConnection.return_connection(conn)


def provision_org(
    slug: str,
    name: str,
    *,
    context_repo: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    instance_id: Optional[int] = None,
    members: Optional[List[Dict[str, Any]]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Provision an org and its memberships.

    members: [{user_id, role?, tool_accounts?: [{tool_key, external_id, username?}]}]
    Returns a summary of what was (or would be) done.
    """
    slug = (slug or "").strip()
    name = (name or "").strip()
    if not slug or not name:
        raise ValueError("slug and name are required")
    members = members or []
    aliases = aliases or []

    plan = {
        "org": {"slug": slug, "name": name, "aliases": aliases, "context_repo": context_repo},
        "instance_id": instance_id,
        "members": [
            {"user_id": m.get("user_id"), "role": m.get("role", "member"),
             "tool_accounts": m.get("tool_accounts", [])}
            for m in members
        ],
        "dry_run": dry_run,
    }
    if dry_run:
        return {"planned": plan}

    org_id = _upsert_org(slug, name, aliases, context_repo)

    if instance_id is not None:
        InstanceRepo().add_org(instance_id, org_id)

    member_repo = OrgMemberRepo()
    account_repo = MemberToolAccountRepo()
    wired_members = []
    for m in members:
        uid = m.get("user_id")
        if uid is None:
            continue
        member_repo.add_member(org_id, uid, role=m.get("role", "member"))
        for acct in m.get("tool_accounts", []):
            if acct.get("tool_key") and acct.get("external_id"):
                account_repo.link(org_id, uid, acct["tool_key"], str(acct["external_id"]),
                                  external_username=acct.get("username"))
        wired_members.append(uid)

    return {
        "org_id": org_id,
        "slug": slug,
        "instance_attached": instance_id,
        "members_wired": wired_members,
    }
