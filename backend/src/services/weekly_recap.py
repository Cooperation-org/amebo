"""
Weekly goal recap (WP14, UC-12) — one digest of an org's live goals: what moved,
what's blocked, what needs a human. Built from the goals' goal_events (their
dispatch_summary carryover, WP11), NOT re-derived. The caller posts it through
the output gate on the org's configured day.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from src.db.repositories.goal_repo import GoalRepo

logger = logging.getLogger(__name__)

# Goals that are "live" this week (not terminal).
_LIVE_STATUSES = ("active", "pending", "waiting_user", "paused")


def _latest_progress(goal_repo: GoalRepo, goal_id: str) -> Optional[str]:
    try:
        events = goal_repo.list_events(goal_id)
    except Exception:
        return None
    for e in reversed(events or []):
        if e.get("action") in ("dispatch_summary", "user_answered", "question_asked"):
            s = (e.get("result_summary") or "").strip().replace("\n", " ")
            return s[:160] if s else None
    return None


def weekly_recap(org_id: int, goal_repo: Optional[GoalRepo] = None) -> str:
    """Build the recap digest for an org. Returns a short markdown string, or a
    'nothing active' line. Pure — the caller sends it through the output gate."""
    repo = goal_repo or GoalRepo()
    goals: List[Dict] = []
    for status in _LIVE_STATUSES:
        try:
            goals.extend(repo.list_for_org(org_id, status=status))
        except Exception:
            logger.exception("recap: list_for_org failed status=%s", status)

    if not goals:
        return "No active goals this week."

    # blocked = waiting on a human or paused (surface these first)
    blocked = [g for g in goals if g["status"] in ("waiting_user", "paused")]
    moving = [g for g in goals if g["status"] in ("active", "pending")]

    lines = [f"*This week's goals* ({len(goals)} live):"]
    if blocked:
        lines.append("\n⏳ *Needs you:*")
        for g in blocked:
            why = "waiting for your reply" if g["status"] == "waiting_user" else "paused"
            prog = _latest_progress(repo, g["id"])
            lines.append(f"  • {g['title']} — {why}" + (f" ({prog})" if prog else ""))
    if moving:
        lines.append("\n▶️ *In progress:*")
        for g in moving:
            prog = _latest_progress(repo, g["id"])
            lines.append(f"  • {g['title']}" + (f" — {prog}" if prog else ""))
    return "\n".join(lines)
