"""
Gated actuators — Amebo's "hands": outbound actions that change the world
(create a Taiga task, post to Slack).

Hard rule (BOUNDARIES.md, DRAFT_APPROVAL_GATE.md, gated_actions.py):

    A background claw must NEVER take an irreversible OUTBOUND or DESTRUCTIVE
    action without a human approving first.

So these tools do NOT perform their side effect directly. Each one routes
through the EXISTING draft-approval gate (``DraftApprovalService.gate_or_execute``)
and reuses the EXISTING classification (``gated_actions.requires_approval`` /
``GATED_ACTIONS``). The action type equals the tool name, which is gated, so
the gate creates a ``pending_action`` (a draft), notifies a human, and returns
WITHOUT running the executor. The actuator then reports the pending action back
to the model instead of claiming the action happened.

The real side effect is supplied as a closure (the ``executor``) but is only
ever invoked by the gate for a FREE action. For these gated tools the gate
never calls it; the side effect runs later, only on human approval, via
``DraftApprovalService.execute_approved`` from the API/dispatcher. This keeps a
single gate and a single classification — we do not invent a second gate.

Org isolation: the gate is keyed by ``org_id`` taken from the tool ``context``
(the same ``org_id`` the read tools and goal-introspection tools use). Without
an org context the actuator refuses, rather than acting under an ambiguous
identity.

Subprocess discipline for the deferred side effect mirrors cli_read_tools:
list args, no ``shell=True``, timeout. But note that for a gated action the
subprocess is NOT run at tool-call time — only the draft is created.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from src.services.draft_approval_service import DraftApprovalService
from src.tools.cli_read_tools import run_cli

logger = logging.getLogger(__name__)


def _org_id(context: Dict[str, Any]) -> Optional[int]:
    raw = (context or {}).get("org_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _acting_identity(context: Dict[str, Any], org_id: int) -> str:
    """
    The stamped actor for the draft. A live, delegated turn carries a principal
    in context; a background claw acts as the team service identity
    ``amebo:<org_id>``. We reuse the credential-helper URI conventions without
    importing a god-token: identity is a label, not a credential.
    """
    principal = (context or {}).get("principal") or (context or {}).get("acting_principal")
    if principal:
        return f"urn:amebo:user:{principal}"
    return f"amebo:{org_id}"


def _gate(context: Dict[str, Any]) -> DraftApprovalService:
    """
    Resolve the gate. Tests inject a fake via ``context['draft_gate']`` so no
    DB is touched; production constructs the real service (which the dispatcher
    can also supply with a notifier).
    """
    injected = (context or {}).get("draft_gate")
    if injected is not None:
        return injected
    return DraftApprovalService()


def _route_through_gate(
    *,
    action_type: str,
    context: Dict[str, Any],
    target: Optional[str],
    payload: Dict[str, Any],
    preview: str,
    executor: Callable[[Dict[str, Any]], str],
) -> str:
    """
    Send one outbound action through the draft-approval gate. Returns a
    human-readable string for the model.

    For a GATED action (all actuators here) the gate creates a pending_action
    and does NOT run ``executor`` — we return a '[held for approval]' message.
    The closure is still passed so that if classification ever marks the action
    FREE, the SAME gate executes it; we never branch around the gate.
    """
    org_id = _org_id(context)
    if org_id is None:
        return (
            "Error: no org context available — refusing to draft an outbound "
            "action without a team identity to attribute it to."
        )

    gate = _gate(context)
    result = gate.gate_or_execute(
        org_id=org_id,
        action_type=action_type,
        acting_identity=_acting_identity(context, org_id),
        executor=executor,
        target=target,
        payload=payload,
        preview=preview,
        instance_id=(context or {}).get("instance_id"),
        goal_id=(context or {}).get("goal_id"),
    )

    if result.gated:
        pa = result.pending_action or {}
        notice = " A human has been notified." if result.notification_sent else ""
        return (
            f"[held for approval] {action_type} was NOT performed. A draft "
            f"(pending action {pa.get('id')}) was created and awaits human "
            f"approval.{notice}\nPreview: {preview}"
        )
    # FREE path (not expected for these actuators, but honour it): the gate ran
    # the executor for us.
    return result.result or "(action executed)"


# ---------------------------------------------------------------------------
# taiga_create_task — create a Taiga task (GATED)
# ---------------------------------------------------------------------------


def execute_taiga_create(action: Dict[str, Any]) -> str:
    """Perform a Taiga task creation from a (pending) action's payload.

    This is THE single side effect for ``taiga_create_task``: used both as the
    gate's executor at draft time and — via the same reference in the executor
    registry — when a human approves the pending_action later. It reads
    everything from ``action["payload"]`` so it works without the original
    closure. Built with list args and no shell.

    CLI shape (confirmed against the live ``mcp-taiga``): ``create PROJECT
    SUBJECT [--description D] [--due YYYY-MM-DD] [--assign USER] [--cash N]``.
    """
    payload = action.get("payload") or {}
    project = payload.get("project")
    subject = payload.get("subject")
    if not project or not subject:
        return "Error: cannot create task — payload is missing project or subject."

    argv = ["mcp-taiga", "create", project, subject]
    if payload.get("description"):
        argv += ["--description", payload["description"]]
    if payload.get("due_date"):
        argv += ["--due", payload["due_date"]]
    if payload.get("assignee"):
        argv += ["--assign", payload["assignee"]]
    if payload.get("cash") is not None:
        argv += ["--cash", str(payload["cash"])]
    out = run_cli(argv)
    # run_cli degrades gracefully (returns an error string, never raises) so the
    # read-tool loop keeps going. But this is a WRITE: a silent failure must NOT
    # be recorded as 'executed'. mcp-taiga prints "Created #<ref>: ..." on
    # success; anything else means the task was not created — raise so
    # execute_approved marks the action failed and stores the reason.
    if "Created #" not in out:
        raise RuntimeError(f"taiga_create_task failed: {out.strip()}")
    return out


def _valid_due_date(value: str) -> bool:
    from datetime import datetime
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def taiga_create_task_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    Draft the creation of a Taiga task. Routes through the gate; the task is
    only created after a human approves the draft.

    A deadline is REQUIRED on every task (team rule). If no due date is given,
    we refuse and tell the model to ask the user for one rather than create a
    dateless task.
    """
    subject = tool_input.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        return "Error: subject is required."
    subject = subject.strip()
    project = (tool_input.get("project") or "").strip()
    if not project:
        # Confirmed against the live CLI: `mcp-taiga create PROJECT SUBJECT`
        # requires a project. Refuse to draft a task with no project rather
        # than create a pending action that can never execute.
        return "Error: project is required (a Taiga project slug/name)."

    due_date = (tool_input.get("due_date") or "").strip()
    if not due_date:
        return (
            "Error: due_date is required (YYYY-MM-DD). Every task needs a "
            "deadline — ask the user for one, then create the task."
        )
    if not _valid_due_date(due_date):
        return f"Error: due_date {due_date!r} is not a valid date. Use YYYY-MM-DD."

    description = (tool_input.get("description") or "").strip()
    assignee = (tool_input.get("assignee") or "").strip()
    cash = tool_input.get("cash")

    payload: Dict[str, Any] = {
        "subject": subject,
        "project": project,
        "due_date": due_date,
    }
    if description:
        payload["description"] = description
    if assignee:
        payload["assignee"] = assignee
    if cash is not None:
        payload["cash"] = cash
    if (context or {}).get("notify_channel"):
        payload["notify_channel"] = context["notify_channel"]

    bits = [f"Create Taiga task: {subject!r} in {project!r} due {due_date}"]
    if assignee:
        bits.append(f"assigned to {assignee}")
    if cash is not None:
        bits.append(f"${cash}")
    preview = ", ".join(bits)

    return _route_through_gate(
        action_type="taiga_create_task",
        context=context,
        target=project,
        payload=payload,
        preview=preview,
        executor=execute_taiga_create,
    )


