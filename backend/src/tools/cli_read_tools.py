"""
Read tools — Amebo's "eyes": ungated, safe, side-effect-free lookups that
shell out to the team's CLIs (odoo-cli, abra, mcp-taiga).

These are READ ONLY. They never write to the CRM, Taiga, or anywhere else, so
they are classified FREE in ``gated_actions`` and run without human approval.
The outbound/destructive counterparts (creating a task, posting to Slack) live
in ``gated_actuators.py`` and route through the draft-approval gate instead.

Subprocess discipline (matches next-steps.md #2 and registry._exec_cli_tool):

  * list args, never ``shell=True`` (no shell injection surface),
  * an explicit timeout on every call,
  * stdout captured and returned, stderr surfaced on non-zero exit,
  * a missing CLI fails safe with a clear message, never a guess.

Where a real CLI subcommand is not yet certain, the adapter is marked with a
TODO and uses the conservative subcommand we DO know; it never invents a
destructive call. (All tools here are read-only, so the worst case of an
unknown subcommand is an empty/erroring read, never a side effect.)
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Default timeout for a CLI read. Kept in step with registry._exec_cli_tool.
DEFAULT_TIMEOUT_S = 10


def run_cli(argv: List[str], timeout: int = DEFAULT_TIMEOUT_S,
            env: Optional[Dict[str, str]] = None) -> str:
    """
    Run a CLI tool as a subprocess and return its stdout.

    ``argv`` is a fully-split argument list (``["abra", "search", "grants"]``)
    so there is no shell and no injection surface. Callers build argv from
    discrete fields — they MUST NOT pre-join a string and split it, because
    that would re-introduce word-splitting on user input.

    ``env`` is an OVERLAY (from ToolConnection.as_subprocess_env(), arch §5):
    it is layered on top of the current process environment for THIS subprocess
    only — os.environ is never mutated (I5). This is how per-org credentials +
    endpoints reach a CLI without touching global state.

    On non-zero exit the trimmed stderr is appended so the model can see why a
    lookup failed. A missing executable returns an explicit message rather than
    raising, so the agentic loop degrades gracefully.
    """
    if not argv or not argv[0]:
        return "Error: no command to run."
    subprocess_env = None
    if env:
        subprocess_env = {**_os.environ, **env}
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            env=subprocess_env,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s: {argv[0]}"
    except FileNotFoundError:
        return f"Error: tool {argv[0]!r} not found in PATH."

    output = (result.stdout or "").strip()
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[:300]
        if output:
            return f"{output}\n[exit {result.returncode}: {stderr}]"
        return f"Error: {argv[0]} exited {result.returncode}: {stderr or '(no stderr)'}"
    return output if output else "(no output)"


def _require(tool_input: Dict[str, Any], key: str) -> Optional[str]:
    value = tool_input.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


# ---------------------------------------------------------------------------
# Per-org connection routing (arch §5). A tool resolves its org's connection
# from the org.yaml manifest via ToolConnection. If the org has no manifest
# entry yet (e.g. linkedtrust before its org.yaml is seeded), we fall back to
# the process env so existing single-org behavior is unchanged until the WP17
# cutover — "env paths keep working until cutover".
# ---------------------------------------------------------------------------
def _org_id_from_context(context: Any) -> Optional[int]:
    if not isinstance(context, dict):
        return None
    oc = context.get("org_context")
    oc_org = getattr(oc, "org_id", None)
    if oc_org is not None:
        return oc_org
    return context.get("org_id")


def _conn(context: Any, tool_key: str):
    """The acting org's ToolConnection for a tool from its manifest.

    Fallback to the process env (returning None) is allowed ONLY for the
    designated legacy org (env LEGACY_ENV_ORG_ID = linkedtrust until the WP17
    cutover seeds its manifest). For every other org, a missing/broken manifest
    RAISES — the process env holds the legacy org's credentials, so a silent
    fallback would route org B's calls through org A's accounts (cross-tenant
    leak; reads leak data exactly as badly as writes act). Same rule for reads
    and writes. At cutover, unset LEGACY_ENV_ORG_ID and everyone fails closed.
    """
    org_id = _org_id_from_context(context)
    if org_id is None:
        # No org in context at all: legacy direct paths (pre-OrgContext) only.
        return None
    legacy = _os.getenv("LEGACY_ENV_ORG_ID", "")
    is_legacy_org = legacy != "" and str(org_id) == legacy
    try:
        from src.credentials.connections import (
            resolve, ToolNotConfigured, ManifestInvalid,
        )
        return resolve(org_id, tool_key)
    except (ToolNotConfigured, ManifestInvalid):
        if is_legacy_org:
            return None
        raise
    except Exception:
        logger.exception("connection resolve failed org=%s tool=%s", org_id, tool_key)
        if is_legacy_org:
            return None
        raise


def _conn_env(context: Any, tool_key: str) -> Optional[Dict[str, str]]:
    """The org's subprocess env for a tool (None = fall back to process env).
    Raises ToolNotConfigured / ManifestInvalid for a non-legacy org with a
    missing/broken manifest — never misroutes to the legacy env creds."""
    c = _conn(context, tool_key)
    return c.as_subprocess_env() if c is not None else None


def _routed_env(context: Any, tool_key: str):
    """(env, error_message). error_message is a friendly string when the org has
    no such tool connected (or a broken manifest) — the tool returns it instead
    of running, so a non-legacy org NEVER misroutes to the legacy org's creds."""
    from src.credentials.connections import ToolNotConfigured, ManifestInvalid
    try:
        return _conn_env(context, tool_key), None
    except ToolNotConfigured:
        return None, f"This org doesn't have {tool_key} connected."
    except ManifestInvalid as exc:
        return None, f"This org's {tool_key} config is invalid: {exc}"


