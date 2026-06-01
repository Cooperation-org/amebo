"""
Amebo Digest API — surface for the <amebo-digest> embed component.

Returns a structured "what should I look at today?" summary built from:
  - hot tags via BindingRepo
  - open goals (active + pending) via GoalRepo
  - (TODO) recent thread activity once ThreadRepo has a per-org-recent helper

Response shape (stable contract — the embed component depends on it):

    {
      "heading": str,                       # e.g. "Today"
      "items": [
        {
          "text":  str,                     # one-line surface text
          "kind":  "hot" | "goal" | "recent" | "system",
          "ref":   str | None               # optional URI back to the source
        }
      ],
      "v": int                              # schema version, currently 0
    }
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from src.api.middleware.auth import get_current_user
from src.db.repositories.binding_repo import BindingRepo
from src.db.repositories.goal_repo import GoalRepo
from src.db.repositories.thread_repo import ThreadRepo


router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_HOT = 5
_MAX_GOALS = 5
_MAX_RECENT = 3
_MAX_ITEMS = 10


@router.get("")
@router.get("/")
async def get_digest(current_user: dict = Depends(get_current_user)):
    """Return a digest summary for the authenticated user's org."""
    org_id = current_user.get("org_id")
    items: List[Dict[str, Any]] = []

    if org_id:
        items.extend(_hot_items(org_id))
        items.extend(_goal_items(org_id))
        items.extend(_recent_thread_items(org_id))

    if not items:
        items = [{
            "text": "No hot tags, open goals, or recent activity yet.",
            "kind": "system",
            "ref": None,
        }]

    return {
        "heading": "Today",
        "items": items[:_MAX_ITEMS],
        "v": 0,
    }


def _hot_items(org_id: int) -> List[Dict[str, Any]]:
    try:
        tags = BindingRepo(org_id=org_id).get_hot_tags()
    except Exception:
        logger.exception("digest: hot tag fetch failed")
        return []
    out: List[Dict[str, Any]] = []
    for t in tags[:_MAX_HOT]:
        name = t.get("name")
        scope = t.get("scope")
        if not name:
            continue
        out.append({
            "text": name,
            "kind": "hot",
            "ref": f"abra:hot/{scope}/{name}" if scope else f"abra:hot/{name}",
        })
    return out


def _recent_thread_items(org_id: int) -> List[Dict[str, Any]]:
    try:
        threads = ThreadRepo().recent_for_org(org_id=org_id, limit=_MAX_RECENT)
    except Exception:
        logger.exception("digest: recent threads fetch failed")
        return []
    out: List[Dict[str, Any]] = []
    for t in threads:
        tid = t.get("id")
        if tid is None:
            continue
        title = t.get("title") or t.get("source_ref") or f"thread {tid}"
        out.append({
            "text": str(title),
            "kind": "recent",
            "ref": f"amebo:thread/{tid}",
        })
    return out


def _goal_items(org_id: int) -> List[Dict[str, Any]]:
    repo = GoalRepo()
    rows: List[Dict[str, Any]] = []
    for status in ("active", "pending"):
        try:
            rows.extend(repo.list_for_org(org_id=org_id, status=status, limit=_MAX_GOALS))
        except Exception:
            logger.exception("digest: goal fetch failed for status=%s", status)
    out: List[Dict[str, Any]] = []
    for g in rows[:_MAX_GOALS]:
        gid = g.get("goal_id") or g.get("id")
        title = g.get("title") or "(untitled goal)"
        if gid is None:
            continue
        out.append({
            "text": title,
            "kind": "goal",
            "ref": f"amebo:goal/{gid}",
        })
    return out
