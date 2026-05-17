"""
Goal-introspection tools — let the model answer "what goals do we have"
and "what has the claw done on X" using real data, not hallucinations.

These tools are scoped to the calling org via `context["org_id"]`. Without
an org_id in context, they return an error rather than leaking other orgs'
goals.
"""

from __future__ import annotations

from typing import Any, Dict

from src.db.repositories.goal_repo import GoalRepo, VALID_STATUSES
from src.services.goal_engine import GoalEngine, GoalNotFoundError


# ---------------------------------------------------------------------------
# list_goals
# ---------------------------------------------------------------------------


def list_goals(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    org_id = context.get("org_id")
    if not org_id:
        return "Error: no org context available — cannot list goals."

    status = tool_input.get("status")
    if status and status not in VALID_STATUSES:
        return f"Error: invalid status. Allowed: {sorted(VALID_STATUSES)}."

    limit = int(tool_input.get("limit") or 25)
    limit = max(1, min(limit, 100))

    repo = GoalRepo()
    goals = repo.list_for_org(org_id, status=status)[:limit]
    if not goals:
        scope = f" with status {status!r}" if status else ""
        return f"No goals{scope} for this org."

    lines = []
    for g in goals:
        trigger = (g.get("trigger_config") or {}).get("type", "default")
        notify = g.get("notify_channel") or "—"
        line = (
            f"- [{g['status']}] {g['title']}  "
            f"(id={g['id']}, trigger={trigger}, notify={notify}, "
            f"created={g['created_at'].isoformat()})"
        )
        if g.get("description"):
            desc = g["description"]
            if len(desc) > 200:
                desc = desc[:200] + "..."
            line += f"\n    {desc}"
        lines.append(line)
    return "\n".join(lines)


LIST_GOALS_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "description": (
                "Optional status filter. One of: pending, active, completed, "
                "failed, paused. Omit to list all."
            ),
        },
        "limit": {
            "type": "integer",
            "description": "Max number of goals to return (default 25, max 100).",
            "default": 25,
        },
    },
    "required": [],
}


# ---------------------------------------------------------------------------
# get_goal_events
# ---------------------------------------------------------------------------


def get_goal_events(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    org_id = context.get("org_id")
    if not org_id:
        return "Error: no org context available."

    goal_id = (tool_input.get("goal_id") or "").strip()
    if not goal_id:
        return "Error: goal_id is required."

    engine = GoalEngine(GoalRepo())
    try:
        goal = engine.get(goal_id)
    except GoalNotFoundError:
        return f"No goal found with id {goal_id!r}."

    if goal["org_id"] != org_id:
        # Same response as not-found — never leak cross-org existence.
        return f"No goal found with id {goal_id!r}."

    events = engine.events(goal_id)
    header = (
        f"Goal: {goal['title']}\n"
        f"Status: {goal['status']}\n"
        f"Created: {goal['created_at'].isoformat()}\n"
    )
    if goal.get("completed_at"):
        header += f"Completed: {goal['completed_at'].isoformat()}\n"

    if not events:
        return header + "\nNo events yet."

    body_lines = ["", "Audit trail:"]
    for e in events:
        when = e["created_at"].isoformat()
        actor = e["actor_type"]
        action = e["action"]
        summary = e.get("result_summary") or ""
        line = f"  {e['step_index']:>3}. [{when}] ({actor}) {action}"
        if summary:
            if len(summary) > 300:
                summary = summary[:300] + "..."
            line += f" — {summary}"
        body_lines.append(line)

    return header + "\n".join(body_lines)


GET_GOAL_EVENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "goal_id": {
            "type": "string",
            "description": "UUID of the goal to inspect.",
        },
    },
    "required": ["goal_id"],
}
