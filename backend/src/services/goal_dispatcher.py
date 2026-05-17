"""
Goal dispatcher — the claw.

Thin wrapper that pursues a single goal using amebo's existing model + tool
plumbing. Stays out of the core Q&A path. Disabling the goal subsystem is
just a config flag elsewhere; the dispatcher is only invoked from the
scheduler when that flag is enabled.

Responsibilities:
- Load the goal + the org's instance + the org's semantic context (vision,
  values, current context) from abra.
- Frame the task for Claude as "pursue this goal" rather than "answer a
  question".
- Run a bounded agentic loop, recording each tool call as a goal_event.
- On success / failure, transition the goal through GoalEngine (which also
  writes the appropriate event).
- Post a notification to the configured channel.

Boundaries:
- Channel adapters (slack/email/etc.) are pluggable. The dispatcher never
  imports a channel directly — it asks a registry for the right adapter.
- The Anthropic client is injected so tests can replace it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.db.repositories.binding_repo import BindingRepo
from src.db.repositories.goal_repo import GoalRepo
from src.db.repositories.instance_repo import InstanceRepo
from src.services.goal_engine import (
    GoalEngine, GoalNotFoundError, InvalidTransitionError,
)

logger = logging.getLogger(__name__)


# Bound the agentic loop so a misbehaving model cannot run forever.
MAX_TOOL_ROUNDS = 5
DEFAULT_MAX_TOKENS = 2000


@dataclass
class DispatchResult:
    """Outcome of dispatching a single goal."""

    goal_id: str
    status: str                    # 'completed' | 'failed' | 'skipped'
    summary: Optional[str] = None
    tool_rounds: int = 0
    notification_sent: bool = False
    error: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


# A notifier takes (channel_spec, message_text) and returns True on success.
Notifier = Callable[[str, str], bool]


def _default_notifier(channel: str, message: str) -> bool:
    """
    Fallback notifier: log it. Channel-specific adapters (Slack, email,
    etc.) plug in at GoalDispatcher construction time.
    """
    logger.info("[goal-notify] %s :: %s", channel, message)
    return True


class GoalDispatcher:
    """
    A dispatcher instance is cheap. It holds repositories and an optional
    Anthropic client + notifier. All long-lived resources are pooled at the
    DB connection layer, not here.
    """

    def __init__(
        self,
        goal_repo: Optional[GoalRepo] = None,
        engine: Optional[GoalEngine] = None,
        instance_repo: Optional[InstanceRepo] = None,
        anthropic_client: Optional[Any] = None,
        notifier: Optional[Notifier] = None,
    ):
        self._goal_repo = goal_repo or GoalRepo()
        self._engine = engine or GoalEngine(self._goal_repo)
        self._instance_repo = instance_repo or InstanceRepo()
        self._client = anthropic_client          # may be None in tests
        self._notify = notifier or _default_notifier

    # ----------------------------------------------------------------- API

    def dispatch(self, goal_id: str) -> DispatchResult:
        """
        Pursue a single goal end-to-end. Idempotent against terminal states:
        re-dispatching a completed goal returns a 'skipped' result.
        """
        try:
            goal = self._engine.get(goal_id)
        except GoalNotFoundError:
            return DispatchResult(goal_id=goal_id, status="failed",
                                  error=f"Goal not found: {goal_id}")

        if goal["status"] in ("completed", "failed"):
            return DispatchResult(goal_id=goal_id, status="skipped",
                                  summary=f"already {goal['status']}")

        # Activate (idempotent — returns None if someone beat us to it).
        if goal["status"] == "pending":
            activated = self._engine.activate(goal_id, actor_type="claw")
            if activated is None:
                # Another worker already picked it up.
                return DispatchResult(goal_id=goal_id, status="skipped",
                                      summary="already activated by another worker")

        # Build context and pursue.
        try:
            org_context = self._load_org_context(goal["org_id"])
            instance = self._load_instance(goal["org_id"])
            summary, tool_calls = self._pursue(goal, instance, org_context)
        except Exception as exc:
            logger.exception("Goal %s dispatch raised", goal_id)
            try:
                self._engine.fail(goal_id, reason=str(exc))
            except InvalidTransitionError:
                pass  # goal is already terminal
            return DispatchResult(goal_id=goal_id, status="failed", error=str(exc))

        # Mark complete and notify.
        self._engine.complete(goal_id, summary=summary)
        notification_sent = self._maybe_notify(goal, summary)

        return DispatchResult(
            goal_id=goal_id,
            status="completed",
            summary=summary,
            tool_rounds=len(tool_calls),
            tool_calls=tool_calls,
            notification_sent=notification_sent,
        )

    # ------------------------------------------------------------- Context

    def _load_instance(self, org_id: int) -> Optional[Dict[str, Any]]:
        """First instance for this org, if any. Returns None when missing."""
        # Stable lookup via a one-off query rather than adding a new repo
        # method just for this. If we need this elsewhere, lift it up.
        from src.db.connection import DatabaseConnection
        from psycopg2 import extras as pg_extras

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=pg_extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM instances WHERE org_id = %s "
                    "ORDER BY created_at ASC LIMIT 1",
                    (org_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def _load_org_context(self, org_id: int) -> Dict[str, List[str]]:
        """
        Load the org's semantic context from abra: vision, values, and any
        currently-hot context. Returned as plain strings per category so
        the dispatcher can decide how to compose them into the prompt.

        Keys returned:
            vision      — list of vision content blobs
            values      — list of values content blobs
            current     — list of currently hot context content blobs

        Empty lists when nothing is stored, so callers can compose without
        special-casing presence.
        """
        repo = BindingRepo(org_id=org_id)
        out: Dict[str, List[str]] = {"vision": [], "values": [], "current": []}

        for key, query in (
            ("vision", "vision"),
            ("values", "values"),
            ("current", "current context"),
        ):
            try:
                results = repo.search_content(query, limit=3) or []
            except Exception as exc:
                # A missing or unreachable knowledge store should not break
                # the dispatcher — the goal can still be pursued without
                # context, just less aligned.
                logger.warning("Failed to load %s context for org %s: %s",
                               key, org_id, exc)
                continue

            for r in results:
                content = (r.get("content") or "").strip()
                if content:
                    out[key].append(content)

        return out

    # ----------------------------------------------------------- Pursuit

    def _pursue(
        self,
        goal: Dict[str, Any],
        instance: Optional[Dict[str, Any]],
        org_context: Dict[str, List[str]],
    ) -> tuple[str, List[Dict[str, Any]]]:
        """
        Run the agentic loop. Returns (summary_text, tool_calls).

        If no Anthropic client is configured, this returns a deterministic
        stub summary so the engine path is still exercisable in dev and
        tests without burning API tokens.
        """
        system_prompt = self._build_system_prompt(instance, org_context)
        user_prompt = self._build_user_prompt(goal)

        if self._client is None:
            return (
                f"[no-llm] Goal pursued in offline mode: {goal['title']}",
                [],
            )

        return self._run_agentic_loop(
            goal_id=goal["id"],
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    def _build_system_prompt(
        self,
        instance: Optional[Dict[str, Any]],
        org_context: Dict[str, List[str]],
    ) -> str:
        parts: List[str] = []

        if instance and instance.get("identity_prompt"):
            parts.append(instance["identity_prompt"])
        else:
            parts.append(
                "You are acting on behalf of an org to pursue an explicit goal. "
                "Stay aligned with the org's vision and values."
            )

        if org_context["vision"]:
            parts.append("## Vision\n" + "\n\n".join(org_context["vision"]))
        if org_context["values"]:
            parts.append("## Values\n" + "\n\n".join(org_context["values"]))
        if org_context["current"]:
            parts.append("## Current context\n" + "\n\n".join(org_context["current"]))

        parts.append(
            "When you are confident the goal is achieved, respond with a "
            "concise summary of what was accomplished. If you cannot achieve "
            "it, respond with a brief explanation of why."
        )
        return "\n\n".join(parts)

    def _build_user_prompt(self, goal: Dict[str, Any]) -> str:
        lines = [f"# Goal: {goal['title']}"]
        if goal.get("description"):
            lines.append(goal["description"])
        criteria = goal.get("target_criteria")
        if criteria:
            lines.append("## Target criteria\n" + str(criteria))
        return "\n\n".join(lines)

    def _run_agentic_loop(
        self,
        goal_id: str,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """
        Minimal agentic loop. v1: no tools wired in yet — the loop just
        does a single Claude call. Tool integration plugs in here later;
        each tool call gets recorded as a goal_event.
        """
        messages = [{"role": "user", "content": user_prompt}]
        response = self._client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=DEFAULT_MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        )

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        if not text.strip():
            text = "(model returned no text)"

        return text.strip(), []

    # ------------------------------------------------------------- Notify

    def _maybe_notify(self, goal: Dict[str, Any], summary: Optional[str]) -> bool:
        channel = goal.get("notify_channel")
        if not channel:
            return False

        message = (
            f"Goal completed: {goal['title']}\n\n"
            f"{summary or '(no summary)'}"
        )
        try:
            return bool(self._notify(channel, message))
        except Exception as exc:
            logger.warning("Notifier raised for goal %s: %s", goal["id"], exc)
            return False