# ---------------------------------------------------------------------------
# odoo_search — search CRM contacts (READ)
# ---------------------------------------------------------------------------


def odoo_search_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Search the CRM (Odoo) for contacts matching a query. Read only."""
    query = _require(tool_input, "query")
    if query is None:
        return "Error: query is required."
    # Confirmed against the live CLI (`odoo-cli --help`, 2026-06-06): the read
    # search verb is `contact-search <query>` — searches contacts by name,
    # email, or catcode. odoo-cli exposes no separate "leads" search, so there
    # is no model to choose: a single read-only contact search.
    env, err = _routed_env(context, "crm")
    if err:
        return err
    return run_cli(["odoo-cli", "contact-search", query], env=env)


ODOO_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Text to search for (name, company, email fragment).",
        },
    },
    "required": ["query"],
}


# ---------------------------------------------------------------------------
# crm_read_latest_email — read latest forwarded email / chatter for a sender
# ---------------------------------------------------------------------------


def crm_read_latest_email_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    Read the message / note history logged in the CRM for a given sender
    (contact name or email). Read only.

    Confirmed against the live CLI (`odoo-cli --help`, 2026-06-06): the
    read verb is ``odoo-cli comms <name>`` — "Show full message/note history
    for a contact". This surfaces the recent chatter/emails on the contact.
    It resolves a contact by name; an email fragment may also match. This is a
    READ, so an unknown/empty result is the worst case — never a write.
    """
    sender = _require(tool_input, "sender")
    if sender is None:
        return "Error: sender is required (email address or contact identifier)."
    # Read-only: contact's full message/note history (recent chatter/emails).
    env, err = _routed_env(context, "crm")
    if err:
        return err
    return run_cli(["odoo-cli", "comms", sender], env=env)


CRM_READ_LATEST_EMAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "sender": {
            "type": "string",
            "description": (
                "Email address or contact identifier whose latest forwarded "
                "email / chatter you want to read."
            ),
        },
    },
    "required": ["sender"],
}


