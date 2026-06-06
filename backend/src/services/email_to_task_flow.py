"""
Email-to-task flow — the flagship near-term claw use case.

The scenario, in Golda's own words: "we got an email, I copied it to the CRM,
make the task and tell people in Slack." A human forwards an email into the CRM;
the claw reads the latest one from a given sender, crystallizes it into a Taiga
task, and notifies the right Slack channel. The task-create and the Slack post
are NEVER sent blind — both are held as APPROVAL DRAFTS routed through the
draft-approval gate (``draft_approval_service.py``), and the Slack notification
ALSO passes the human-output gate (``human_output_gate.py``) so it stays concise.

Where this sits in the boundaries (docs/BOUNDARIES.md):

  - Reading the forwarded email      → CRM (Odoo) is the system of record; the
                                        flow only references it via a reader seam.
  - Crystallizing the email → a task → Amebo's own job (the agency layer).
  - Creating the Taiga task          → Taiga is the system of record; GATED
                                        (outbound/destructive) → draft, not direct.
  - Notifying Slack                  → outbound → GATED → draft; and a
                                        human-facing message → output gate.

Additive by construction. This module imports NO channel, NO CRM client, NO
Taiga client, and does NOT touch ``registry.py``. Every external dependency is
injected as a Protocol so the real adapters attach at the call site (TODOs mark
exactly where) and tests inject fakes. The flow itself performs NO direct side
effect: everything outbound is a gated draft (a ``pending_action``), and the
flow returns the ids of the drafts it queued.

See docs/EMAIL_TO_TASK_FLOW.md for the full design and the injection seams.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


# ===========================================================================
# Action-type constants — must line up with gated_actions.GATED_ACTIONS.
# ===========================================================================
#
# These name the OUTBOUND actions this flow drafts. Both are GATED in
# ``gated_actions.py`` (default-deny would gate them anyway, but they are
# explicitly listed there), so routing them through the gate yields a
# pending_action rather than a direct call. Defined as constants here so the
# flow never hardcodes a magic string at a call site.
ACTION_CREATE_TASK = "mcp_taiga"   # writes a Taiga task (outbound/destructive)
ACTION_SLACK_POST = "slack_post"   # posts to Slack (outbound)


# ===========================================================================
# Injected dependency seams (Protocols). The flow depends on these, never on a
# concrete client. Real adapters attach at the call site; tests inject fakes.
# ===========================================================================


@dataclass(frozen=True)
class ForwardedEmail:
    """One forwarded email as read from the CRM.

    Minimal shape the flow needs to crystallize a task. A real CRM adapter maps
    the Odoo record (mail.message / crm.lead note, etc.) onto these fields.
    """

    sender: str                      # the original sender the human forwarded
    subject: str
    body: str
    received_at: Optional[str] = None        # ISO timestamp, if the CRM has one
    source_url: Optional[str] = None         # deep link back to the CRM record
    message_id: Optional[str] = None         # CRM-side id, for provenance/dedup


class CrmEmailReader(Protocol):
    """Reads forwarded emails out of the CRM.

    The real adapter calls the CRM read tool (Odoo ``mail.message`` lookup for
    the forwarded note) — a READ-ONLY operation, so it is NOT gated. The flow
    only ever reads here; it never writes to the CRM.

    TODO(crm-adapter): implement a ``CrmEmailReader`` that calls the existing
    CRM read path (the ``odoo_cli`` / Odoo client used elsewhere in amebo,
    scoped read-only). It must return the LATEST forwarded email from ``sender``
    for the given org, or None when there is nothing to act on.
    """

    def latest_forwarded_from(
        self, *, sender: str, org_id: int
    ) -> Optional[ForwardedEmail]:
        """Return the most recent forwarded email from ``sender`` for ``org_id``,
        or None if there is none."""
        ...


class TaskCreator(Protocol):
    """Creates a task in the task system of record (Taiga).

    Writing a task is OUTBOUND/DESTRUCTIVE, so the flow NEVER calls this
    directly — it routes the create through the draft-approval gate as a
    ``mcp_taiga`` action, which holds it as a pending_action until a human
    approves. This Protocol is the executor the gate would run AFTER approval
    (via ``execute_approved``); the flow only drafts.

    TODO(taiga-adapter): implement a ``TaskCreator`` that calls the existing
    ``mcp_taiga`` tool to create the task, returning a human-readable result
    (e.g. the created task ref/url). It is invoked only on approval, never by
    the flow's draft step.
    """

    def create_task(self, task: "DraftedTask") -> str:
        """Create the task and return a human-readable result string."""
        ...


class Notifier(Protocol):
    """Posts a human-facing message to a channel.

    Mirrors ``draft_approval_service.Notifier`` / ``goal_dispatcher.Notifier``
    so the same Slack adapter can be reused. Posting to Slack is OUTBOUND, so
    the flow NEVER calls this directly: the Slack notification is routed through
    BOTH the draft-approval gate (it becomes a ``slack_post`` pending_action)
    AND the human-output gate (so the message is concise / non-noisy).

    TODO(slack-adapter): implement a ``Notifier`` that calls the existing Slack
    send path. It is the executor the gate runs on approval, never by the draft
    step.
    """

    def notify(self, channel: str, message: str) -> bool:
        """Post ``message`` to ``channel``; return True on success."""
        ...


class ApprovalGate(Protocol):
    """The draft-approval gate seam.

    Satisfied by ``draft_approval_service.DraftApprovalService`` (its
    ``create_pending_action`` signature). The flow depends on this narrow
    Protocol so unit tests can inject a fake gate that records drafts WITHOUT a
    database, while production passes the real service. The flow uses
    ``create_pending_action`` directly (not ``gate_or_execute``) because for
    THIS flow both actions are always gated and must NEVER execute inline — we
    want a draft every time, never a conditional immediate send.
    """

    def create_pending_action(
        self,
        org_id: int,
        action_type: str,
        acting_identity: str,
        target: Optional[str] = ...,
        payload: Optional[Dict[str, Any]] = ...,
        preview: Optional[str] = ...,
        instance_id: Optional[int] = ...,
        goal_id: Optional[str] = ...,
    ) -> Dict[str, Any]:
        ...


class OutputGate(Protocol):
    """The human-output (message) gate seam.

    Satisfied by ``human_output_gate.HumanOutputGate.gate``. Used to run the
    Slack notification text through dedup / rate-limit / crystallize BEFORE it
    is drafted, so the drafted message a human approves is already the concise
    one. Returns an object exposing ``should_send``, ``text`` and ``thread_ts``
    (the ``GateDecision`` shape).
    """

    def gate(
        self,
        message: str,
        *,
        channel: str,
        thread_ts: Optional[str] = ...,
        urgency: str = ...,
        goal_id: Optional[str] = ...,
    ) -> Any:
        ...


# ===========================================================================
# Data shapes the flow produces.
# ===========================================================================


@dataclass
class DraftedTask:
    """A task crystallized from a forwarded email, before it is created.

    This is the "crystallize the email into a task" output: the title, the
    description, and a source link back to the originating CRM record so the
    eventual Taiga task is traceable to its evidence.
    """

    title: str
    description: str
    source_url: Optional[str] = None
    source_message_id: Optional[str] = None

    def as_payload(self) -> Dict[str, Any]:
        """Serialize for the gate's ``payload`` (what the executor will act on
        after approval)."""
        return {
            "title": self.title,
            "description": self.description,
            "source_url": self.source_url,
            "source_message_id": self.source_message_id,
        }


@dataclass
class FlowResult:
    """Outcome of one run of the flow.

    The flow performs NO direct side effect. When an email was found it returns
    the email it read, the task it drafted, and the ids of the pending_actions
    (drafts) it queued for human approval. When there was no email it is a clean
    no-op (``email`` and ``drafted_task`` are None, no pending actions).
    """

    email: Optional[ForwardedEmail] = None
    drafted_task: Optional[DraftedTask] = None
    # ids of the gated pending_actions created, keyed by action type.
    task_pending_action_id: Optional[str] = None
    slack_pending_action_id: Optional[str] = None
    # disposition of the Slack message after the output gate (send/defer/suppress).
    slack_output_disposition: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @property
    def acted(self) -> bool:
        """True when there was an email to process (drafts were queued)."""
        return self.email is not None

    @property
    def pending_action_ids(self) -> List[str]:
        """All pending_action ids this run created, in queue order."""
        return [
            pid
            for pid in (self.task_pending_action_id, self.slack_pending_action_id)
            if pid
        ]


# ===========================================================================
# Crystallize: email → task. Deterministic; no model.
# ===========================================================================


def _crystallize_email_to_task(email: ForwardedEmail) -> DraftedTask:
    """Turn a forwarded email into a drafted task.

    Deterministic and offline-safe (no model call here): the title is derived
    from the subject, the description carries sender + body + provenance, and
    the source link points back at the CRM record. When the crystallize engine
    lands (docs/CRYSTALLIZE.md) the description could be distilled further, but
    this flow keeps a faithful, reviewable draft — a human approves it before it
    becomes a real task.
    """
    subject = (email.subject or "").strip()
    title = subject or f"Follow up on email from {email.sender}"

    desc_lines: List[str] = [
        f"From: {email.sender}",
    ]
    if email.received_at:
        desc_lines.append(f"Received: {email.received_at}")
    desc_lines.append("")
    body = (email.body or "").strip()
    desc_lines.append(body or "(no body)")
    if email.source_url:
        desc_lines.append("")
        desc_lines.append(f"Source (CRM): {email.source_url}")

    return DraftedTask(
        title=title,
        description="\n".join(desc_lines),
        source_url=email.source_url,
        source_message_id=email.message_id,
    )


def _slack_message_for_task(task: DraftedTask, sender: str) -> str:
    """The human-facing notification text for a drafted task.

    Kept short; the output gate will crystallize it further. Names what came in
    and what the claw proposes, with the source link so a human can verify.
    """
    lines = [
        f"New task drafted from an email forwarded by {sender}:",
        f"• {task.title}",
    ]
    if task.source_url:
        lines.append(f"  source: {task.source_url}")
    return "\n".join(lines)


# ===========================================================================
# The flow.
# ===========================================================================


def process_latest_forwarded_email(
    *,
    sender: str,
    slack_channel: str,
    org_id: int,
    readers: CrmEmailReader,
    task_creator: TaskCreator,
    notifier: Notifier,
    gate: ApprovalGate,
    output_gate: Optional[OutputGate] = None,
    acting_identity: str,
    instance_id: Optional[int] = None,
    goal_id: Optional[str] = None,
) -> FlowResult:
    """Read the latest forwarded CRM email from ``sender``, crystallize it into a
    task, and queue two GATED approval drafts: create-the-task and notify-Slack.

    The flow performs NO direct side effect. Both outbound actions become
    ``pending_action`` rows via ``gate.create_pending_action`` and run only
    after a human approves them (the injected ``task_creator`` / ``notifier``
    are the executors the gate runs on approval, never called here). The Slack
    message is additionally run through ``output_gate`` so the drafted text is
    already concise; if the output gate SUPPRESSes it (e.g. a duplicate) no
    Slack draft is queued.

    Args:
        sender: the original sender whose forwarded email to read.
        slack_channel: the channel to notify. INPUT/config — never hardcoded.
        org_id: org whose CRM/Taiga/Slack and approval queue this acts in.
        readers: CRM email reader seam (read-only; real adapter calls the CRM).
        task_creator: Taiga task-create executor (run only after approval).
        notifier: Slack notifier executor (run only after approval).
        gate: the draft-approval gate (DraftApprovalService in production).
        output_gate: the human-output gate; optional. When provided the Slack
            text is crystallized / dedup'd / rate-checked before drafting.
        acting_identity: who the draft is attributed to (e.g. ``amebo:<team>``
            for the background service identity, per BOUNDARIES.md "stamp the
            actor").
        instance_id: originating amebo instance, for provenance on the draft.
        goal_id: goal this flow is pursuing, so the draft is tied into the
            goal's audit trail.

    Returns:
        FlowResult with the email read, the drafted task, and the pending_action
        ids. On no email: a clean no-op (``acted`` is False, no drafts).
    """
    # ``task_creator`` and ``notifier`` are accepted so the executors the gate
    # runs on approval are bound at the flow's call site (not imported here),
    # keeping the channel/Taiga clients out of this module. They are NOT invoked
    # by the draft step — the flow only ever drafts. They are referenced so the
    # injection seam is explicit and lint does not flag them as unused.
    _ = (task_creator, notifier)

    result = FlowResult()

    # (1) Read the latest forwarded email (read-only; not gated).
    email = readers.latest_forwarded_from(sender=sender, org_id=org_id)
    if email is None:
        # Clean no-op: nothing forwarded from this sender. No drafts, no side
        # effects, no notification.
        result.notes.append(f"No forwarded email from {sender}; nothing to do.")
        logger.info("[email-to-task] no forwarded email from %s (org %s)", sender, org_id)
        return result
    result.email = email

    # (2) Crystallize the email into a task (Amebo's own work).
    task = _crystallize_email_to_task(email)
    result.drafted_task = task

    # (3) Draft the Taiga task as a GATED pending_action. NOT created directly.
    task_action = gate.create_pending_action(
        org_id=org_id,
        action_type=ACTION_CREATE_TASK,
        acting_identity=acting_identity,
        target="taiga",
        payload={"task": task.as_payload()},
        preview=f"Create Taiga task: {task.title}",
        instance_id=instance_id,
        goal_id=goal_id,
    )
    result.task_pending_action_id = str(task_action["id"])

    # (4) Notify Slack — routed through BOTH the output gate (conciseness /
    # noise control) AND the draft-approval gate (outbound → draft). The output
    # gate runs first so the drafted text is already the concise one a human
    # approves. ``slack_channel`` is the injected config, never hardcoded.
    raw_message = _slack_message_for_task(task, sender)

    message_to_draft = raw_message
    if output_gate is not None:
        decision = output_gate.gate(
            raw_message, channel=slack_channel, goal_id=goal_id,
        )
        disposition = getattr(decision, "disposition", None)
        result.slack_output_disposition = (
            getattr(disposition, "value", None)
            or (str(disposition) if disposition is not None else None)
        )
        if not getattr(decision, "should_send", False):
            # Output gate says do not send now (duplicate / over-noise / queued
            # to the daily stand-up). Do NOT queue a Slack draft — the task
            # draft still stands on its own.
            result.notes.append(
                "Slack notification withheld by output gate "
                f"({result.slack_output_disposition}); no Slack draft queued."
            )
            return result
        # Use the crystallized text for the draft a human will approve.
        message_to_draft = getattr(decision, "text", None) or raw_message

    slack_action = gate.create_pending_action(
        org_id=org_id,
        action_type=ACTION_SLACK_POST,
        acting_identity=acting_identity,
        target=slack_channel,
        payload={
            "channel": slack_channel,
            "text": message_to_draft,
            # Where the approval request itself should be surfaced (the gate's
            # own notifier reads payload['notify_channel']).
            "notify_channel": slack_channel,
        },
        preview=f"Notify {slack_channel}: {task.title}",
        instance_id=instance_id,
        goal_id=goal_id,
    )
    result.slack_pending_action_id = str(slack_action["id"])

    logger.info(
        "[email-to-task] org=%s sender=%s drafted task=%s slack=%s",
        org_id, sender, result.task_pending_action_id, result.slack_pending_action_id,
    )
    return result
