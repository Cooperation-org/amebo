"""
Statements API — mission, vision, values, OKRs: what the org is aiming at.

The page these back is where a person edits the things that steer their own
prioritization (Golda 2026-08-05: "there should be a way for them to edit the
things that are affecting their prioritization"). Before this the goal
dispatcher guessed at them with a vector search and nobody could see or correct
the result.

Auth matches whiteboard/goals: user JWT or service X-API-Key, and the client's
org_id is the authority — callers never pass org_id.

    GET    /api/statements/            everything the org holds, proposals included
    GET    /api/statements/resolved    the switched-on ones with their words read
    POST   /api/statements/            add one {name, body|pointer, ...}
    PATCH  /api/statements/{id}        edit in place; accept a proposal
    DELETE /api/statements/{id}        throw one away
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from src.api.middleware.auth import get_service_or_user
from src.db.repositories.statement_repo import StatementRepo
from src.services import statements as statement_service

router = APIRouter()
logger = logging.getLogger(__name__)


class StatementOut(BaseModel):
    id: int
    org_id: int
    holder: str
    name: str
    body: Optional[str] = None
    pointer: Optional[str] = None
    source: str = ""
    informs_priority: bool = False
    written_by: str = ""
    accepted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ResolvedOut(BaseModel):
    """What a switched-on statement actually contributes, with the words read.

    The page shows the words rather than the link, per UX_PRINCIPLES §1 — a
    pointer at a document nobody can currently read is worth seeing as such.
    """
    id: int
    name: str
    text: str


class StatementCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    body: Optional[str] = Field(None, max_length=200_000)
    pointer: Optional[str] = Field(None, max_length=2000)
    source: str = Field("", max_length=500)
    informs_priority: bool = False
    holder: str = Field("org", max_length=200)

    @model_validator(mode="after")
    def _words_or_pointer(self):
        has_body = bool((self.body or "").strip())
        has_pointer = bool((self.pointer or "").strip())
        if has_body == has_pointer:
            raise ValueError("give either the words or a pointer to them, not both")
        return self


class StatementPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    body: Optional[str] = Field(None, max_length=200_000)
    pointer: Optional[str] = Field(None, max_length=2000)
    source: Optional[str] = Field(None, max_length=500)
    informs_priority: Optional[bool] = None
    accept: bool = False


def _who(client: Dict[str, Any]) -> str:
    """Same shape as whiteboard._author_identity: who made this change."""
    if client.get("auth") == "user":
        return client.get("email") or f"user:{client.get('user_id')}"
    return f"service:{client.get('key_name', 'unknown')}"


@router.get("/", response_model=List[StatementOut])
async def list_statements(client: dict = Depends(get_service_or_user)):
    return StatementRepo().list_for_org(client["org_id"])


@router.get("/resolved", response_model=List[ResolvedOut])
async def resolved(client: dict = Depends(get_service_or_user)):
    """The words currently steering this org, pointers followed."""
    return [
        {"id": sid, "name": name, "text": text}
        for name, text, sid in statement_service.live_context(client["org_id"])
    ]


@router.post("/", response_model=StatementOut, status_code=201)
async def add_statement(
    req: StatementCreate,
    client: dict = Depends(get_service_or_user),
):
    """A person adding one is accepting it by the act of writing it. A service
    key is amebo proposing: the row lands inert until a human accepts."""
    by_person = client.get("auth") == "user"
    row = StatementRepo().add(
        client["org_id"],
        req.name.strip(),
        body=(req.body or "").strip() or None,
        pointer=(req.pointer or "").strip() or None,
        source=req.source.strip(),
        informs_priority=req.informs_priority,
        holder=req.holder.strip() or "org",
        written_by=_who(client),
        accepted=by_person,
    )
    logger.info("statement %s added: org=%s name=%s accepted=%s",
                row["id"], client["org_id"], row["name"], by_person)
    return row


@router.patch("/{statement_id}", response_model=StatementOut)
async def edit_statement(
    statement_id: int,
    req: StatementPatch,
    client: dict = Depends(get_service_or_user),
):
    repo = StatementRepo()
    current = repo.get(statement_id, client["org_id"])
    if current is None:
        raise HTTPException(status_code=404, detail="No such statement")

    fields: Dict[str, Any] = {}
    if req.name is not None:
        fields["name"] = req.name.strip()
    if req.source is not None:
        fields["source"] = req.source.strip()
    if req.informs_priority is not None:
        fields["informs_priority"] = req.informs_priority
    # Words and pointer are exclusive in the DB, so setting one clears the
    # other rather than failing the constraint under the person's cursor.
    if req.body is not None:
        fields["body"] = req.body.strip() or None
        if fields["body"]:
            fields["pointer"] = None
    if req.pointer is not None:
        fields["pointer"] = req.pointer.strip() or None
        if fields["pointer"]:
            fields["body"] = None
    if not (fields.get("body") or fields.get("pointer")
            or (current.get("body") if "body" not in fields else None)
            or (current.get("pointer") if "pointer" not in fields else None)):
        raise HTTPException(status_code=400,
                            detail="A statement needs either words or a pointer")

    updated = repo.update(
        statement_id,
        client["org_id"],
        fields,
        written_by=_who(client) if client.get("auth") == "user" else "",
        accept=req.accept,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="No such statement")
    return updated


@router.delete("/{statement_id}", status_code=204)
async def delete_statement(
    statement_id: int,
    client: dict = Depends(get_service_or_user),
):
    if not StatementRepo().delete(statement_id, client["org_id"]):
        raise HTTPException(status_code=404, detail="No such statement")
    return None
