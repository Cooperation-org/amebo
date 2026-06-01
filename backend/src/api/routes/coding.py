"""
Coding-agent HTTP route.

A thin channel into the coding orchestrator: accept a message, resolve/queue it
against its intention thread, and (by default) run it synchronously through the
worker, returning the result(s).

This is flag-gated. It is only mounted when CODING_ENABLED=true (see
src/api/main.py), so it is inert in any deployment that hasn't opted in. It also
requires an authenticated user, because this surface will eventually dispatch
real coding work — it must never be reachable unauthenticated.

The worker is the stub until the real Claude Agent SDK worker is wired, so for
now `run=true` returns the stub's acknowledgement, not actual code changes.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth_utils import get_current_user
from src.coding.orchestrator import CodingOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter()

# Lazily-created default orchestrator (stub worker). Created on first use rather
# than at import, so importing this module has no DB side effects. Tests override
# the dependency below with a fake.
_orchestrator: Optional[CodingOrchestrator] = None


def get_orchestrator() -> CodingOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = CodingOrchestrator()
    return _orchestrator


class CodingMessageRequest(BaseModel):
    # `model_hint` is intentional; opt out of pydantic's protected `model_` namespace.
    model_config = ConfigDict(protected_namespaces=())

    source_ref: str = Field(..., min_length=1, description="Intention-thread key (e.g. web session id, slack thread_ts)")
    prompt: str = Field(..., min_length=1)
    source_type: str = Field(default="web")
    workspace_id: Optional[str] = None
    model_hint: Optional[str] = Field(default=None, description="opus | sonnet | haiku | cheap | full model id")
    run: bool = Field(default=True, description="Run queued work synchronously and return results")


class CodingResult(BaseModel):
    thread_ref: Optional[str]
    text: str


class CodingMessageResponse(BaseModel):
    session_id: str
    job_id: str
    seq: int
    ran: bool
    results: List[CodingResult]


@router.post("/message", response_model=CodingMessageResponse)
async def post_message(
    req: CodingMessageRequest,
    user: dict = Depends(get_current_user),
    orch: CodingOrchestrator = Depends(get_orchestrator),
):
    submitted = orch.submit(
        source_type=req.source_type,
        source_ref=req.source_ref,
        prompt=req.prompt,
        workspace_id=req.workspace_id,
        model_hint=req.model_hint,
    )
    results: List[CodingResult] = []
    if req.run:
        for action in orch.drain():
            results.append(CodingResult(thread_ref=action.thread_ref, text=action.text))

    return CodingMessageResponse(
        session_id=str(submitted["session"]["id"]),
        job_id=str(submitted["job"]["id"]),
        seq=submitted["job"]["seq"],
        ran=req.run,
        results=results,
    )


@router.get("/sessions/{session_id}/jobs")
async def list_session_jobs(
    session_id: str,
    user: dict = Depends(get_current_user),
    orch: CodingOrchestrator = Depends(get_orchestrator),
):
    jobs = orch.jobs.list_for_session(session_id)
    return {
        "session_id": session_id,
        "jobs": [
            {"id": str(j["id"]), "seq": j["seq"], "status": j["status"], "prompt": j["prompt"]}
            for j in jobs
        ],
    }