# ---------------------------------------------------------------------------
# In-process Odoo (CRM) read tools — the biz-dev gaps amebo asked for: a
# recent-activity feed, the lead pipeline, and contact browse. These talk to
# Odoo over XML-RPC in-process (no per-call odoo-cli subprocess cold-start, so
# much faster). READ ONLY. Config by instance via env (no hardcoded org values):
# ODOO_URL, ODOO_DB, ODOO_USER, ODOO_API_KEY (or ODOO_PASSWORD).
# ---------------------------------------------------------------------------

import os as _os
import re as _re
import xmlrpc.client as _xmlrpc

def _crm_conf(context: Any = None) -> Dict[str, str]:
    """Effective Odoo connection env for this org: the manifest ToolConnection
    (arch §5) if configured, else the process env — the transition fallback that
    keeps linkedtrust working until its org.yaml is seeded (WP17 cutover)."""
    env = _conn_env(context, "crm")
    if env:
        return env
    return {
        "ODOO_URL": _os.getenv("ODOO_URL", "http://localhost:8069"),
        "ODOO_DB": _os.getenv("ODOO_DB", "linkedtrust_crm"),
        "ODOO_USER": _os.getenv("ODOO_USER", ""),
        "ODOO_API_KEY": _os.getenv("ODOO_API_KEY", "") or _os.getenv("ODOO_PASSWORD", ""),
    }


def _odoo(context: Any = None):
    """Authenticate to the acting org's Odoo in-process; return (models, db, uid,
    pwd). Config comes from the org's connection (per-org), falling back to env.
    Raises a clear RuntimeError if not configured / auth fails. Read-only."""
    conf = _crm_conf(context)
    url = conf.get("ODOO_URL") or "http://localhost:8069"
    db = conf.get("ODOO_DB") or "linkedtrust_crm"
    user = conf.get("ODOO_USER", "")
    pwd = conf.get("ODOO_API_KEY", "") or conf.get("ODOO_PASSWORD", "")
    if not user or not pwd:
        raise RuntimeError("CRM not configured (set ODOO_USER + ODOO_API_KEY).")
    uid = _xmlrpc.ServerProxy(f"{url}/xmlrpc/2/common").authenticate(db, user, pwd, {})
    if not uid:
        raise RuntimeError("CRM authentication failed.")
    return _xmlrpc.ServerProxy(f"{url}/xmlrpc/2/object"), db, uid, pwd


def _clean(html: str) -> str:
    return _re.sub(r"<[^>]+>", "", html or "").replace("&nbsp;", " ").strip()


def crm_recent_activity_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Recent chatter (messages/emails) across the WHOLE CRM, newest first.
    Read only. This is the cross-contact activity feed — NOT scoped to one
    person — that answers 'what's been happening in the CRM lately'."""
    try:
        limit = int(tool_input.get("limit", 15))
    except (TypeError, ValueError):
        limit = 15
    limit = max(1, min(limit, 50))
    try:
        m, db, uid, pwd = _odoo(context)
        msgs = m.execute_kw(db, uid, pwd, "mail.message", "search_read",
            [[("model", "=", "res.partner"),
              ("message_type", "in", ["comment", "email"])]],
            {"fields": ["date", "record_name", "subject", "body", "email_from"],
             "order": "date desc", "limit": limit})
    except Exception as e:
        return f"Error reading CRM activity: {e}"
    if not msgs:
        return "No recent CRM chatter found."
    lines = [f"{len(msgs)} most recent CRM messages (newest first):"]
    for x in msgs:
        who = x.get("record_name") or x.get("email_from") or "?"
        what = (x.get("subject") or _clean(x.get("body")))[:120]
        lines.append(f"- {x['date']} | {who} | {what}")
    return "\n".join(lines)


CRM_RECENT_ACTIVITY_SCHEMA = {
    "type": "object",
    "properties": {
        "limit": {"type": "integer",
                  "description": "How many recent messages (default 15, max 50)."},
    },
}


