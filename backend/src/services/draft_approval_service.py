"""
Draft-approval service — the human-in-the-loop gate for the claw.

Strategic purpose (see docs/DRAFT_APPROVAL_GATE.md and open question #4 in
docs/ORGS_GOALS_CLAW.md): let a background claw run UNSUPERVISED safely. A claw
must never take an irreversible OUTBOUND or DESTRUCTIVE action (send a Slack
message, send email, write to CRM/Taiga, open/merge a PR) without a human
approving first. Read-only and internal actions are NOT gated.

Two layers live here:

1. The state machine over pending_actions (create / list / approve / reject /
   mark_executed / mark_failed). On create, a goal_events audit entry is
   written when the action is tied to a goal, reusing the existing GoalRepo
   audit pattern — so claw activity stays interrogable through the same trail
   as everything else.

2. The gate: `requires_approval(action_type)` + `gate_or_execute(...)`. For a
   gated action the gate records a pending_action and NOTIFIES instead of
   executing. For a free action it executes immediately. Approval itself does
   NOT send anything — it transitions state and returns the action for the
   caller/executor to perform. Execution is pluggable.

Org isolation: every approve/reject/mark_* takes the caller's org_id and the
repo guards on it in the UPDATE, so one org can never decide or run another
org's pending action.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from src.db.repositories.goal_repo import GoalRepo
from src.db.repositories.pending_action_repo import PendingActionRepo
from src.services import gated_actions

logger = logging.getLogger(__name__)


class PendingActionNotFound(LookupError):
    """Raised when an action id is unknown, or belongs to a different org, or
    is not in the state the requested transition needs."""


# A notifier takes (channel_spec, message_text) and returns True on success.
# Mirrors goal_dispatcher.Notifier so the same adapters can be reused.
Notifier = Callable[[str, str], bool]


def _default_notifier(channel: Optional[str], message: str) -> bool:
    """
    Fallback notifier: log it. A real channel adapter (Slack DM to the org's
    approver, email, etc.) plugs in at construction time.

    TODO(notify): wire this to the existing notify channel used by
    GoalDispatcher (_default_notifier / the Slack adapter passed at dispatcher
    construction) so an approval request reaches a human the same way a goal
    completion notification does. Until then it logs, which is safe: the
    pending_action row is the durable source of truth and the API surfaces it.
    """
    logger.info("[draft-approval-notify] %s :: %s", channel, message)
    return True


# An executor performs a single approved action and returns a human-readable
# result string. It is provided by the caller; the service never imports a
# channel/tool directly, keeping execution pluggable.
Executor = Callable[[Dict[str, Any]], str]


@dataclass
class GateResult:
    """Outcome of running an action through the gate."""

    gated: bool                              # True if it was held for approval
    executed: bool                           # True if it ran immediately (free)
    result: Optional[str] = None             # executor output, when executed
    pending_action: Optional[Dict[str, Any]] = None  # the row, when gated
    notification_sent: bool = False          # whether an approval notice went out


class DraftApprovalService:
    """Cheap to instantiate. Holds repositories and an optional notifier."""

    def __init__(
        self,
        repo: Optional[PendingActionRepo] = None,
        goal_repo: Optional[GoalRepo] = None,
        notifier: Optional[Notifier] = None,
    ):
        self._repo = repo or PendingActionRepo()
        self._goal_repo = goal_repo or GoalRepo()
        self._notify = notifier or _default_notifier

    # --------------------------------------------------------- Classification

    @staticmethod
    def requires_approval(action_type: str) -> bool:
        """True iff this action type must be approved by a human before it
        runs. Delegates to the gated-action registry (default-deny)."""
        return gated_actions.requires_approval(action_type)

    # ------------------------------------------------------------- Create

    def create_pending_action(
        self,
        org_id: int,
        action_type: str,
        acting_identity: str,
        target: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        preview: Optional[str] = None,
        instance_id: Optional[int] = None,
        goal_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record an outbound/destructive action as 'pending' approval. When the
        action is tied to a goal, also append a goal_events audit entry so the
        claw's request to act is visible in the goal's trail.
        """
        action = self._repo.create(
            org_id=org_id,
            action_type=action_type,
            acting_identity=acting_identity,
            target=target,
            payload=payload,
            preview=preview,
            instance_id=instance_id,
            goal_id=goal_id,
        )

        if goal_id:
            # Reuse the existing audit pattern (GoalRepo.append_event). Best
            # effort — a failure to write the audit line must not lose the
            # pending action itself, which is the durable record.
            try:
                self._goal_repo.append_event(
                    goal_id=goal_id,
                    actor_type="claw",
                    action=f"draft_pending_approval:{action_type}",
                    result_summary=preview or target or action_type,
                    metadata={
                        "pending_action_id": str(action["id"]),
                        "action_type": action_type,
                        "target": target,
                        "acting_identity": acting_identity,
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to record draft_pending_approval event for goal %s "
                    "(pending_action %s persisted regardless)",
                    goal_id, action["id"],
                )

        return action

    # ------------------------------------------------------------- Reads

    def list_pending(self, instance_id: int) -> List[Dict[str, Any]]:
        """
        List pending actions for an org. Named `list_pending(instance_id)` per
        the gate spec, but the value passed is the org-scoping authority (the
        same authority `goals` use for isolation): callers pass the
        authenticated client's org_id. Provenance filtering by the originating
        amebo instance is available via list_for_instance().
        """
        return self._repo.list_for_org(instance_id, status="pending")

    def list_for_instance(
        self, org_id: int, status: Optional[str] = "pending"
    ) -> List[Dict[str, Any]]:
        """List actions for an org, optionally filtered by status. Explicit
        org-named alias for clarity at call sites."""
        return self._repo.list_for_org(org_id, status=status)

    def get(self, action_id: str, org_id: int) -> Dict[str, Any]:
        """Fetch one action, verifying org ownership. Raises
        PendingActionNotFound if unknown or owned by another org (no existence
        leak — same error either way)."""
        action = self._repo.get(action_id)
        if action is None or action["org_id"] != org_id:
            raise PendingActionNotFound(action_id)
        return action

    # ------------------------------------------------------------- Decisions

    def approve(self, action_id: str, approver: str, org_id: int) -> Dict[str, Any]:
        """
        Approve a pending action. Transitions pending → approved and records
        the approver. Does NOT execute anything — it returns the approved
        action so the caller/executor can perform it (see execute_approved).

        Org-scoped: the underlying UPDATE only matches rows owned by org_id
        that are still pending, so one org cannot approve another's action and
        a double-approve is a no-op that raises here.
        """
        updated = self._repo.set_decision(
            action_id, org_id, to_status="approved", approver=approver,
        )
        if updated is None:
            raise PendingActionNotFound(action_id)

        if updated.get("goal_id"):
            self._safe_event(
                updated["goal_id"], "draft_approved", approver,
                action_id, updated["action_type"],
            )
        return updated

    def reject(
        self, action_id: str, approver: str, org_id: int, reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Reject a pending action: pending → rejected, recording who and why.
        Org-scoped and terminal — a rejected action never executes."""
        updated = self._repo.set_decision(
            action_id, org_id, to_status="rejected",
            approver=approver, decision_reason=reason,
        )
        if updated is None:
            raise PendingActionNotFound(action_id)

        if updated.get("goal_id"):
            self._safe_event(
                updated["goal_id"], "draft_rejected", approver,
                action_id, updated["action_type"], summary=reason,
            )
        return updated

    # ------------------------------------------------------------- Execution

    def mark_executed(self, action_id: str, org_id: int) -> Dict[str, Any]:
        """Record that an approved action ran successfully (approved →
        executed). Org- and status-guarded."""
        updated = self._repo.mark_executed(action_id, org_id)
        if updated is None:
            raise PendingActionNotFound(action_id)
        if updated.get("goal_id"):
            self._safe_event(
                updated["goal_id"], "draft_executed", updated.get("approver") or "system",
                action_id, updated["action_type"],
            )
        return updated

    def mark_failed(self, action_id: str, org_id: int, error: str) -> Dict[str, Any]:
        """Record that an approved action failed during execution (approved →
        failed), storing the error. Org- and status-guarded."""
        updated = self._repo.mark_failed(action_id, org_id, error=error)
        if updated is None:
            raise PendingActionNotFound(action_id)
        if updated.get("goal_id"):
            self._safe_event(
                updated["goal_id"], "draft_failed", updated.get("approver") or "system",
                action_id, updated["action_type"], summary=error,
            )
        return updated

    def execute_approved(
        self, action_id: str, org_id: int, executor: Executor
    ) -> Dict[str, Any]:
        """
        Run an approved action via the supplied executor, then transition to
        executed (or failed on exception). The executor performs the actual
        side effect (post to Slack, send email, etc.); this keeps execution
        pluggable and the service free of channel imports.

        Returns the final action row.
        """
        action = self.get(action_id, org_id)
        if action["status"] != "approved":
            raise PendingActionNotFound(
                f"action {action_id} is {action['status']!r}, not approved"
            )
        try:
            result = executor(action)
        except Exception as exc:  # noqa: BLE001 — record any failure
            logger.exception("Executor failed for pending action %s", action_id)
            return self.mark_failed(action_id, org_id, error=str(exc))
        logger.info("Executed pending action %s: %s", action_id, (result or "")[:200])
        return self.mark_executed(action_id, org_id)

    # ------------------------------------------------------------- The gate

    def gate_or_execute(
        self,
        org_id: int,
        action_type: str,
        acting_identity: str,
        executor: Executor,
        target: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        preview: Optional[str] = None,
        instance_id: Optional[int] = None,
        goal_id: Optional[str] = None,
    ) -> GateResult:
        """
        The single decision point the dispatcher calls before any action.

        - FREE action  → execute immediately via `executor`, return the result.
        - GATED action → create a pending_action, notify a human, and return
          WITHOUT executing. The action runs later only after approval (see
          execute_approved).

        Default-deny: an unclassified action type is treated as gated.
        """
        if not self.requires_approval(action_type):
            result = executor({
                "org_id": org_id,
                "action_type": action_type,
                "target": target,
                "payload": payload or {},
            })
            return GateResult(gated=False, executed=True, result=result)

        action = self.create_pending_action(
            org_id=org_id,
            action_type=action_type,
            acting_identity=acting_identity,
            target=target,
            payload=payload,
            preview=preview,
            instance_id=instance_id,
            goal_id=goal_id,
        )
        notified = self._notify_pending(action)
        return GateResult(
            gated=True,
            executed=False,
            pending_action=action,
            notification_sent=notified,
        )

    # ------------------------------------------------------------- Internal

    def _notify_pending(self, action: Dict[str, Any]) -> bool:
        """Surface a newly-created pending action to a human for approval.

        Stub-by-default (logs) with a clear hook to the real notify channel —
        see _default_notifier's TODO. Channel is taken from the payload's
        notify_channel when present, else None (the default notifier logs)."""
        channel = (action.get("payload") or {}).get("notify_channel")
        message = (
            f"Approval needed: {action['action_type']}"
            + (f" → {action['target']}" if action.get("target") else "")
            + f"\n{action.get('preview') or '(no preview)'}"
            + f"\nApprove or reject pending action {action['id']}."
        )
        try:
            return bool(self._notify(channel, message))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Notifier raised for pending action %s: %s", action["id"], exc)
            return False

    def _safe_event(
        self,
        goal_id: str,
        action: str,
        actor: str,
        action_id: str,
        action_type: str,
        summary: Optional[str] = None,
    ) -> None:
        """Best-effort goal_events audit line for a decision/execution.
        Failures are logged, never raised — the pending_actions row is the
        durable record."""
        try:
            self._goal_repo.append_event(
                goal_id=goal_id,
                actor_type="user" if action in ("draft_approved", "draft_rejected") else "claw",
                action=action,
                result_summary=summary or f"{action_type} by {actor}",
                metadata={
                    "pending_action_id": str(action_id),
                    "action_type": action_type,
                    "actor": actor,
                },
            )
        except Exception:
            logger.exception(
                "Failed to record %s event for goal %s (pending_action %s)",
                action, goal_id, action_id,
            )