TAIGA_CREATE_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {
            "type": "string",
            "description": "Task title / subject.",
        },
        "project": {
            "type": "string",
            "description": "Taiga project slug/name to create the task in (required).",
        },
        "description": {
            "type": "string",
            "description": "Task description / body. Include full context so the "
                           "task is doable on its own — not a one-liner.",
        },
        "due_date": {
            "type": "string",
            "description": "Deadline as YYYY-MM-DD. REQUIRED — every task needs a "
                           "deadline. If the user didn't give one, ask before creating.",
        },
        "assignee": {
            "type": "string",
            "description": "Optional Taiga username to assign the task to.",
        },
        "cash": {
            "type": "integer",
            "description": "Optional funds to attach to the task (adds a cash tag).",
        },
    },
    "required": ["subject", "project", "due_date"],
}


# Register the executor so an approved taiga_create_task pending_action can be
# run from its stored payload (see src/services/action_executors.py).
from src.services.action_executors import register_executor  # noqa: E402
register_executor("taiga_create_task", execute_taiga_create)


# ---------------------------------------------------------------------------
# taiga writes: update / comment / close — all GATED. Same shape as create: an
# _impl drafts through the gate; a matching executor performs the one side
# effect (at draft time if free, else on human approval). Per-org routing: the
# acting org id is carried in the payload so the approve-time executor can build
# the org's Taiga env even detached from the request context.
# ---------------------------------------------------------------------------