def crm_list_leads_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """List CRM leads/opportunities (the pipeline), most-recently-updated first.
    Optional stage-name filter. Read only — for 'where does the pipeline stand'."""
    try:
        limit = int(tool_input.get("limit", 25))
    except (TypeError, ValueError):
        limit = 25
    limit = max(1, min(limit, 100))
    domain = [("active", "=", True)]
    stage = (tool_input.get("stage") or "").strip()
    if stage:
        domain.append(("stage_id.name", "ilike", stage))
    try:
        m, db, uid, pwd = _odoo(context)
        leads = m.execute_kw(db, uid, pwd, "crm.lead", "search_read",
            [domain],
            {"fields": ["name", "partner_name", "stage_id", "user_id",
                        "expected_revenue", "date_deadline", "write_date"],
             "order": "write_date desc", "limit": limit})
    except Exception as e:
        return f"Error reading CRM leads: {e}"
    if not leads:
        return "No leads found."
    lines = [f"{len(leads)} leads (most recently updated first):"]
    for l in leads:
        st = l["stage_id"][1] if l.get("stage_id") else "-"
        owner = l["user_id"][1] if l.get("user_id") else "unassigned"
        rev = l.get("expected_revenue") or 0
        lines.append(f"- {l.get('name', '(no name)')} | stage: {st} | "
                     f"owner: {owner} | ${rev:g} | updated {(l.get('write_date') or '')[:10]}")
    return "\n".join(lines)


CRM_LIST_LEADS_SCHEMA = {
    "type": "object",
    "properties": {
        "stage": {"type": "string",
                  "description": "Filter by pipeline stage name (e.g. 'qualified', 'proposal')."},
        "limit": {"type": "integer", "description": "Max leads (default 25, max 100)."},
    },
}


def crm_list_contacts_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Browse/list CRM contacts. Optional query (name/email/company/catcode);
    with no query, lists contacts most-recently-touched first. Read only — for
    'list our contacts' / browsing, not just a single lookup."""
    try:
        limit = int(tool_input.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))
    q = (tool_input.get("query") or "").strip()
    domain = [("id", ">", 4)]
    if q:
        domain = ["&", ("id", ">", 4), "|", "|", "|",
                  ("name", "ilike", q), ("email", "ilike", q),
                  ("company_name", "ilike", q), ("x_abra_catcode", "ilike", q)]
    try:
        m, db, uid, pwd = _odoo(context)
        rows = m.execute_kw(db, uid, pwd, "res.partner", "search_read",
            [domain],
            {"fields": ["name", "email", "company_name", "function"],
             "order": "write_date desc", "limit": limit})
    except Exception as e:
        return f"Error listing CRM contacts: {e}"
    if not rows:
        return "No contacts found."
    lines = [f"{len(rows)} contacts:"]
    for c in rows:
        bits = [c.get("name") or "(no name)"]
        if c.get("email"):
            bits.append(c["email"])
        if c.get("company_name"):
            bits.append(c["company_name"])
        lines.append("- " + " | ".join(bits))
    return "\n".join(lines)


CRM_LIST_CONTACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string",
                  "description": "Optional filter: name / email / company / catcode. Omit to list recent."},
        "limit": {"type": "integer", "description": "Max contacts (default 50, max 200)."},
    },
}


# ---------------------------------------------------------------------------
# load_skill — model-driven skill selection (Claude-Code-style progressive
# disclosure). The system prompt lists the skill catalog (name: description);
# the model calls this to pull the full instructions for the skill(s) it wants.
# Read only — just reads a markdown file under prompts/skills/.
# ---------------------------------------------------------------------------


from pathlib import Path as _Path


def _packaged_skills_dir() -> _Path:
    """Core/universal skills packaged with amebo (backend/prompts/skills)."""
    return _Path(__file__).resolve().parent.parent.parent / "prompts" / "skills"


def _org_skills_dir(context: Any) -> Optional[_Path]:
    """The acting org's skills overlay dir (arch §7): `<context repo>/skills`.
    Org-specific skills live in the org's context repo (decided 2026-07-04:
    durable text in repos, not abra). None if there's no org / no context repo."""
    org_id = _org_id_from_context(context)
    if org_id is None:
        return None
    try:
        from src.credentials.connections import _org_context_repo
        repo = _org_context_repo(org_id)
        if repo:
            return _Path(repo) / "skills"
    except Exception:
        logger.exception("org skills dir resolve failed")
    return None


