"""
Echo API — a person's own journal / to-do lines on a timeline.

Golda 2026-09-08, after ECCO Pro: "simplest possible interface, click click
click, drill down, move things, enter stuff, move it, categorize it, put it on
a calendar, time is a line." Backs the page at GET /echo (embed/echo.html).

A line has: text, a day (on_date), an optional category (free text the person
chose), an optional parent (drill-down), and done_at. The authenticated USER is
the owner — rows are read and written by user_id only, never shared in the org.

    GET    /api/echo/            every line this person has
    POST   /api/echo/            add one {text, on_date?, category?, parent_id?}
    PATCH  /api/echo/{id}        change text / on_date / category / parent_id / position / done
    DELETE /api/echo/{id}        remove it (children go with it)
"""

import logging
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from src.api.middleware.auth import get_current_user
from src.db.repositories.echo_repo import EchoRepo

router = APIRouter()
logger = logging.getLogger(__name__)

TEXT_MAX = 4000
CATEGORY_MAX = 80


class LineCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=TEXT_MAX)
    on_date: Optional[date] = None
    category: Optional[str] = Field(None, max_length=CATEGORY_MAX)
    parent_id: Optional[int] = None


class LinePatch(BaseModel):
    """Every field optional; a field present with null clears it (category,
    parent_id). `done` is a boolean the API turns into done_at."""
    text: Optional[str] = Field(None, min_length=1, max_length=TEXT_MAX)
    on_date: Optional[date] = None
    category: Optional[str] = Field(None, max_length=CATEGORY_MAX)
    parent_id: Optional[int] = None
    position: Optional[int] = None
    done: Optional[bool] = None


class LineResponse(BaseModel):
    id: int
    parent_id: Optional[int] = None
    text: str
    category: Optional[str] = None
    on_date: date
    position: int
    done_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


def _clean_category(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()
    return value or None


@router.get("/", response_model=List[LineResponse])
async def list_lines(user: dict = Depends(get_current_user)):
    return EchoRepo().list_for_user(user["user_id"])


@router.post("/", response_model=LineResponse, status_code=201)
async def add_line(req: LineCreate, user: dict = Depends(get_current_user)):
    repo = EchoRepo()
    if req.parent_id is not None and repo.get(req.parent_id, user["user_id"]) is None:
        raise HTTPException(status_code=404, detail="Parent line not found")
    return repo.add(
        user["org_id"], user["user_id"], req.text.strip(),
        on_date=req.on_date, category=_clean_category(req.category),
        parent_id=req.parent_id,
    )


@router.patch("/{line_id}", response_model=LineResponse)
async def change_line(line_id: int, req: LinePatch, user: dict = Depends(get_current_user)):
    repo = EchoRepo()
    sent = req.model_dump(exclude_unset=True)
    changes = {}
    if "text" in sent:
        changes["text"] = sent["text"].strip()
    if "on_date" in sent and sent["on_date"] is not None:
        changes["on_date"] = sent["on_date"]
    if "category" in sent:
        changes["category"] = _clean_category(sent["category"])
    if "position" in sent and sent["position"] is not None:
        changes["position"] = sent["position"]
    if "done" in sent and sent["done"] is not None:
        changes["done_at"] = datetime.now(timezone.utc) if sent["done"] else None
    if "parent_id" in sent:
        parent_id = sent["parent_id"]
        if parent_id is not None:
            if parent_id == line_id:
                raise HTTPException(status_code=400, detail="A line cannot sit inside itself")
            if repo.get(parent_id, user["user_id"]) is None:
                raise HTTPException(status_code=404, detail="Parent line not found")
        changes["parent_id"] = parent_id
    row = repo.update(line_id, user["user_id"], changes)
    if row is None:
        raise HTTPException(status_code=404, detail="Line not found")
    return row


@router.delete("/{line_id}", status_code=204)
async def remove_line(line_id: int, user: dict = Depends(get_current_user)):
    if not EchoRepo().delete(line_id, user["user_id"]):
        raise HTTPException(status_code=404, detail="Line not found")
    return Response(status_code=204)
