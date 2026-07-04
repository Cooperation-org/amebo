"""
Goals REST API.

Authenticates via either an X-API-Key (service-to-service) or a Bearer
JWT (per-user, via the view-server proxy). The authenticated client's
org_id is the authority for every operation — callers never specify
org_id directly. Goals belonging to other orgs are invisible regardless
of which auth path was used.

Endpoints:
    GET    /api/goals/                  list goals for the authenticated org
    POST   /api/goals/                  create a goal
    GET    /api/goals/{goal_id}         goal detail
    GET    /api/goals/{goal_id}/events  audit-trail events
    POST   /api/goals/{goal_id}/pause   pause a goal
    POST   /api/goals/{goal_id}/resume  resume a paused goal
    POST   /api/goals/{goal_id}/dispatch-now  manually trigger one tick

No PATCH for full updates yet — keep the surface minimal. We can add an
explicit "update title/description" endpoint when there is a real need.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.middleware.auth import get_service_or_user
from src.db.repositories.goal_repo import GoalRepo, VALID_STATUSES
from src.services.goal_dispatcher import GoalDispatcher
from src.services.goal_engine import (
    GoalEngine, GoalNotFoundError, InvalidTransitionError,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class GoalCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    target_criteria: Optional[Dict[str, Any]] = None
    trigger_config: Optional[Dict[str, Any]] = None
    notify_channel: Optional[str] = Field(None, max_length=255)
    config: Optional[Dict[str, Any]] = None


class GoalResponse(BaseModel):
    id: str
    org_id: int
    title: str
    description: Optional[str] = None
    target_criteria: Optional[Dict[str, Any]] = None
    status: str
    trigger_config: Optional[Dict[str, Any]] = None
    notify_channel: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class GoalEventResponse(BaseModel):
    id: str
    goal_id: str
    step_index: int
    actor_type: str
    action: str
    result_summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime


class ToolCallSummary(BaseModel):
    """One tool call the claw made during a dispatch — the play-by-play a human
    needs to see what the claw actually did, including held-for-approval steps."""

    name: str
    ok: bool
    summary: Optional[str] = None


class DispatchResultResponse(BaseModel):
    goal_id: str
    status: str
    summary: Optional[str] = None
    error: Optional[str] = None
    notification_sent: bool
    # The per-step trail the dispatcher already builds. Surfaced so a manual run
    # shows what happened even when the final summary is thin/empty.
    tool_rounds: int = 0
    tool_calls: List[ToolCallSummary] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_engine() -> GoalEngine:
    return GoalEngine(GoalRepo())


def _to_goal_response(goal: Dict[str, Any]) -> GoalResponse:
    return GoalResponse(
        id=str(goal["id"]),
        org_id=goal["org_id"],
        title=goal["title"],
        description=goal.get("description"),
        target_criteria=goal.get("target_criteria"),
        status=goal["status"],
        trigger_config=goal.get("trigger_config"),
        notify_channel=goal.get("notify_channel"),
        created_at=goal["created_at"],
        updated_at=goal["updated_at"],
        completed_at=goal.get("completed_at"),
    )


def _load_or_404(engine: GoalEngine, goal_id: str, org_id: int) -> Dict[str, Any]:
    """Fetch a goal and verify it belongs to the calling org."""
    try:
        goal = engine.get(goal_id)
    except GoalNotFoundError:
        raise HTTPException(status_code=404, detail="Goal not found")
    if goal["org_id"] != org_id:
        # Don't leak existence — same 404 as "not found".
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_model=List[GoalResponse])
async def list_goals(
    status: Optional[str] = None,
    limit: int = 100,
    client: dict = Depends(get_service_or_user),
):
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Allowed: {sorted(VALID_STATUSES)}",
        )
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be 1..500")

    engine = _get_engine()
    goals = engine.list_for_org(client["org_id"], status=status)[:limit]
    return [_to_goal_response(g) for g in goals]


@router.post("/", response_model=GoalResponse, status_code=201)
async def create_goal(
    req: GoalCreateRequest,
    client: dict = Depends(get_service_or_user),
):
    engine = _get_engine()
    goal = engine.create_goal(
        org_id=client["org_id"],
        title=req.title,
        description=req.description,
        target_criteria=req.target_criteria,
        trigger_config=req.trigger_config,
        notify_channel=req.notify_channel,
        config=req.config,
    )
    logger.info("Goal created: id=%s org=%s key=%s",
                goal["id"], client["org_id"], client["key_name"])
    return _to_goal_response(goal)


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    goal_id: str,
    client: dict = Depends(get_service_or_user),
):
    engine = _get_engine()
    goal = _load_or_404(engine, goal_id, client["org_id"])
    return _to_goal_response(goal)


@router.get("/{goal_id}/events", response_model=List[GoalEventResponse])
async def list_goal_events(
    goal_id: str,
    client: dict = Depends(get_service_or_user),
):
    engine = _get_engine()
    _load_or_404(engine, goal_id, client["org_id"])  # org-scoped existence check
    events = engine.events(goal_id)
    return [
        GoalEventResponse(
            id=str(e["id"]),
            goal_id=str(e["goal_id"]),
            step_index=e["step_index"],
            actor_type=e["actor_type"],
            action=e["action"],
            result_summary=e.get("result_summary"),
            metadata=e.get("metadata"),
            created_at=e["created_at"],
        )
        for e in events
    ]


@router.post("/{goal_id}/pause", response_model=GoalResponse)
async def pause_goal(
    goal_id: str,
    client: dict = Depends(get_service_or_user),
):
    engine = _get_engine()
    _load_or_404(engine, goal_id, client["org_id"])
    try:
        paused = engine.pause(goal_id)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _to_goal_response(paused)


@router.post("/{goal_id}/resume", response_model=GoalResponse)
async def resume_goal(
    goal_id: str,
    client: dict = Depends(get_service_or_user),
):
    engine = _get_engine()
    _load_or_404(engine, goal_id, client["org_id"])
    try:
        resumed = engine.resume(goal_id)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _to_goal_response(resumed)


@router.post("/{goal_id}/dispatch-now", response_model=DispatchResultResponse)
async def dispatch_goal_now(
    goal_id: str,
    client: dict = Depends(get_service_or_user),
):
    """
    Manually trigger dispatch for this goal, bypassing the periodic
    scheduler. Useful for testing and for manual-trigger goals.
    """
    engine = _get_engine()
    _load_or_404(engine, goal_id, client["org_id"])

    # Same client sourcing as QAService: without it every dispatch silently
    # ran the [no-llm] stub (found live 2026-07-04 running the Dana story).
    anthropic_client = None
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        from anthropic import Anthropic
        anthropic_client = Anthropic(api_key=api_key)

    dispatcher = GoalDispatcher(anthropic_client=anthropic_client)
    result = dispatcher.dispatch(goal_id)
    return DispatchResultResponse(
        goal_id=result.goal_id,
        status=result.status,
        summary=result.summary,
        error=result.error,
        notification_sent=result.notification_sent,
        tool_rounds=result.tool_rounds,
        tool_calls=[
            ToolCallSummary(
                name=tc.get("name", "?"),
                ok=bool(tc.get("ok", False)),
                summary=tc.get("summary"),
            )
            for tc in (result.tool_calls or [])
        ],
    )


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: str,
    client: dict = Depends(get_service_or_user),
):
    """Hard-delete a claw and its event history. Org-scoped: the
    underlying engine call rejects if the claw does not belong to the
    caller's org.

    Per Golda 2026-06-05: deletion is appropriate for completed claws
    that will not run again. The web component only surfaces this
    control on terminal-status rows. Other callers (CLI, future admin)
    can use it on any status; that is by design — the engine is the
    enforcer of policy, not the route layer.
    """
    engine = _get_engine()
    _load_or_404(engine, goal_id, client["org_id"])
    engine.delete_goal(goal_id, org_id=client["org_id"])
    logger.info("Goal deleted: id=%s org=%s key=%s",
                goal_id, client["org_id"], client["key_name"])
    return None
