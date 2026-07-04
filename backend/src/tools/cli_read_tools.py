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
    return run_cli(["odoo-cli", "contact-search", query])


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
    return run_cli(["odoo-cli", "comms", sender])


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

_ODOO_URL = _os.getenv("ODOO_URL", "http://localhost:8069")
_ODOO_DB = _os.getenv("ODOO_DB", "linkedtrust_crm")


def _odoo():
    """Authenticate to Odoo in-process; return (models, db, uid, pwd). Raises a
    clear RuntimeError if not configured / auth fails. Read-only callers only."""
    user = _os.getenv("ODOO_USER", "")
    pwd = _os.getenv("ODOO_API_KEY", "") or _os.getenv("ODOO_PASSWORD", "")
    if not user or not pwd:
        raise RuntimeError("CRM not configured (set ODOO_USER + ODOO_API_KEY).")
    uid = _xmlrpc.ServerProxy(f"{_ODOO_URL}/xmlrpc/2/common").authenticate(
        _ODOO_DB, user, pwd, {})
    if not uid:
        raise RuntimeError("CRM authentication failed.")
    return _xmlrpc.ServerProxy(f"{_ODOO_URL}/xmlrpc/2/object"), _ODOO_DB, uid, pwd


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
        m, db, uid, pwd = _odoo()
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
        m, db, uid, pwd = _odoo()
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
        m, db, uid, pwd = _odoo()
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


def load_skill_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Load a skill's full instructions by name. Read only. Valid names are the
    ones listed in the 'Available skills' catalog in your system prompt."""
    from pathlib import Path
    name = (tool_input.get("name") or "").strip()
    if not name:
        return "Error: name is required."
    skills_dir = Path(__file__).resolve().parent.parent.parent / "prompts" / "skills"
    path = skills_dir / f"{name}.md"
    if not path.exists():
        avail = (", ".join(sorted(p.stem for p in skills_dir.glob("*.md")
                                  if not p.stem.startswith("_")))
                 if skills_dir.exists() else "")
        return f"No skill named '{name}'. Available: {avail or '(none)'}"
    content = path.read_text()
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    return content or "(skill has no body)"


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
    if mode not in ("search", "about"):
        return "Error: mode must be 'search' or 'about'."
    # abra search "<query>"  /  abra about <name>  (per CLAUDE.md + next-steps.md)
    return run_cli(["abra", mode, query])


ABRA_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search text, or the name to look up when mode='about'.",
        },
        "mode": {
            "type": "string",
            "description": "'search' for full-text (default) or 'about' for a name.",
            "enum": ["search", "about"],
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
    return run_cli(["mcp-taiga", "list", project])


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
