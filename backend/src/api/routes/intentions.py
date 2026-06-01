"""
Intentions API — backs the <amebo-create-goal> embed component.

Two endpoints:
  POST /api/intentions/place    — propose a placement (no writes)
  POST /api/intentions/commit   — apply a (possibly edited) proposal

The component flow:
  1. user types free text → POST /place → returns Proposal
  2. user edits / corrects in free text → POST /place again with feedback
  3. user confirms → POST /commit with the (possibly edited) proposal
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.middleware.auth import get_current_user
from src.services.intentions_service import IntentionsService, Proposal


router = APIRouter()
logger = logging.getLogger(__name__)

# One service instance per process is fine — the Anthropic client is
# thread-safe and the writer is constructed per-commit.
_service = IntentionsService()


# ── request / response models ─────────────────────────────────────────────

class PlaceRequest(BaseModel):
    text: str = Field(..., min_length=1)
    scope: str = Field(default="golda")
    name: Optional[str] = Field(default=None,
                                description="Existing name when in extend mode")
    feedback: Optional[str] = Field(default=None,
                                    description="Free-text correction on the prior proposal")


class ProposalModel(BaseModel):
    scope: str
    name: str
    name_is_new: bool
    content_summary: str
    labels: List[str] = []
    make_clawable: bool = False
    cron: Optional[str] = None
    title: str = ""
    description: str = ""
    reasoning: str = ""


class CommitResponse(BaseModel):
    scope: str
    name: str
    content_id: int
    goal_id: Optional[str] = None
    bindings_written: int
    labels_set: List[str] = []


# ── routes ────────────────────────────────────────────────────────────────

@router.post("/place", response_model=ProposalModel)
async def place(req: PlaceRequest,
                current_user: dict = Depends(get_current_user)):
    """Propose a placement for free-text input. No writes."""
    try:
        proposal = _service.propose(
            text=req.text,
            scope=req.scope,
            name=req.name,
            feedback=req.feedback,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ProposalModel(**proposal.to_dict())


@router.post("/commit", response_model=CommitResponse)
async def commit(req: ProposalModel,
                  current_user: dict = Depends(get_current_user)):
    """Apply a (possibly edited) proposal. Writes to abra (and creates
    an amebo goal if clawable)."""
    proposal = Proposal(
        scope=req.scope, name=req.name, name_is_new=req.name_is_new,
        content_summary=req.content_summary, labels=list(req.labels),
        make_clawable=req.make_clawable, cron=req.cron,
        title=req.title, description=req.description,
        reasoning=req.reasoning,
    )
    org_id = current_user.get("org_id")
    user_id = current_user.get("user_id")
    google_sub = current_user.get("google_sub") or current_user.get("email") or f"user-{user_id}"
    writer_uri = f"urn:amebo:user:{google_sub}"

    if org_id is None:
        raise HTTPException(status_code=400, detail="No org_id on token")

    try:
        result = _service.commit(
            proposal,
            user_writer_uri=writer_uri,
            org_id=org_id,
            created_by_user_id=user_id,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Commit failed")
        raise HTTPException(status_code=500, detail=f"commit failed: {e}")

    return CommitResponse(**result)
