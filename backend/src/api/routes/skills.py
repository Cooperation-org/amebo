"""Skills the dashboard can offer as a button.

A skill is a markdown file (core catalog packaged with amebo, or the acting
org's overlay in its context repo). This route only reads them: it exists so a
surface like the cohort dash can show what amebo can be asked to do, in the
words of the skill itself, without any surface hardcoding a list.

The `ask` in each row is a sample message for the person's chat box: pressing
the button writes it there for them to edit before sending. The `slug` is what
the send carries, so the skill's own instructions are loaded for that message
without ever being written into the box.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from src.api.auth_utils import get_current_user
from src.services.skill_files import core_skills_dir, org_skills_dir, read_skills

router = APIRouter()
logger = logging.getLogger(__name__)


class SkillRow(BaseModel):
    slug: str           # the filename, which is what a chat message names to load it
    name: str
    description: str
    button: str
    ask: str
    order: int
    source: str          # 'core' | 'org'


class SkillDetail(SkillRow):
    body: str


def _skills_for(current_user: dict):
    """Core catalog plus the acting org's overlay, the overlay shadowing core."""
    return read_skills([org_skills_dir(current_user.get("org_id")), core_skills_dir()])


@router.get("/", response_model=List[SkillRow])
async def list_skills(
    audience: Optional[str] = Query(None, description="Only skills for this audience, e.g. founder"),
    current_user: dict = Depends(get_current_user),
):
    """Skills this org can use, in the order a person walks through them.

    Rows without a `button` are left out: a skill amebo chooses for itself is
    not automatically something to put on a screen.
    """
    rows = [
        s for s in _skills_for(current_user)
        if s.get("button") and (not audience or s.get("audience") == audience)
    ]
    rows.sort(key=lambda s: (s["order"], s["name"]))
    return [SkillRow(**{k: s[k] for k in SkillRow.model_fields}) for s in rows]


@router.get("/{name}", response_model=SkillDetail)
async def get_skill(name: str, current_user: dict = Depends(get_current_user)):
    """One skill, including what it tells amebo to do."""
    for s in _skills_for(current_user):
        if s["name"] == name:
            return SkillDetail(**{k: s[k] for k in SkillDetail.model_fields})
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No skill named '{name}'")
