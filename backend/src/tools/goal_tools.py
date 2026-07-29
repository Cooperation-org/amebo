"""
Goal-control tools available to a claw while pursuing a goal.

goal_done: say the goal's aim is actually met, so it retires instead of coming
back on its schedule. Nothing else in the system judges completion — a dispatch
finishing a cycle is not the same as the goal being achieved — so a recurring
goal keeps returning on its cron until this is called (or a human marks it done
from the list, which is the same transition).

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


def goal_done_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Retire the goal: its aim is met.

    A dispatch ending is not evidence the goal was achieved, so this is the only
    thing that says so from the claw's side. Until it is called, a goal with a
    cron keeps coming back on schedule — which is what "keep working it until it
    is done" means.
    """
    goal_id = (context or {}).get("goal_id")
    if not goal_id:
        return ("Error: goal_done only works while pursuing a goal (there is no "
                "goal to finish here).")
    reason = (tool_input.get("reason") or "").strip()
    if not reason:
        return ("Error: reason is required — say what was actually achieved, so "
                "a person reading the log later knows why this retired.")
    from src.services.goal_engine import GoalEngine, InvalidTransitionError
    from src.db.repositories.goal_repo import GoalRepo
    try:
        GoalEngine(GoalRepo()).complete(goal_id, summary=reason)
    except InvalidTransitionError as exc:
        return f"Error: cannot finish this goal right now ({exc})."
    except Exception as exc:
        logger.exception("goal_done failed for goal %s", goal_id)
        return f"Error: could not finish the goal: {exc}"
    return ("[GOAL DONE] Retired, and it will not come back on its schedule. "
            f"Recorded: {reason}")


GOAL_DONE_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {
            "type": "string",
            "description": (
                "What was actually achieved, in one or two plain sentences. "
                "Not a description of the work you did — the outcome."
            ),
        },
    },
    "required": ["reason"],
}