def _ctx_org_id(context: Dict[str, Any]) -> Any:
    oc = (context or {}).get("org_context")
    return getattr(oc, "org_id", None) or (context or {}).get("org_id")


def _taiga_env(payload: Dict[str, Any]):
    from src.tools.cli_read_tools import _conn_env
    return _conn_env({"org_id": payload.get("org_id")}, "tasks")


def _cli_failed(out: str) -> bool:
    """run_cli never raises; a write must not be logged 'executed' on failure.
    It returns 'Error: …' (no stdout) or appends '[exit N: …]' (stdout+nonzero)."""
    s = (out or "").strip()
    return s.startswith("Error") or "[exit " in s


def execute_taiga_update(action: Dict[str, Any]) -> str:
    payload = action.get("payload") or {}
    project, ref = payload.get("project"), payload.get("ref")
    if not project or ref in (None, ""):
        return "Error: cannot update — payload missing project or ref."
    argv = ["mcp-taiga", "update", str(project), str(ref)]
    if payload.get("status"):
        argv += ["--status", str(payload["status"])]
    if payload.get("assignee"):
        argv += ["--assign", str(payload["assignee"])]
    if payload.get("due_date"):
        argv += ["--due", str(payload["due_date"])]
    if payload.get("description"):
        argv += ["--description", str(payload["description"])]
    out = run_cli(argv, env=_taiga_env(payload))
    if _cli_failed(out):
        raise RuntimeError(f"taiga_update_task failed: {out.strip()}")
    return out


def execute_taiga_comment(action: Dict[str, Any]) -> str:
    payload = action.get("payload") or {}
    project, ref, text = payload.get("project"), payload.get("ref"), payload.get("text")
    if not project or ref in (None, "") or not (text or "").strip():
        return "Error: cannot comment — payload missing project, ref, or text."
    out = run_cli(["mcp-taiga", "comment", str(project), str(ref), text],
                  env=_taiga_env(payload))
    if _cli_failed(out):
        raise RuntimeError(f"taiga_add_comment failed: {out.strip()}")
    return out


def execute_taiga_close(action: Dict[str, Any]) -> str:
    payload = action.get("payload") or {}
    project, ref = payload.get("project"), payload.get("ref")
    status = (payload.get("status") or "Done")
    if not project or ref in (None, ""):
        return "Error: cannot close — payload missing project or ref."
    out = run_cli(["mcp-taiga", "move", str(project), str(ref), str(status)],
                  env=_taiga_env(payload))
    if _cli_failed(out):
        raise RuntimeError(f"taiga_close_task failed: {out.strip()}")
    return out