def _skill_slug(name: str) -> str:
    s = _re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return s or "skill"


def _read_skill_body(path: _Path) -> str:
    content = path.read_text()
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return content.strip()


def load_skill_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Load a skill's full instructions by name. Read only. Checks the acting
    org's skills overlay first, then the packaged core catalog."""
    name = (tool_input.get("name") or "").strip()
    if not name:
        return "Error: name is required."
    slug = _skill_slug(name)
    # org overlay wins over a packaged skill of the same name
    for d in (_org_skills_dir(context), _packaged_skills_dir()):
        if d is None:
            continue
        for candidate in (d / f"{name}.md", d / f"{slug}.md"):
            if candidate.exists():
                return _read_skill_body(candidate) or "(skill has no body)"
    avail = _list_skill_names(context)
    return f"No skill named '{name}'. Available: {avail or '(none)'}"


def _list_skill_names(context: Any) -> str:
    names = set()
    for d in (_packaged_skills_dir(), _org_skills_dir(context)):
        if d and d.exists():
            names.update(p.stem for p in d.glob("*.md") if not p.stem.startswith("_"))
    return ", ".join(sorted(names))


def list_skills_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """List available skills (name — description — status) for the acting org:
    the packaged core catalog plus the org's own overlay. Read only."""
    import yaml as _yaml
    rows = []
    seen = set()
    # org overlay first so an org skill shadows a core one of the same name
    for src_label, d in (("org", _org_skills_dir(context)), ("core", _packaged_skills_dir())):
        if not d or not d.exists():
            continue
        for p in sorted(d.glob("*.md")):
            if p.stem.startswith("_") or p.stem in seen:
                continue
            seen.add(p.stem)
            desc, status = "", ""
            try:
                content = p.read_text()
                if content.startswith("---"):
                    fm = _yaml.safe_load(content.split("---", 2)[1]) or {}
                    desc = fm.get("description", "")
                    status = fm.get("status", "")
            except Exception:
                pass
            tag = f" [{status}]" if status else ""
            rows.append(f"  - {p.stem} ({src_label}){tag}: {desc}")
    return "Available skills:\n" + "\n".join(rows) if rows else "No skills available."


def file_skill_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """File a skill into the acting org's context repo, verbatim (arch §7, §9).

    Stores the person's words UNCHANGED as the body plus a clearly separated
    one-line summary in the frontmatter (I9 — never replace the original). The
    org is the RESOLVED org (so 'file this under raise the voices' from any
    channel lands in RTV's repo). Lightly gated: it is a write-class tool, so the
    trust gate already blocks an unknown (T0) user; the write itself is to the
    org's own knowledge, so no full draft gate."""
    name = (tool_input.get("name") or "").strip()
    content = tool_input.get("content") or ""
    status = (tool_input.get("status") or "idea").strip()
    summary = (tool_input.get("summary") or "").strip()
    if not name or not content.strip():
        return "Error: name and content are required."
    if status not in ("idea", "draft", "active"):
        return "Error: status must be idea | draft | active."
    skills_dir = _org_skills_dir(context)
    if skills_dir is None:
        return ("Error: I don't have an org to file this under. Say which org "
                "(e.g. 'file this under raise the voices').")
    if not summary:
        summary = content.strip().splitlines()[0][:100]
    slug = _skill_slug(name)
    try:
        skills_dir.mkdir(parents=True, exist_ok=True)
        # frontmatter (summary + status) then the VERBATIM body, separated.
        fm = (f"---\nname: {name}\ndescription: {summary}\nstatus: {status}\n"
              f"source: filed-by-member\n---\n\n")
        path = skills_dir / f"{slug}.md"
        path.write_text(fm + content.rstrip() + "\n")
    except OSError as exc:
        return f"Error: could not file skill: {exc}"
    return (f"Filed skill '{name}' ({status}) in this org's skills at {path}. "
            f"Summary: {summary}")


