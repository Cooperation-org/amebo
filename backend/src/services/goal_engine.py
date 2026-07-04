"""
Goal engine — state machine for goals.

Wraps GoalRepo with the rule that every state change ALSO appends an event
to the audit trail. The engine never decides *what* the claw should do or
*how* to pursue a goal — that is the dispatcher's job. The engine only
makes sure the lifecycle is recorded consistently.

Lifecycle:

    pending → active → completed        (one-shot goals)
              ↓     ↘
              ↓      pending (rearmed)   (recurring/cron goals: back to wait
              ↓                           for the next cron edge)
              failed | paused
              ↑
              active (via resume)

    Recurring (cron) goals re-arm active → pending after each dispatch cycle
    instead of completing, so the scheduler runs them again on the next cron
    edge. The dispatcher chooses complete() vs rearm() per the trigger type.

Concurrency model:
    activate() uses GoalRepo's row lock to ensure only one caller can move
    a goal from pending → active at a time. If two schedulers fire on the
    same goal, the second sees status != pending and returns None.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.db.repositories.goal_repo import GoalRepo

logger = logging.getLogger(__name__)


class GoalNotFoundError(LookupError):
    pass


class InvalidTransitionError(RuntimeError):
    pass


# Allowed transitions. Keys are starting status; values are statuses that
# are valid to move to from there. The action label that gets recorded in
# the event log lives alongside.
_TRANSITIONS = {
    "pending":   {"active": "activated", "paused": "paused"},
    "active":    {"completed": "completed", "failed": "failed", "paused": "paused",
                  "pending": "rearmed", "waiting_user": "question_asked"},
    "paused":    {"active": "resumed", "pending": "reset"},
    "waiting_user": {"pending": "user_answered", "failed": "failed", "paused": "paused"},
    "completed": {},  # terminal
    "failed":    {},  # terminal
}


class GoalEngine:
    """Stateless orchestration over GoalRepo. Safe to instantiate per call."""

    def __init__(self, repo: Optional[GoalRepo] = None):
        self._repo = repo or GoalRepo()

    # ------------------------------------------------------------ Lookups

    def get(self, goal_id: str) -> Dict[str, Any]:
        goal = self._repo.get(goal_id)
        if goal is None:
            raise GoalNotFoundError(goal_id)
        return goal

    def pending_for_org(self, org_id: int) -> List[Dict[str, Any]]:
        return self._repo.list_pending(org_id=org_id)

    def list_for_org(
        self, org_id: int, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        return self._repo.list_for_org(org_id, status=status)

    def events(self, goal_id: str) -> List[Dict[str, Any]]:
        # Verify goal exists so callers get a clear error.
        self.get(goal_id)
        return self._repo.list_events(goal_id)

    # ------------------------------------------------------------ Creation

    def create_goal(
        self,
        org_id: int,
        title: str,
        description: Optional[str] = None,
        target_criteria: Optional[Dict[str, Any]] = None,
        trigger_config: Optional[Dict[str, Any]] = None,
        notify_channel: Optional[str] = None,
        created_by_user_id: Optional[int] = None,
        assigned_to_user_id: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        goal = self._repo.create(
            org_id=org_id,
            title=title,
            description=description,
            target_criteria=target_criteria,
            trigger_config=trigger_config,
            notify_channel=notify_channel,
            created_by_user_id=created_by_user_id,
            assigned_to_user_id=assigned_to_user_id,
            config=config,
        )
        self._repo.append_event(
            goal["id"],
            actor_type="user" if created_by_user_id else "system",
            actor_user_id=created_by_user_id,
            action="created",
            result_summary=title,
        )
        return goal

    # ----------------------------------------------------------- Transitions

    def activate(
        self,
        goal_id: str,
        actor_type: str = "claw",
        actor_user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Move a pending goal to active. Returns the updated goal, or None if
        the goal was no longer pending (another worker beat us to it).
        """
        return self._transition(
            goal_id,
            to_status="active",
            actor_type=actor_type,
            actor_user_id=actor_user_id,
        )

    def complete(
        self,
        goal_id: str,
        summary: Optional[str] = None,
        actor_type: str = "claw",
        actor_user_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = self._transition(
            goal_id,
            to_status="completed",
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            summary=summary,
            metadata=metadata,
            require_existing=True,
        )
        assert result is not None  # require_existing=True raises if missing
        return result

    def rearm(
        self,
        goal_id: str,
        summary: Optional[str] = None,
        actor_type: str = "claw",
        actor_user_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Re-arm a recurring goal after a dispatch cycle: move active → pending
        so the scheduler re-evaluates it on the next cron edge instead of
        retiring it. This bumps updated_at, which _cron_is_due uses as the
        watermark, so the goal waits for its next fire rather than running
        again immediately.

        One-shot goals use complete() instead and terminate. The dispatcher
        decides which path to take (see GoalDispatcher._is_recurring).
        """
        result = self._transition(
            goal_id,
            to_status="pending",
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            summary=summary,
            metadata=metadata,
            require_existing=True,
        )
        assert result is not None
        return result

    def delete_goal(self, goal_id: str, org_id: int) -> bool:
        """Hard-delete a claw (and its events via FK CASCADE). Returns
        True if a row was deleted. Org-scoped: rejects deletion of claws
        belonging to a different org by returning False (the repo level
        enforces this). Callers (routes, CLI, internal) decide their
        own policy on which status values they allow this on; the engine
        will delete any status."""
        return self._repo.delete(goal_id, org_id)

    def fail(
        self,
        goal_id: str,
        reason: Optional[str] = None,
        actor_type: str = "claw",
        actor_user_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = self._transition(
            goal_id,
            to_status="failed",
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            summary=reason,
            metadata=metadata,
            require_existing=True,
        )
        assert result is not None
        return result

    def pause(
        self,
        goal_id: str,
        actor_user_id: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = self._transition(
            goal_id,
            to_status="paused",
            actor_type="user",
            actor_user_id=actor_user_id,
            summary=reason,
            require_existing=True,
        )
        assert result is not None
        return result

    def resume(
        self,
        goal_id: str,
        actor_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Only valid from the 'paused' state. Use dispatch / activate for
        pending goals — resume specifically un-pauses a paused goal so the
        audit trail reads correctly.
        """
        goal = self._repo.get(goal_id)
        if goal is None:
            raise GoalNotFoundError(goal_id)
        if goal["status"] != "paused":
            raise InvalidTransitionError(
                f"resume requires paused state; goal {goal_id} is {goal['status']!r}"
            )
        result = self._transition(
            goal_id,
            to_status="active",
            actor_type="user",
            actor_user_id=actor_user_id,
            require_existing=True,
        )
        assert result is not None
        return result

    def await_user(
        self,
        goal_id: str,
        question: str,
        thread_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Pause an active goal to ask a human (WP12). active -> waiting_user,
        recording the question (action 'question_asked') + the thread to watch
        for the reply. The scheduler skips waiting_user goals."""
        result = self._transition(
            goal_id,
            to_status="waiting_user",
            actor_type="claw",
            summary=question,
            metadata={"thread_ref": thread_ref} if thread_ref else None,
            require_existing=True,
        )
        assert result is not None
        return result

    def answer(
        self,
        goal_id: str,
        answer: str,
        thread_ref: Optional[str] = None,
        actor_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Record a human's reply to a waiting goal (WP12). waiting_user ->
        pending (action 'user_answered'); carryover (WP11) delivers the answer to
        the next dispatch."""
        goal = self._repo.get(goal_id)
        if goal is None:
            raise GoalNotFoundError(goal_id)
        if goal["status"] != "waiting_user":
            raise InvalidTransitionError(
                f"answer requires waiting_user state; goal {goal_id} is {goal['status']!r}"
            )
        result = self._transition(
            goal_id,
            to_status="pending",
            actor_type="user",
            actor_user_id=actor_user_id,
            summary=answer,
            metadata={"thread_ref": thread_ref} if thread_ref else None,
            require_existing=True,
        )
        assert result is not None
        return result

    # ----------------------------------------------------------- Tool calls

    def record_tool_call(
        self,
        goal_id: str,
        tool_name: str,
        result_summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        actor_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Record a tool invocation in the audit trail; does NOT change status."""
        return self._repo.append_event(
            goal_id,
            actor_type="claw",
            actor_user_id=actor_user_id,
            action=f"tool_call:{tool_name}",
            result_summary=result_summary,
            metadata=metadata,
        )

    # -------------------------------------------------------------- Internal

    def _transition(
        self,
        goal_id: str,
        to_status: str,
        actor_type: str,
        actor_user_id: Optional[int] = None,
        summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        require_existing: bool = False,
    ) -> Optional[Dict[str, Any]]:
        goal = self._repo.get(goal_id)
        if goal is None:
            raise GoalNotFoundError(goal_id)

        current = goal["status"]
        allowed = _TRANSITIONS.get(current, {})
        if to_status not in allowed:
            if require_existing:
                raise InvalidTransitionError(
                    f"Cannot transition goal {goal_id} from {current!r} to {to_status!r}"
                )
            logger.debug(
                "Goal %s: refusing transition %s → %s (no longer eligible)",
                goal_id, current, to_status,
            )
            return None

        action = allowed[to_status]
        is_completion = to_status == "completed"

        updated = self._repo.set_status(goal_id, to_status, completed=is_completion)
        self._repo.append_event(
            goal_id,
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            action=action,
            result_summary=summary,
            metadata=metadata,
        )
        return updated