def taiga_update_task_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Draft an update to a Taiga story (status / assignee / due / description).
    Gated — applied only on human approval."""
    project = (tool_input.get("project") or "").strip()
    ref = tool_input.get("ref")
    if not project or ref in (None, ""):
        return "Error: project and ref are required."
    fields = {k: tool_input[k] for k in ("status", "assignee", "due_date", "description")
              if tool_input.get(k)}
    if not fields:
        return "Error: nothing to update (set at least one of status/assignee/due_date/description)."
    if fields.get("due_date") and not _valid_due_date(fields["due_date"]):
        return f"Error: due_date {fields['due_date']!r} is not valid. Use YYYY-MM-DD."
    payload = {"project": project, "ref": ref, "org_id": _ctx_org_id(context), **fields}
    preview = f"Update Taiga {project}#{ref}: " + ", ".join(f"{k}={v}" for k, v in fields.items())
    return _route_through_gate(
        action_type="taiga_update_task", context=context, target=f"{project}#{ref}",
        payload=payload, preview=preview, executor=execute_taiga_update,
    )


def taiga_add_comment_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Draft a comment on a Taiga story. Gated."""
    project = (tool_input.get("project") or "").strip()
    ref = tool_input.get("ref")
    text = (tool_input.get("text") or "").strip()
    if not project or ref in (None, "") or not text:
        return "Error: project, ref, and text are required."
    payload = {"project": project, "ref": ref, "text": text, "org_id": _ctx_org_id(context)}
    return _route_through_gate(
        action_type="taiga_add_comment", context=context, target=f"{project}#{ref}",
        payload=payload, preview=f"Comment on Taiga {project}#{ref}: {text[:80]}",
        executor=execute_taiga_comment,
    )


def taiga_close_task_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Draft closing (moving to a done status) a Taiga story. Gated."""
    project = (tool_input.get("project") or "").strip()
    ref = tool_input.get("ref")
    status = (tool_input.get("status") or "Done").strip()
    if not project or ref in (None, ""):
        return "Error: project and ref are required."
    payload = {"project": project, "ref": ref, "status": status, "org_id": _ctx_org_id(context)}
    return _route_through_gate(
        action_type="taiga_close_task", context=context, target=f"{project}#{ref}",
        payload=payload, preview=f"Close Taiga {project}#{ref} (move to {status!r})",
        executor=execute_taiga_close,
    )


TAIGA_UPDATE_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "project": {"type": "string", "description": "Taiga project slug/name."},
        "ref": {"type": "integer", "description": "Story reference number (e.g. 42)."},
        "status": {"type": "string", "description": "New status name (e.g. 'In progress')."},
        "assignee": {"type": "string", "description": "Taiga username to assign to."},
        "due_date": {"type": "string", "description": "New due date YYYY-MM-DD."},
        "description": {"type": "string", "description": "New description."},
    },
    "required": ["project", "ref"],
}

TAIGA_ADD_COMMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "project": {"type": "string", "description": "Taiga project slug/name."},
        "ref": {"type": "integer", "description": "Story reference number."},
        "text": {"type": "string", "description": "Comment body."},
    },
    "required": ["project", "ref", "text"],
}

TAIGA_CLOSE_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "project": {"type": "string", "description": "Taiga project slug/name."},
        "ref": {"type": "integer", "description": "Story reference number."},
        "status": {"type": "string", "description": "Done/closed status name (default 'Done')."},
    },
    "required": ["project", "ref"],
}

register_executor("taiga_update_task", execute_taiga_update)
register_executor("taiga_add_comment", execute_taiga_comment)
register_executor("taiga_close_task", execute_taiga_close)


# ---------------------------------------------------------------------------
# CRM writes (Odoo) — all GATED. Mapped to the REAL odoo-cli verbs (the plan's
# crm_log_note/create_lead/update_stage names were guesses; these are the verbs
# the CLI actually has and the team uses). Per-org env via the payload's org id.
# ---------------------------------------------------------------------------


def _crm_env(payload: Dict[str, Any]):
    from src.tools.cli_read_tools import _conn_env
    return _conn_env({"org_id": payload.get("org_id")}, "crm")


def execute_crm_schedule(action: Dict[str, Any]) -> str:
    """odoo-cli schedule <contact> <when> [summary] — set a next step/activity."""
    p = action.get("payload") or {}
    contact, when = p.get("contact"), p.get("when")
    if not contact or not when:
        return "Error: cannot schedule — payload missing contact or when."
    argv = ["odoo-cli", "schedule", str(contact), str(when)]
    if p.get("summary"):
        argv.append(str(p["summary"]))
    out = run_cli(argv, env=_crm_env(p))
    if _cli_failed(out):
        raise RuntimeError(f"crm_schedule failed: {out.strip()}")
    return out


def execute_crm_tag(action: Dict[str, Any]) -> str:
    """odoo-cli contact-tag <contact> <tag> — tag/categorize a contact."""
    p = action.get("payload") or {}
    contact, tag = p.get("contact"), p.get("tag")
    if not contact or not tag:
        return "Error: cannot tag — payload missing contact or tag."
    out = run_cli(["odoo-cli", "contact-tag", str(contact), str(tag)], env=_crm_env(p))
    if _cli_failed(out):
        raise RuntimeError(f"crm_tag_contact failed: {out.strip()}")
    return out


def execute_crm_contacted(action: Dict[str, Any]) -> str:
    """odoo-cli contacted <contact> [date] — log last-contacted."""
    p = action.get("payload") or {}
    contact = p.get("contact")
    if not contact:
        return "Error: cannot log contact — payload missing contact."
    argv = ["odoo-cli", "contacted", str(contact)]
    if p.get("date"):
        argv.append(str(p["date"]))
    out = run_cli(argv, env=_crm_env(p))
    if _cli_failed(out):
        raise RuntimeError(f"crm_log_contacted failed: {out.strip()}")
    return out


def crm_schedule_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Draft setting a next step (activity) on a CRM contact. Gated. This is how
    a deal gets a 'next step' — the pipeline-hygiene fix."""
    contact = (tool_input.get("contact") or "").strip()
    when = (tool_input.get("when") or "").strip()
    if not contact or not when:
        return "Error: contact and when are required (when: YYYY-MM-DD or 'tuesday')."
    summary = (tool_input.get("summary") or "").strip()
    payload = {"contact": contact, "when": when, "org_id": _ctx_org_id(context)}
    if summary:
        payload["summary"] = summary
    preview = f"CRM: schedule next step for {contact} on {when}" + (f" — {summary}" if summary else "")
    return _route_through_gate(
        action_type="crm_schedule", context=context, target=contact,
        payload=payload, preview=preview, executor=execute_crm_schedule,
    )


