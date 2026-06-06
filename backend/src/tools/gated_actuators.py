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


def taiga_create_task_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    Draft the creation of a Taiga task. Routes through the gate; the task is
    only created after a human approves the draft.
    """
    subject = tool_input.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        return "Error: subject is required."
    subject = subject.strip()
    project = (tool_input.get("project") or "").strip()
    description = (tool_input.get("description") or "").strip()

    payload: Dict[str, Any] = {"subject": subject}
    if project:
        payload["project"] = project
    if description:
        payload["description"] = description
    if (context or {}).get("notify_channel"):
        payload["notify_channel"] = context["notify_channel"]

    def _executor(_action: Dict[str, Any]) -> str:
        # Runs ONLY after approval (via execute_approved). Built with list args
        # and no shell. The exact create subcommand is the documented
        # ``mcp-taiga create``; flags below are the conservative, known form.
        # TODO(mcp-taiga): confirm the precise flag names for project and
        # description (``--project`` / ``--description`` assumed). If unknown at
        # run time, this fails safe by surfacing mcp-taiga's own error rather
        # than guessing a destructive variant.
        argv = ["mcp-taiga", "create", subject]
        if project:
            argv += ["--project", project]
        if description:
            argv += ["--description", description]
        return run_cli(argv)

    target = project or "taiga"
    preview = f"Create Taiga task: {subject!r}" + (f" in {project!r}" if project else "")
    return _route_through_gate(
        action_type="taiga_create_task",
        context=context,
        target=target,
        payload=payload,
        preview=preview,
        executor=_executor,
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
            "description": "Optional Taiga project slug/name to create the task in.",
        },
        "description": {
            "type": "string",
            "description": "Optional task description / body.",
        },
    },
    "required": ["subject"],
}


# ---------------------------------------------------------------------------
# slack_post — post a message to Slack (GATED)
# ---------------------------------------------------------------------------


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

    def _executor(action: Dict[str, Any]) -> str:
        # Runs ONLY after approval. Delegate to the existing slack_tools
        # implementation so the real posting logic lives in one place. The
        # approved action's payload carries the message fields.
        from src.tools import slack_tools

        approved_payload = action.get("payload") or payload
        return slack_tools.slack_post_impl(approved_payload, context)

    preview = f"Post to {channel}: {text[:140]}" + ("…" if len(text) > 140 else "")
    return _route_through_gate(
        action_type="slack_post",
        context=context,
        target=channel,
        payload=payload,
        preview=preview,
        executor=_executor,
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
