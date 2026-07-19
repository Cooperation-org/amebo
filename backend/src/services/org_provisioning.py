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
import os
from typing import Any, Dict, List, Optional, Tuple

from psycopg2 import extras
from src.db.connection import DatabaseConnection
from src.db.repositories.instance_repo import InstanceRepo
from src.db.repositories.org_member_repo import OrgMemberRepo
from src.db.repositories.member_tool_account_repo import MemberToolAccountRepo

logger = logging.getLogger(__name__)


def _require_legacy_pin() -> None:
    """Hard precondition (Fable review): the env-credential fallback must be
    SCOPED to the designated legacy org before another org exists, or a new
    org's missing manifest could break the legacy org / risk misroute. Refuse
    to provision until LEGACY_ENV_ORG_ID pins the legacy org (unset it only at
    the WP17 cutover, when everyone fails closed)."""
    from src.credentials.connections import env_credentials_shared
    if env_credentials_shared():
        # Cohort-VM shape: env credentials are declared shared by every org,
        # so there is no legacy org to pin and nothing to misroute.
        return
    if not os.getenv("LEGACY_ENV_ORG_ID"):
        raise RuntimeError(
            "LEGACY_ENV_ORG_ID is not set. Pin the legacy org (the one still "
            "using env credentials, e.g. linkedtrust's org_id) before provisioning "
            "additional orgs, so the credential fallback is scoped and new orgs "
            "fail closed on a missing manifest (arch §5, I1).")


def _get_org(slug: str) -> Optional[Dict[str, Any]]:
    """The org row for a slug ({org_id, org_name, aliases}) or None."""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT org_id, org_name, aliases FROM organizations WHERE org_slug = %s",
                (slug,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        DatabaseConnection.return_connection(conn)


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
                (name, slug, list(aliases or []), context_repo),
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

    _require_legacy_pin()
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


# ---------------------------------------------------------------------------
# S2S provisioning (POST /api/orgs/provision) — sibling services (GovKit
# accept, earnkit add-team) send members identified by email and/or lt_sub
# (the LinkedTrust OIDC subject), not by user_id. This wrapper upserts
# platform_users rows from those identifiers, then reuses provision_org()
# for the canonical org/membership/tool-account wiring. Idempotent.
# ---------------------------------------------------------------------------


def _upsert_platform_user(
    org_id: int,
    *,
    email: Optional[str] = None,
    lt_sub: Optional[str] = None,
    display_name: Optional[str] = None,
    role: str = "member",
) -> Tuple[int, bool]:
    """Find-or-create a platform_users row for an externally-identified person.

    Match order (same resolution the OIDC callback uses, auth.py): the stable
    LinkedTrust subject first (auth_provider='linkedtrust', auth_provider_id),
    then email. Existing rows are only FILLED IN (link lt_sub if the row has no
    provider yet, set full_name if empty) — never overwritten, and their org_id
    / platform role are left alone (org role lives in org_members).

    Returns (user_id, created).
    """
    email = (email or "").strip() or None
    lt_sub = (lt_sub or "").strip() or None
    if not email and not lt_sub:
        raise ValueError("member needs at least one of email, lt_sub")

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            user = None
            if lt_sub:
                cur.execute(
                    "SELECT user_id, full_name, auth_provider, auth_provider_id "
                    "FROM platform_users "
                    "WHERE auth_provider = 'linkedtrust' AND auth_provider_id = %s",
                    (lt_sub,),
                )
                user = cur.fetchone()
            if user is None and email:
                cur.execute(
                    "SELECT user_id, full_name, auth_provider, auth_provider_id "
                    "FROM platform_users WHERE email = %s",
                    (email,),
                )
                user = cur.fetchone()

            if user is None:
                # platform_users.email is NOT NULL/UNIQUE; a sub-only member
                # gets the same placeholder shape the OIDC callback mints.
                effective_email = email or f"lt-{lt_sub}@users.amebo.local"
                cur.execute(
                    """
                    INSERT INTO platform_users
                        (org_id, email, full_name, role, is_active, email_verified,
                         auth_provider, auth_provider_id)
                    VALUES (%s, %s, %s, %s, true, false, %s, %s)
                    RETURNING user_id
                    """,
                    (org_id, effective_email, display_name, role,
                     "linkedtrust" if lt_sub else None, lt_sub),
                )
                user_id = cur.fetchone()["user_id"]
                conn.commit()
                return user_id, True

            # Existing person: fill-in-only updates, no overwrites.
            sets: List[str] = []
            params: List[Any] = []
            if lt_sub and not user["auth_provider"]:
                sets.append("auth_provider = 'linkedtrust'")
                sets.append("auth_provider_id = %s")
                params.append(lt_sub)
            if display_name and not user["full_name"]:
                sets.append("full_name = %s")
                params.append(display_name)
            if sets:
                sets.append("updated_at = NOW()")
                params.append(user["user_id"])
                cur.execute(
                    f"UPDATE platform_users SET {', '.join(sets)} WHERE user_id = %s",
                    params,
                )
                conn.commit()
            return user["user_id"], False
    finally:
        DatabaseConnection.return_connection(conn)


def provision_org_s2s(
    slug: str,
    *,
    name: Optional[str] = None,
    source: Optional[str] = None,
    members: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create/update an org + its members for a trusted sibling service.

    members: [{email?, lt_sub?, display_name?, role?, tool_accounts?}]
    (identified by email/lt_sub — user_ids are resolved here).

    `source` is provenance for the audit log only: org_members.source is
    CHECK-constrained to manual|linkedclaims (mig 020), so it is not persisted
    on the membership row.

    Returns {"org_id", "created", "members": [{"user_id", "created"}]}.
    Idempotent: re-running with the same body changes nothing and reports
    created=False throughout.
    """
    slug = (slug or "").strip()
    if not slug:
        raise ValueError("slug is required")
    _require_legacy_pin()  # fail fast, before any write
    members = members or []

    existing = _get_org(slug)
    created = existing is None
    if created:
        effective_name = (name or "").strip()
        if not effective_name:
            raise ValueError(
                f"org '{slug}' does not exist yet; 'name' is required to create it")
        aliases: List[str] = []
    else:
        effective_name = (name or "").strip() or existing["org_name"]
        aliases = list(existing["aliases"] or [])  # preserve — don't clobber

    logger.info("S2S provision: org=%s created=%s source=%s members=%d",
                slug, created, source, len(members))

    # The org row must exist before member rows (platform_users.org_id is
    # NOT NULL, retained for back-compat per mig 020).
    org_id = _upsert_org(slug, effective_name, aliases, None)

    member_results: List[Dict[str, Any]] = []
    service_members: List[Dict[str, Any]] = []
    for m in members:
        role = m.get("role") or "member"
        user_id, user_created = _upsert_platform_user(
            org_id,
            email=m.get("email"),
            lt_sub=m.get("lt_sub"),
            display_name=m.get("display_name"),
            role=role,
        )
        member_results.append({"user_id": user_id, "created": user_created})
        service_members.append({
            "user_id": user_id,
            "role": role,
            "tool_accounts": m.get("tool_accounts") or [],
        })

    # Canonical wiring path — org_members + member_tool_accounts.
    provision_org(slug, effective_name, aliases=aliases, members=service_members)

    return {"org_id": org_id, "created": created, "members": member_results}
