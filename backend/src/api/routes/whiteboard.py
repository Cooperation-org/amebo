"""
Whiteboard API — the org's input surface (a chatter log, not a record).

People jot project talk here as it happens; amebo's filing pass reads the
unprocessed entries, puts each fact where it belongs (projects tracker, abra,
Taiga, CRM), and stamps the entry processed. See migration 027 and
docs/WHITEBOARD.md for the design.

Endpoints (auth matches goals/pending-actions: user JWT or service X-API-Key;
the client's org_id is the authority — callers never pass org_id):

    GET  /api/whiteboard/                     recent entries (?unprocessed=true, ?limit=)
    POST /api/whiteboard/                     add an entry {text}
    POST /api/whiteboard/{id}/processed       stamp filed (amebo/service use) {filed?}
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.middleware.auth import get_service_or_user
from src.db.repositories.whiteboard_repo import WhiteboardRepo

router = APIRouter()
logger = logging.getLogger(__name__)


class EntryCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class ProcessedRequest(BaseModel):
    filed: Optional[List[Dict[str, Any]]] = None


class EntryResponse(BaseModel):
    id: int
    org_id: int
    user_id: Optional[int] = None
    author: str = ""
    text: str
    created_at: datetime
    processed_at: Optional[datetime] = None
    filed: Optional[List[Dict[str, Any]]] = None


def _author_identity(client: dict) -> str:
    """Same shape as pending_actions._approver_identity: who wrote this."""
    if client.get("auth") == "user":
        return client.get("email") or f"user:{client.get('user_id')}"
    return f"service:{client.get('key_name', 'unknown')}"


@router.get("/", response_model=List[EntryResponse])
async def list_entries(
    unprocessed: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    client: dict = Depends(get_service_or_user),
):
    repo = WhiteboardRepo()
    return repo.list_for_org(client["org_id"], limit=limit, unprocessed_only=unprocessed)


@router.post("/", response_model=EntryResponse, status_code=201)
async def add_entry(
    req: EntryCreate,
    client: dict = Depends(get_service_or_user),
):
    repo = WhiteboardRepo()
    entry = repo.add(
        client["org_id"],
        req.text.strip(),
        user_id=client.get("user_id"),
        author=_author_identity(client),
    )
    logger.info("Whiteboard entry added: id=%s org=%s", entry["id"], client["org_id"])
    return entry


@router.post("/{entry_id}/processed", response_model=EntryResponse)
async def mark_processed(
    entry_id: int,
    req: ProcessedRequest = ProcessedRequest(),
    client: dict = Depends(get_service_or_user),
):
    """Stamp an entry as filed (amebo's filing pass calls this after putting the
    facts where they belong). Org-guarded; 409 if already processed."""
    repo = WhiteboardRepo()
    updated = repo.mark_processed(entry_id, client["org_id"], filed=req.filed)
    if updated is None:
        raise HTTPException(
            status_code=404, detail="Entry not found or already processed"
        )
    return updated
