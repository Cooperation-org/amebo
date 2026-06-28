"""
Direct-access provisioning for team-member SSO invites.

When an SSO invite is consumed (see ``api/routes/auth.py`` :func:`oidc_callback`),
this gives the person their OWN direct logins to the team tools — independent of
amebo:

  * **CRM (Odoo)** — a real *internal + sales* user, with their LinkedTrust
    ``oauth_uid`` set so stock ``auth_oauth`` links a "Sign in with LinkedTrust"
    login straight to this user (true SSO, no portal stub, no Odoo module).
  * **Marten (Taiga)** — a ``Back`` membership in every *active* project, keyed
    to their email so the Taiga LinkedTrust plugin attaches them on login.

Afterwards they sign in directly at crm.linkedtrust.us / taiga.linkedtrust.us;
amebo is only the trigger, never in the path.

SECURITY BOUNDARY (deliberate): the admin credentials used here come ONLY from
the process environment (``PROVISION_*`` in the gitignored ``.env``) and are read
ONLY in this module. They are intentionally NOT stored in ``org_credentials`` and
NOT reachable through ``CredentialResolver`` — so the LLM/agent/chat tool path has
no code path to them. Provisioning runs as a fixed, deterministic step in the SSO
callback; it is never an agent decision.

Everything here is idempotent (safe to re-run on every login) and best-effort:
failures are logged, never raised, so a tool outage can't block the amebo login.
"""

from __future__ import annotations

import logging
import os
import xmlrpc.client
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 20

# Odoo access for a real team member: internal user + salesperson.
_ODOO_GROUP_XMLIDS = ["base.group_user", "sales_team.group_sale_salesman"]
_ODOO_PROVIDER_NAME = "LinkedTrust"

# Taiga role granted in each active project (matches org_tools.default_role).
_TAIGA_ROLE = "Back"


# ---------------------------------------------------------------------------
# Odoo / CRM
# ---------------------------------------------------------------------------

def _odoo_cfg():
    return (
        os.getenv("PROVISION_ODOO_URL"),
        os.getenv("PROVISION_ODOO_DB"),
        os.getenv("PROVISION_ODOO_LOGIN"),
        os.getenv("PROVISION_ODOO_PASSWORD"),
    )


def provision_odoo(email: str, name: Optional[str], oauth_sub: str) -> dict:
    """Create/ensure an internal+sales Odoo user linked to the LinkedTrust sub.

    Setting ``oauth_provider_id`` + ``oauth_uid`` is what makes stock auth_oauth
    resolve the user's "Sign in with LinkedTrust" login to THIS account instead
    of minting a portal stub — i.e. real direct SSO into the CRM.
    """
    url, db, login, pw = _odoo_cfg()
    if not all([url, db, login, pw]):
        raise RuntimeError("PROVISION_ODOO_* not configured")

    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, login, pw, {})
    if not uid:
        raise RuntimeError("Odoo admin authentication failed")
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def call(model, method, *args, **kw):
        return models.execute_kw(db, uid, pw, model, method, list(args), kw)

    # Resolve group + provider ids by reference (don't hardcode res_ids).
    group_ids = []
    for xmlid in _ODOO_GROUP_XMLIDS:
        mod, nm = xmlid.split(".", 1)
        rec = call(
            "ir.model.data", "search_read",
            [["model", "=", "res.groups"], ["module", "=", mod], ["name", "=", nm]],
            fields=["res_id"], limit=1,
        )
        if rec:
            group_ids.append(rec[0]["res_id"])

    prov = call("auth.oauth.provider", "search", [["name", "=", _ODOO_PROVIDER_NAME]], limit=1)
    provider_id = prov[0] if prov else None

    link_vals = {}
    if provider_id:
        link_vals = {"oauth_provider_id": provider_id, "oauth_uid": str(oauth_sub)}

    # Match an existing user by login or email (also catches a prior portal stub).
    found = call("res.users", "search", [["login", "=", email]], limit=1) \
        or call("res.users", "search", [["email", "=", email]], limit=1)

    if found:
        # `found` is already an id list (e.g. [33]); pass it as the write ids,
        # not wrapped again.
        call("res.users", "write", found, {
            **link_vals,
            "active": True,
            "groups_id": [(4, gid) for gid in group_ids],  # add groups, keep existing
        })
        return {"tool": "odoo", "user_id": found[0], "created": False}

    vals = {
        "name": name or email,
        "login": email,
        "email": email,
        "groups_id": [(6, 0, group_ids)],
        **link_vals,
    }
    new_id = call("res.users", "create", vals)
    return {"tool": "odoo", "user_id": new_id, "created": True}