def crm_tag_contact_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Draft tagging a CRM contact (e.g. 'ally', 'partner'). Gated."""
    contact = (tool_input.get("contact") or "").strip()
    tag = (tool_input.get("tag") or "").strip()
    if not contact or not tag:
        return "Error: contact and tag are required."
    payload = {"contact": contact, "tag": tag, "org_id": _ctx_org_id(context)}
    return _route_through_gate(
        action_type="crm_tag_contact", context=context, target=contact,
        payload=payload, preview=f"CRM: tag {contact!r} as {tag!r}",
        executor=execute_crm_tag,
    )


def crm_log_contacted_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Draft logging that a CRM contact was contacted (date defaults to today).
    Gated."""
    contact = (tool_input.get("contact") or "").strip()
    if not contact:
        return "Error: contact is required."
    date = (tool_input.get("date") or "").strip()
    payload = {"contact": contact, "org_id": _ctx_org_id(context)}
    if date:
        payload["date"] = date
    return _route_through_gate(
        action_type="crm_log_contacted", context=context, target=contact,
        payload=payload, preview=f"CRM: log contacted {contact}" + (f" on {date}" if date else ""),
        executor=execute_crm_contacted,
    )


CRM_SCHEDULE_SCHEMA = {
    "type": "object",
    "properties": {
        "contact": {"type": "string", "description": "Contact name (or email) in the CRM."},
        "when": {"type": "string", "description": "When: YYYY-MM-DD, 'tuesday', 'next week'."},
        "summary": {"type": "string", "description": "What the next step is."},
    },
    "required": ["contact", "when"],
}

CRM_TAG_CONTACT_SCHEMA = {
    "type": "object",
    "properties": {
        "contact": {"type": "string", "description": "Contact name (or email)."},
        "tag": {"type": "string", "description": "Tag to add (e.g. 'ally', 'partner')."},
    },
    "required": ["contact", "tag"],
}

