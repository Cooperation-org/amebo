"""
Project Money tools: money on tasks, budget lines, approvals, said in Slack.

Project Money is an Odoo addon (github.com/Cooperation-org/project-money). Its
JSON-RPC methods for an agent (docs/API.md there) record what a NAMED PERSON
said; the record names that person, never the agent, and Project Money itself
checks that the person may approve. So these tools never take the person from
the model: who said it comes from Slack (the conversation's user_id and
message_ts, set by the Slack handler), looked up to an email with users.info.

Money is a proposal until an allocator approves it, and anyone may propose, so
registering is not gated. Approving and marking paid are recorded only for the
person who wrote the Slack message that asked for it, with that message's link.

Config (env, the deployment's own Project Money): PROJECT_MONEY_URL,
PROJECT_MONEY_DB, PROJECT_MONEY_LOGIN, PROJECT_MONEY_API_KEY. Only the org the
environment belongs to may use it (same rule as the Slack token).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import requests

from src.tools.cli_read_tools import run_cli
from src.tools.slack_tools import (
    SLACK_USERS_INFO_ENDPOINT,
    SlackPostError,
    _bot_token,
    _conversation_from_context,
    _org_id_from_context,
)

logger = logging.getLogger(__name__)

ALLOC = "project.money.allocation"
LINE = "project.money.budget.line"


class ProjectMoneyError(RuntimeError):
    pass


# --- connection ----------------------------------------------------------------

def _config(context) -> Dict[str, str]:
    from src.credentials.connections import env_credentials_shared
    org_id = _org_id_from_context(context)
    legacy = os.getenv("LEGACY_ENV_ORG_ID", "")
    if not (env_credentials_shared() or org_id is None
            or (legacy != "" and str(org_id) == legacy)):
        raise ProjectMoneyError(
            "this org has no Project Money connected; the one in the environment "
            "belongs to a different org.")
    cfg = {k: os.getenv("PROJECT_MONEY_" + k.upper(), "") for k in ("url", "db", "login", "api_key")}
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise ProjectMoneyError("Project Money is not configured (missing %s)." % ", ".join(missing))
    cfg["url"] = cfg["url"].rstrip("/")
    return cfg


def _rpc(cfg, service, method, *args):
    resp = requests.post(
        cfg["url"] + "/jsonrpc",
        json={"jsonrpc": "2.0", "method": "call",
              "params": {"service": service, "method": method, "args": list(args)}},
        timeout=30,
    )
    body = resp.json()
    if body.get("error"):
        err = body["error"]
        msg = (err.get("data") or {}).get("message") or err.get("message")
        raise ProjectMoneyError(msg)
    return body.get("result")


def _call(cfg, model, method, args=None, kwargs=None):
    uid = _rpc(cfg, "common", "login", cfg["db"], cfg["login"], cfg["api_key"])
    if not uid:
        raise ProjectMoneyError("Project Money refused the agent login.")
    return _rpc(cfg, "object", "execute_kw", cfg["db"], uid, cfg["api_key"],
                model, method, args or [], kwargs or {})


def _project(cfg, project: str) -> Dict[str, Any]:
    """A project by id, task-board slug, or name."""
    project = (project or "").strip()
    if not project:
        raise ProjectMoneyError("project is required.")
    fields = ["id", "name", "tracker_project_slug", "money_currency_id"]
    if project.isdigit():
        domain = [["id", "=", int(project)]]
    else:
        domain = ["|", ["tracker_project_slug", "=", project], ["name", "ilike", project]]
    found = _call(cfg, "project.project", "search_read", [domain], {"fields": fields, "limit": 5})
    exact = [p for p in found if p["name"].lower() == project.lower()
             or p["tracker_project_slug"] == project]
    found = exact or found
    if len(found) != 1:
        names = ", ".join(p["name"] for p in found) or "none"
        raise ProjectMoneyError("%d projects match %r (%s)." % (len(found), project, names))
    return found[0]


def _money(n, cur):
    return ("$%s" % format(n, ",.0f")) if cur == "USD" else "%s %s" % (format(n, ",.2f"), cur)


# --- who said it: Slack, not the model -------------------------------------------

def _speaker(context) -> Dict[str, str]:
    """Email of the person whose Slack message this is, and that message's link."""
    conv = _conversation_from_context(context)
    uid, ts, channel = conv.get("user_id"), conv.get("message_ts"), conv.get("channel_id")
    if conv.get("channel_type") != "slack" or not (uid and ts and channel):
        raise ProjectMoneyError(
            "approving and marking paid are recorded from a person's own Slack "
            "message; there is none in this conversation.")
    token = _bot_token(context)
    info = requests.get(SLACK_USERS_INFO_ENDPOINT, params={"user": uid},
                        headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    email = ((info.get("user") or {}).get("profile") or {}).get("email")
    if not email:
        raise ProjectMoneyError("Slack does not share this person's email with the app "
                                "(users:read.email scope).")
    link = None
    try:
        pl = requests.get("https://slack.com/api/chat.getPermalink",
                          params={"channel": channel, "message_ts": ts},
                          headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
        link = pl.get("permalink")
    except Exception:
        logger.debug("permalink lookup failed", exc_info=True)
    return {"email": email, "link": link or "slack:%s/%s" % (channel, ts)}


# --- tools -------------------------------------------------------------------------

def _budget_text(cfg, project) -> str:
    lines = _call(cfg, LINE, "search_read", [[["project_id", "=", project["id"]]]],
                  {"fields": ["id", "section", "name", "amount", "approved_amount",
                              "paid_amount", "left_amount", "registered_amount",
                              "currency_id"]})
    if not lines:
        return "%s has no budget lines." % project["name"]
    out = ["Budget lines of %s, project id %d (id · line · agreed · approved · paid · left):"
           % (project["name"], project["id"])]
    for b in lines:
        cur = b["currency_id"][1] if b["currency_id"] else "USD"
        out.append("%d · %s%s · %s · %s · %s · %s" % (
            b["id"], (b["section"] + ": ") if b["section"] else "", b["name"],
            _money(b["amount"], cur), _money(b["approved_amount"], cur),
            _money(b["paid_amount"], cur), _money(b["left_amount"], cur)))
    return "\n".join(out)


def project_money_budget_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    try:
        cfg = _config(context)
        project = _project(cfg, tool_input.get("project"))
        text = _budget_text(cfg, project)
        allocs = _call(cfg, ALLOC, "search_read",
                       [[["project_id", "=", project["id"]], ["state", "in", ["proposed", "authorized"]]]],
                       {"fields": ["id", "amount", "currency_id", "state", "budget_line_id",
                                   "tracker_ref", "subject"], "limit": 50})
        if allocs:
            text += "\n\nNot paid yet (id · amount · state · line · task):"
            for a in allocs:
                cur = a["currency_id"][1] if a["currency_id"] else "USD"
                text += "\n%d · %s · %s · %s · #%s %s" % (
                    a["id"], _money(a["amount"], cur),
                    "approved" if a["state"] == "authorized" else "registered",
                    a["budget_line_id"][1] if a["budget_line_id"] else "no line",
                    a["tracker_ref"] or "?", a["subject"] or "")
        return text
    except (ProjectMoneyError, SlackPostError) as exc:
        return f"Error: {exc}"


def project_money_register_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Register money on a task, split across budget lines. Creates the task on
    the project's board first when asked (only when the owner is directing live)."""
    try:
        cfg = _config(context)
        project = _project(cfg, tool_input.get("project"))
        task = str(tool_input.get("task") or "").strip().lstrip("#")
        new_task = (tool_input.get("new_task_subject") or "").strip()
        made = ""
        if not task and new_task:
            if not context.get("auto_execute"):
                return ("Error: creating a task needs approval here; draft it with "
                        "taiga_create_task, then register the money on its number.")
            slug = project["tracker_project_slug"]
            if not slug:
                return "Error: %s has no task board." % project["name"]
            due = (tool_input.get("due_date") or "").strip()
            argv = ["mcp-taiga", "create", slug, new_task]
            if due:
                argv += ["--due", due]
            out = run_cli(argv)
            if "Created #" not in out:
                return "Error: the task was not created: %s" % out.strip()
            task = out.split("Created #", 1)[1].split(":", 1)[0].strip()
            made = "Created task #%s %s on %s. " % (task, new_task, slug)
        if not task:
            return "Error: task (its number on the board) or new_task_subject is required."
        parts = tool_input.get("lines") or []
        if not parts and tool_input.get("amount"):
            parts = [{"amount": tool_input["amount"], "budget_line": tool_input.get("budget_line")}]
        if not parts:
            return "Error: lines (each an amount and a budget line) are required."
        try:
            said = _speaker(context)
        except ProjectMoneyError:
            said = None
        ids: List[int] = []
        for part in parts:
            kwargs: Dict[str, Any] = {"currency": tool_input.get("currency") or "USD"}
            if part.get("budget_line") not in (None, ""):
                kwargs["budget_line"] = part["budget_line"]
            if said:
                kwargs["link"] = said["link"]
                kwargs["said_by_email"] = said["email"]
            try:
                new_id = _call(cfg, ALLOC, "api_register",
                               [project["id"], float(part["amount"]), [task]], kwargs)
            except ProjectMoneyError as exc:
                if said and "No single Jade user" in str(exc):
                    # The speaker is not a user of this Project Money: record it as
                    # the agent, with the Slack message as the evidence.
                    kwargs.pop("said_by_email")
                    new_id = _call(cfg, ALLOC, "api_register",
                                   [project["id"], float(part["amount"]), [task]], kwargs)
                else:
                    raise
            ids.append(new_id)
        return (made + "Registered %d amount(s) on task #%s in %s: ids %s. Not money until "
                "an allocator approves.\n\n%s") % (
            len(ids), task, project["name"], ", ".join(map(str, ids)), _budget_text(cfg, project))
    except (ProjectMoneyError, SlackPostError) as exc:
        return f"Error: {exc}"


def _as_speaker(method: str, tool_input, context, extra=None) -> str:
    try:
        cfg = _config(context)
        ids = [int(i) for i in (tool_input.get("ids") or [])]
        if not ids:
            return "Error: ids (the registered amounts) are required."
        said = _speaker(context)
        kwargs = {"said_by_email": said["email"]}
        if method == "api_approve":
            kwargs["link"] = said["link"]
        else:
            kwargs["evidence_url"] = tool_input.get("evidence_url") or said["link"]
            for k in ("paid_on", "how"):
                if tool_input.get(k):
                    kwargs[k] = tool_input[k]
        _call(cfg, ALLOC, method, [ids], kwargs)
        rows = _call(cfg, ALLOC, "read", [ids], {"fields": ["project_id"]})
        project = {"id": rows[0]["project_id"][0], "name": rows[0]["project_id"][1]}
        verb = "Approved" if method == "api_approve" else "Marked paid"
        return "%s %s as %s (%s).\n\n%s" % (verb, ", ".join(map(str, ids)), said["email"],
                                           said["link"], _budget_text(cfg, project))
    except (ProjectMoneyError, SlackPostError) as exc:
        return f"Error: {exc}"


def project_money_approve_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    return _as_speaker("api_approve", tool_input, context)


def project_money_mark_paid_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    return _as_speaker("api_mark_paid", tool_input, context)


PROJECT_SCHEMA = {"type": "string", "description": "Project name, id, or its task-board slug, e.g. 'Civicus / Raise the Voices'."}

PROJECT_MONEY_BUDGET_SCHEMA = {
    "type": "object",
    "properties": {"project": PROJECT_SCHEMA},
    "required": ["project"],
}

PROJECT_MONEY_REGISTER_SCHEMA = {
    "type": "object",
    "properties": {
        "project": PROJECT_SCHEMA,
        "task": {"type": "string", "description": "The task's number on the project's board, e.g. '1'."},
        "new_task_subject": {"type": "string", "description": "Create this task on the project's board first, when no task fits."},
        "due_date": {"type": "string", "description": "Due date for a new task, YYYY-MM-DD."},
        "lines": {
            "type": "array",
            "description": "One entry per budget line the request draws on.",
            "items": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "budget_line": {"type": "string", "description": "Budget line id or its name as the budget words it."},
                },
                "required": ["amount"],
            },
        },
        "currency": {"type": "string", "description": "Default USD."},
    },
    "required": ["project"],
}

PROJECT_MONEY_IDS_SCHEMA = {
    "type": "object",
    "properties": {
        "ids": {"type": "array", "items": {"type": "integer"}, "description": "Registered amount ids."},
        "paid_on": {"type": "string", "description": "YYYY-MM-DD, for marking paid."},
        "how": {"type": "string", "description": "e.g. bank, Wise, M-Pesa, for marking paid."},
        "evidence_url": {"type": "string"},
    },
    "required": ["ids"],
}
