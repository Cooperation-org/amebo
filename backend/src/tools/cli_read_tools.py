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


def run_cli(argv: List[str], timeout: int = DEFAULT_TIMEOUT_S) -> str:
    """
    Run a CLI tool as a subprocess and return its stdout.

    ``argv`` is a fully-split argument list (``["abra", "search", "grants"]``)
    so there is no shell and no injection surface. Callers build argv from
    discrete fields — they MUST NOT pre-join a string and split it, because
    that would re-introduce word-splitting on user input.

    On non-zero exit the trimmed stderr is appended so the model can see why a
    lookup failed. A missing executable returns an explicit message rather than
    raising, so the agentic loop degrades gracefully.
    """
    if not argv or not argv[0]:
        return "Error: no command to run."
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
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
    model = (tool_input.get("model") or "contacts").strip()
    # Whitelist the searchable models so a bad value can't become an arbitrary
    # odoo-cli subcommand. Both are read-only searches.
    if model not in ("contacts", "leads"):
        return "Error: model must be 'contacts' or 'leads'."
    # odoo-cli search contacts "<query>"  (per next-steps.md #2)
    return run_cli(["odoo-cli", "search", model, query])


ODOO_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Text to search for (name, company, email fragment).",
        },
        "model": {
            "type": "string",
            "description": "What to search: 'contacts' (default) or 'leads'.",
            "enum": ["contacts", "leads"],
        },
    },
    "required": ["query"],
}


# ---------------------------------------------------------------------------
# crm_read_latest_email — read latest forwarded email / chatter for a sender
# ---------------------------------------------------------------------------


def crm_read_latest_email_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    Read the latest forwarded email / chatter message logged in the CRM for a
    given sender (email address or contact). Read only.

    TODO(odoo-cli): the exact subcommand that returns a contact's most recent
    chatter/email is not confirmed in next-steps.md. We use the documented
    read subcommand ``odoo-cli show contact <id-or-email>`` which surfaces the
    contact record including recent messages. If a dedicated
    ``odoo-cli messages <sender>`` (or similar) exists, switch to it here. This
    is a READ, so an unknown/empty result is the worst case — never a write.
    """
    sender = _require(tool_input, "sender")
    if sender is None:
        return "Error: sender is required (email address or contact identifier)."
    # Read-only: show the contact record, which includes recent chatter/emails.
    return run_cli(["odoo-cli", "show", "contact", sender])


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
    """List tasks in Taiga via mcp-taiga. Read only."""
    # mcp-taiga list [project]   (per next-steps.md #2)
    argv = ["mcp-taiga", "list"]
    project = tool_input.get("project")
    if isinstance(project, str) and project.strip():
        argv.append(project.strip())
    return run_cli(argv)


TAIGA_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "project": {
            "type": "string",
            "description": "Optional Taiga project slug/name to scope the listing.",
        },
    },
    "required": [],
}