FILE_SKILL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short skill name."},
        "content": {"type": "string",
                    "description": "The skill instructions IN THE PERSON'S OWN WORDS — stored verbatim."},
        "summary": {"type": "string",
                    "description": "Optional one-line summary (separate from the verbatim body)."},
        "status": {"type": "string", "enum": ["idea", "draft", "active"],
                   "description": "idea | draft | active (default idea)."},
    },
    "required": ["name", "content"],
}

LIST_SKILLS_SCHEMA = {"type": "object", "properties": {}, "required": []}


LOAD_SKILL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string",
                 "description": "Skill name to load (from the Available skills catalog)."},
    },
    "required": ["name"],
}


# ---------------------------------------------------------------------------
# abra_search — knowledge-base search / about (READ)
# ---------------------------------------------------------------------------


def abra_search_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    Query the abra knowledge base. ``mode`` selects the read subcommand:
    'search' (full-text) or 'about' (everything known about a name). Read only.
    """
    query = _require(tool_input, "query")
    if query is None:
        return "Error: query is required."
    mode = (tool_input.get("mode") or "search").strip()
    if mode not in ("search", "about", "read"):
        return "Error: mode must be 'search', 'about', or 'read'."
    # abra search "<query>" / abra about <name> / abra read <name>
    from src.credentials.connections import ToolNotConfigured, ManifestInvalid
    try:
        conn = _conn(context, "knowledge")
    except ToolNotConfigured:
        return "This org doesn't have knowledge (abra) connected."
    except ManifestInvalid as exc:
        return f"This org's knowledge config is invalid: {exc}"
    env = conn.as_subprocess_env() if conn is not None else None
    argv = ["abra", mode, query]
    # Apply the org's abra scope from its manifest (arch §5, §7). Only 'about'
    # supports --scope; 'search' is full-text across the (per-org) abra DB, which
    # the env routing (ABRA_DATABASE_URL) already isolates.
    scope = conn.config.get("scope") if conn is not None else None
    if scope and mode == "about":
        argv = ["abra", "about", "--scope", str(scope), query]
    return run_cli(argv, env=env)


ABRA_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search text, or the name to look up when mode='about'/'read'.",
        },
        "mode": {
            "type": "string",
            "description": "'search' for full-text (default), 'about' for a "
                           "name's bindings, 'read' for a note's full content.",
            "enum": ["search", "about", "read"],
        },
    },
    "required": ["query"],
}


# ---------------------------------------------------------------------------
# taiga_list — list Taiga tasks (READ)
# ---------------------------------------------------------------------------


def taiga_list_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """List user stories in a Taiga project. Read only."""
    # Confirmed against the live CLI (`mcp-taiga list --help`, 2026-06-06):
    # `mcp-taiga list PROJECT` — PROJECT is a REQUIRED positional argument.
    # (Use the `mcp-taiga projects` command to discover valid project slugs.)
    project = _require(tool_input, "project")
    if project is None:
        return "Error: project is required (a Taiga project slug/name)."
    env, err = _routed_env(context, "tasks")
    if err:
        return err
    return run_cli(["mcp-taiga", "list", project], env=env)


TAIGA_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "project": {
            "type": "string",
            "description": "Taiga project slug/name to list (required).",
        },
    },
    "required": ["project"],
}