# ---------------------------------------------------------------------------
# Taiga / Marten
# ---------------------------------------------------------------------------

def _taiga_cfg():
    return (
        os.getenv("PROVISION_TAIGA_URL"),
        os.getenv("PROVISION_TAIGA_LOGIN"),
        os.getenv("PROVISION_TAIGA_PASSWORD"),
    )


def _taiga_token(url: str, login: str, pw: str) -> str:
    # Taiga tokens are short-lived, so re-auth on every provisioning run rather
    # than storing a token that goes stale.
    r = requests.post(
        f"{url}/api/v1/auth",
        json={"type": "normal", "username": login, "password": pw},
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["auth_token"]


def _taiga_active_projects(url: str, token: str) -> list:
    r = requests.get(
        f"{url}/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    return [p for p in r.json() if not p.get("blocked_code") and not p.get("is_archived")]


def _taiga_role_id(url: str, token: str, project_id: int, role_name: str) -> Optional[int]:
    r = requests.get(
        f"{url}/api/v1/roles?project={project_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    roles = r.json()
    for role in roles:
        if (role.get("name") or "").strip().lower() == role_name.lower():
            return role["id"]
    # Fall back to any computable role so the member still lands somewhere sane.
    return roles[0]["id"] if roles else None


def _taiga_member_emails(url: str, token: str, project_id: int) -> set:
    r = requests.get(
        f"{url}/api/v1/memberships?project={project_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    return {(m.get("email") or m.get("user_email") or "").lower() for m in r.json()}


def provision_taiga(email: str, name: Optional[str]) -> dict:
    """Add the member (role ``Back``) to every active Taiga project, by email."""
    url, login, pw = _taiga_cfg()
    if not all([url, login, pw]):
        raise RuntimeError("PROVISION_TAIGA_* not configured")

    token = _taiga_token(url, login, pw)
    projects = _taiga_active_projects(url, token)
    added, already, failed = [], [], []
    for p in projects:
        if email.lower() in _taiga_member_emails(url, token, p["id"]):
            already.append(p["slug"])
            continue
        role_id = _taiga_role_id(url, token, p["id"], _TAIGA_ROLE)
        if not role_id:
            failed.append((p["slug"], "no role"))
            continue
        resp = requests.post(
            f"{url}/api/v1/memberships",
            headers={"Authorization": f"Bearer {token}"},
            json={"project": p["id"], "role": role_id, "username": email},
            timeout=_HTTP_TIMEOUT,
        )
        # Taiga returns HTTP 500 when the post-create invitation *email* step
        # fails (its SMTP isn't configured) even though the membership WAS
        # created — so never trust the status code; verify against the live
        # membership list, the way mcp-taiga does.
        if email.lower() in _taiga_member_emails(url, token, p["id"]):
            added.append(p["slug"])
        else:
            failed.append((p["slug"], f"{resp.status_code}:{resp.text[:80]}"))
    return {"tool": "taiga", "added": added, "already_member": already, "failed": failed,
            "active_projects": len(projects)}


# ---------------------------------------------------------------------------
# Entry point — called from the SSO invite-consume flow only.
# ---------------------------------------------------------------------------

def provision_member(email: str, name: Optional[str], oauth_sub: str) -> dict:
    """Best-effort: give a freshly-admitted member direct CRM + Taiga access.

    Never raises — each tool is isolated so one failing can't block login or the
    other tool. Idempotent, so re-running on every login is safe.
    """
    result: dict = {}
    for fn, key in ((lambda: provision_odoo(email, name, oauth_sub), "odoo"),
                    (lambda: provision_taiga(email, name), "taiga")):
        try:
            result[key] = fn()
            logger.info("provision[%s] %s -> %s", key, email, result[key])
        except Exception as exc:  # noqa: BLE001 - best-effort, log and continue
            result[key] = {"error": f"{type(exc).__name__}: {exc}"}
            logger.error("provision[%s] FAILED for %s: %s", key, email, exc, exc_info=True)
    return result
