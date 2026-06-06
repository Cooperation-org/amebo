"""
Pending-actions REST API — the human-in-the-loop approval surface.

A background claw routes every outbound/destructive action through the draft-
approval gate (see src/services/draft_approval_service.py). Gated actions land
as 'pending' rows; this router lets a human list them and approve or reject.

Authentication matches goals.py: either an X-API-Key (service-to-service) or a
Bearer JWT (per-user, via the view-server proxy). The authenticated client's
org_id is the authority for every operation — callers never specify org_id
directly, and actions belonging to other orgs are invisible (404), regardless
of which auth path was used.

Endpoints:
    GET    /api/pending-actions/                 list pending actions for the org
    GET    /api/pending-actions/{action_id}      action detail
    POST   /api/pending-actions/{action_id}/approve  approve (does NOT execute)
    POST   /api/pending-actions/{action_id}/reject   reject (terminal)

Registration is deferred to the OAuth/SSO session owners — see
docs/DRAFT_APPROVAL_GATE.md. This file does not edit src/api/main.py.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.middleware.auth import get_service_or_user
from src.db.repositories.pending_action_repo import VALID_STATUSES
from src.services.draft_approval_service import (
    DraftApprovalService, PendingActionNotFound,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class RejectRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=2000)


class PendingActionResponse(BaseModel):
    id: str
    org_id: int
    instance_id: Optional[int] = None
    goal_id: Optional[str] = None
    action_type: str
    target: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    preview: Optional[str] = None
    status: str
    acting_identity: str
    requested_at: datetime
    approver: Optional[str] = None
    decision_reason: Optional[str] = None
    decided_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _service() -> DraftApprovalService:
    return DraftApprovalService()


def _to_response(action: Dict[str, Any]) -> PendingActionResponse:
    return PendingActionResponse(
        id=str(action["id"]),
        org_id=action["org_id"],
        instance_id=action.get("instance_id"),
        goal_id=str(action["goal_id"]) if action.get("goal_id") else None,
        action_type=action["action_type"],
        target=action.get("target"),
        payload=action.get("payload"),
        preview=action.get("preview"),
        status=action["status"],
        acting_identity=action["acting_identity"],
        requested_at=action["requested_at"],
        approver=action.get("approver"),
        decision_reason=action.get("decision_reason"),
        decided_at=action.get("decided_at"),
        executed_at=action.get("executed_at"),
        error=action.get("error"),
    )


def _approver_identity(client: dict) -> str:
    """Human-readable identity of the approving caller for the audit trail."""
    if client.get("auth") == "user":
        return client.get("email") or f"user:{client.get('user_id')}"
    return f"service:{client.get('key_name', 'unknown')}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_model=List[PendingActionResponse])
async def list_pending_actions(
    status: Optional[str] = "pending",
    client: dict = Depends(get_service_or_user),
):
    """List actions for the authenticated org. Defaults to status=pending;
    pass an empty string or omit a valid filter to widen."""
    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Allowed: {sorted(VALID_STATUSES)}",
            )
        actions = _service().list_for_instance(client["org_id"], status=status)
    else:
        actions = _service().list_for_instance(client["org_id"], status=None)
    return [_to_response(a) for a in actions]


@router.get("/{action_id}", response_model=PendingActionResponse)
async def get_pending_action(
    action_id: str,
    client: dict = Depends(get_service_or_user),
):
    try:
        action = _service().get(action_id, client["org_id"])
    except PendingActionNotFound:
        raise HTTPException(status_code=404, detail="Pending action not found")
    return _to_response(action)


@router.post("/{action_id}/approve", response_model=PendingActionResponse)
async def approve_pending_action(
    action_id: str,
    client: dict = Depends(get_service_or_user),
):
    """Approve a pending action. Transitions pending → approved; does NOT
    execute. The executor performs the action separately after approval."""
    svc = _service()
    try:
        updated = svc.approve(
            action_id, approver=_approver_identity(client), org_id=client["org_id"],
        )
    except PendingActionNotFound:
        # Either unknown/other-org (true 404) or not pending (409). Disambiguate
        # without leaking other orgs' existence.
        try:
            svc.get(action_id, client["org_id"])
        except PendingActionNotFound:
            raise HTTPException(status_code=404, detail="Pending action not found")
        raise HTTPException(status_code=409, detail="Action is not pending")
    logger.info("Pending action approved: id=%s org=%s", action_id, client["org_id"])
    return _to_response(updated)


@router.post("/{action_id}/reject", response_model=PendingActionResponse)
async def reject_pending_action(
    action_id: str,
    req: RejectRequest = RejectRequest(),
    client: dict = Depends(get_service_or_user),
):
    """Reject a pending action (terminal). Records who and why."""
    svc = _service()
    try:
        updated = svc.reject(
            action_id, approver=_approver_identity(client),
            org_id=client["org_id"], reason=req.reason,
        )
    except PendingActionNotFound:
        try:
            svc.get(action_id, client["org_id"])
        except PendingActionNotFound:
            raise HTTPException(status_code=404, detail="Pending action not found")
        raise HTTPException(status_code=409, detail="Action is not pending")
    logger.info("Pending action rejected: id=%s org=%s", action_id, client["org_id"])
    return _to_response(updated)
