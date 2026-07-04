"""
Goal-control tools available to a claw while pursuing a goal.

ask_user (WP12): pause the goal to ask a human one short question and resume on
their reply. It transitions the goal to waiting_user (the scheduler then skips
it); the dispatcher posts the question and, when a reply lands on the thread,
records the answer and re-arms the goal to pending (carryover delivers it).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def ask_user_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    goal_id = (context or {}).get("goal_id")
    if not goal_id:
        return ("Error: ask_user only works while pursuing a goal (there is no "
                "goal to pause here).")
    question = (tool_input.get("question") or "").strip()
    if not question:
        return "Error: question is required (ask ONE short question)."
    from src.services.goal_engine import GoalEngine, InvalidTransitionError
    from src.db.repositories.goal_repo import GoalRepo
    thread_ref = (context or {}).get("thread_ref")
    try:
        GoalEngine(GoalRepo()).await_user(goal_id, question, thread_ref=thread_ref)
    except InvalidTransitionError as exc:
        return f"Error: cannot pause to ask right now ({exc})."
    except Exception as exc:
        logger.exception("ask_user failed for goal %s", goal_id)
        return f"Error: could not pause to ask: {exc}"
    return ("[WAITING FOR THE USER] Your question is queued and the goal is "
            "paused until they reply. STOP now — take no further steps this "
            f"dispatch. Question: {question}")


ASK_USER_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "ONE short question for the human. A few sentences max.",
        },
    },
    "required": ["question"],
}
