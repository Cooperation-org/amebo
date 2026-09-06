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
    POST   /api/goals/{goal_id}/answer  answer a waiting_user goal
    POST   /api/goals/{goal_id}/dispatch-now  manually trigger one tick

No PATCH for full updates yet — keep the surface minimal. We can add an
explicit "update title/description" endpoint when there is a real need.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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
    config: Optional[Dict[str, Any]] = None
    # Who carries this goal. Nullable: a goal is always an org's and only
    # optionally a person's. Exposed so a client can tell mine from ours
    # without a second call — the column has always been on the row.
    assigned_to_user_id: Optional[int] = None
    # The question this goal is holding for a person, when status is
    # waiting_user. Read off the last 'question_asked' event, never stored twice.
    question: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class GoalAnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=20000)


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
        config=goal.get("config"),
        assigned_to_user_id=goal.get("assigned_to_user_id"),
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
    waiting = [str(g["id"]) for g in goals if g.get("status") == "waiting_user"]
    questions: Dict[str, str] = {}
    if waiting:
        try:
            from src.db.repositories.goal_repo import GoalRepo
            questions = GoalRepo().last_questions(waiting)
        except Exception as exc:  # noqa: BLE001 - the list stands without them
            logger.warning("goals: questions unreadable: %s", exc)
    out = []
    for g in goals:
        r = _to_goal_response(g)
        r.question = questions.get(str(g["id"]))
        out.append(r)
    return out


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


class GoalProgress(BaseModel):
    id: str
    title: str
    status: str
    state: str                      # waiting | moving | stalled | paused | done
    question: Optional[str] = None
    owner: Optional[str] = None
    org_label: Optional[str] = None
    kind: Optional[str] = None
    tasks_open: int = 0
    tasks_done: int = 0
    tasks_url: Optional[str] = None
    last_activity: Optional[datetime] = None
    quiet_days: Optional[int] = None
    trigger: Optional[str] = None


STALLED_AFTER_DAYS = 7


def _goal_tag(goal_id: str) -> str:
    return f"goal:{str(goal_id)[:8]}"


@router.get("/progress", response_model=List[GoalProgress])
async def goals_progress(client: dict = Depends(get_service_or_user)):
    """Every live goal with where it stands: its state as a traffic light, the
    question it holds, its tasks done and open (stories tagged goal:<id8> or
    named in its description), and how long since anything happened.

    One Taiga read for the tag search, one for the events; a Taiga outage
    loses the task counts and nothing else."""
    from src.services.work_list import goal_task_refs
    engine = _get_engine()
    goals = [g for g in engine.list_for_org(client["org_id"])
             if g.get("status") in ("waiting_user", "pending", "active", "paused")]
    if not goals:
        return []
    ids = [str(g["id"]) for g in goals]
    repo = GoalRepo()
    questions: Dict[str, str] = {}
    activity: Dict[str, datetime] = {}
    try:
        questions = repo.last_questions([i for i in ids])
        activity = repo.last_activity(ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("goals/progress: events unreadable: %s", exc)

    counts: Dict[str, Dict[str, int]] = {i: {"open": 0, "done": 0} for i in ids}
    marten = os.getenv("MARTEN_URL", "https://marten.linkedtrust.us").rstrip("/")
    try:
        from src.services.work_list_taiga import TaigaStoryStore
        store = TaigaStoryStore()
        store.prime_slugs()
        tagged = store.stories_tagged([_goal_tag(i) for i in ids])
        seen: Dict[str, set] = {i: set() for i in ids}
        for story in tagged:
            closed = bool((story.get("status_extra_info") or {}).get("is_closed"))
            for t in (story.get("tags") or []):
                name = t[0] if isinstance(t, (list, tuple)) else t
                for i in ids:
                    if name == _goal_tag(i) and story.get("id") not in seen[i]:
                        seen[i].add(story.get("id"))
                        counts[i]["done" if closed else "open"] += 1
        for g in goals:
            for slug, ref in goal_task_refs(g):
                try:
                    story = store.story(slug, ref)
                except Exception:  # noqa: BLE001
                    story = None
                if story and story.get("id") not in seen[str(g["id"])]:
                    seen[str(g["id"])].add(story.get("id"))
                    closed = bool((story.get("status_extra_info") or {}).get("is_closed"))
                    counts[str(g["id"])]["done" if closed else "open"] += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("goals/progress: taiga unreadable: %s", exc)

    now = datetime.now(tz=None)
    out: List[GoalProgress] = []
    for g in goals:
        gid = str(g["id"])
        cfg = g.get("config") or {}
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:  # noqa: BLE001
                cfg = {}
        last = activity.get(gid) or g.get("updated_at")
        quiet = None
        if last:
            try:
                quiet = max(0, (now - last.replace(tzinfo=None)).days)
            except Exception:  # noqa: BLE001
                quiet = None
        status = g.get("status")
        if status == "waiting_user":
            state = "waiting"
        elif status == "paused":
            state = "paused"
        elif quiet is not None and quiet > STALLED_AFTER_DAYS and counts[gid]["open"] == 0 and counts[gid]["done"] == 0:
            state = "stalled"
        elif quiet is not None and quiet > STALLED_AFTER_DAYS * 2:
            state = "stalled"
        else:
            state = "moving"
        out.append(GoalProgress(
            id=gid, title=g["title"], status=status, state=state,
            question=questions.get(gid), owner=cfg.get("owner"),
            org_label=cfg.get("org_label"), kind=cfg.get("kind"),
            tasks_open=counts[gid]["open"], tasks_done=counts[gid]["done"],
            tasks_url=f"{marten}/board?tag={_goal_tag(gid)}",
            last_activity=last, quiet_days=quiet,
            trigger=(g.get("trigger_config") or {}).get("type"),
        ))
    order = {"waiting": 0, "stalled": 1, "moving": 2, "paused": 3}
    out.sort(key=lambda p: (order.get(p.state, 9), p.title))
    return out


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


def _dispatch_in_background(goal_id: str) -> None:
    """Run one dispatch after an answer lands, so the answer immediately
    becomes work instead of waiting for a scheduler edge or a human nudge.
    Errors are logged, never surfaced — the answer itself is already saved."""
    try:
        from src.services.llm_client import get_llm_client
        anthropic_client = get_llm_client()
        result = GoalDispatcher(anthropic_client=anthropic_client).dispatch(goal_id)
        logger.info("Post-answer dispatch for %s finished: %s",
                    goal_id, result.status)
    except Exception:
        logger.exception("Post-answer dispatch for %s raised", goal_id)


@router.post("/{goal_id}/answer", response_model=GoalResponse)
async def answer_goal(
    goal_id: str,
    req: GoalAnswerRequest,
    background_tasks: BackgroundTasks,
    client: dict = Depends(get_service_or_user),
):
    """Record a human answer on a waiting_user goal (WP12). The goal re-arms
    to pending, the answer rides the carryover, and one dispatch is kicked
    off in the background so the answer is acted on right away."""
    engine = _get_engine()
    _load_or_404(engine, goal_id, client["org_id"])
    try:
        answered = engine.answer(
            goal_id,
            answer=req.answer,
            actor_user_id=client.get("user_id"),
        )
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    logger.info("Goal answered: id=%s org=%s", goal_id, client["org_id"])
    background_tasks.add_task(_dispatch_in_background, goal_id)
    return _to_goal_response(answered)


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
    from src.services.llm_client import get_llm_client
    anthropic_client = get_llm_client()

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