CRM_LOG_CONTACTED_SCHEMA = {
    "type": "object",
    "properties": {
        "contact": {"type": "string", "description": "Contact name (or email)."},
        "date": {"type": "string", "description": "Date contacted YYYY-MM-DD (default today)."},
    },
    "required": ["contact"],
}

register_executor("crm_schedule", execute_crm_schedule)
register_executor("crm_tag_contact", execute_crm_tag)
register_executor("crm_log_contacted", execute_crm_contacted)


# ---------------------------------------------------------------------------
# slack_post — post a message to Slack (GATED)
# ---------------------------------------------------------------------------


def execute_slack_post(action: Dict[str, Any]) -> str:
    """Post a Slack message from a (pending) action's payload.

    THE single side effect for slack_post: used by the gate at draft time and,
    via the executor registry, when a human approves the pending_action later.
    Delegates the real posting (token, @-mention rules) to slack_tools so it
    lives in one place. Raises on failure so a silently-failed post is recorded
    as 'failed', not 'executed' (slack_tools returns 'Error: …' on failure).
    """
    from src.tools import slack_tools

    payload = action.get("payload") or {}
    if not payload.get("channel") or not (payload.get("text") or "").strip():
        return "Error: cannot post — payload missing channel or text."
    # A channel broadcast (a claw digest / announcement) has no single recipient
    # to @-mention. Such payloads opt out explicitly with require_mention=False;
    # personal pings keep the default (mention required, so the recipient is
    # actually notified).
    context: Dict[str, Any] = {}
    if payload.get("require_mention") is False:
        from types import SimpleNamespace
        context = {"guardrails": SimpleNamespace(slack_require_mention=False)}
    result = slack_tools.slack_post_impl(payload, context)
    if isinstance(result, str) and result.startswith("Error"):
        raise RuntimeError(f"slack_post failed: {result}")
    return result


def slack_post_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    Draft a Slack message. Routes through the gate; the message is only posted
    after a human approves the draft.

    Note: this is the gated actuator that reuses the existing
    ``src.tools.slack_tools.slack_post_impl`` as the deferred side effect, so
    the actual posting logic (token, @-mention rules) is not duplicated. The
    difference is that here the post is NEVER executed at tool-call time — it
    becomes a pending_action first.
    """
    channel = (tool_input.get("channel") or "").strip()
    text = tool_input.get("text") or ""
    if not channel:
        return "Error: channel is required."
    if not isinstance(text, str) or not text.strip():
        return "Error: text is required."

    payload: Dict[str, Any] = {
        "channel": channel,
        "text": text,
    }
    if tool_input.get("thread_ts"):
        payload["thread_ts"] = tool_input["thread_ts"]
    if tool_input.get("mention_user_id"):
        payload["mention_user_id"] = tool_input["mention_user_id"]
    if (context or {}).get("notify_channel"):
        payload["notify_channel"] = context["notify_channel"]

    preview = f"Post to {channel}: {text[:140]}" + ("…" if len(text) > 140 else "")
    return _route_through_gate(
        action_type="slack_post",
        context=context,
        target=channel,
        payload=payload,
        preview=preview,
        executor=execute_slack_post,
    )


SLACK_POST_SCHEMA = {
    "type": "object",
    "properties": {
        "channel": {
            "type": "string",
            "description": "Channel name (e.g. '#standup') or Slack channel id.",
        },
        "text": {
            "type": "string",
            "description": "Message body.",
        },
        "thread_ts": {
            "type": "string",
            "description": "Optional thread_ts to reply inside an existing thread.",
        },
        "mention_user_id": {
            "type": "string",
            "description": (
                "Slack user id to @-mention so the recipient is actually "
                "notified (e.g. UHUUD9ERZ)."
            ),
        },
    },
    "required": ["channel", "text"],
}


# Register the slack_post executor so an approved slack_post pending_action can
# be posted from its stored payload (see src/services/action_executors.py).
register_executor("slack_post", execute_slack_post)
