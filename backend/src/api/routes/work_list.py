"""Work list REST API — one ranked list of what needs a human.

The surface that replaces reading a wall of "may I send this?" drafts. An item
here is the real thing (a Taiga story) with the links it has and, when a person
said something on it, their words. Amebo contributes assembly and provenance,
never prose about itself.

Auth matches pending_actions.py: a user JWT, a service X-API-Key, or the session
cookie. The authenticated client's org_id is the authority; callers never pass
one.

Endpoints:
    GET /api/work-list/    live + past items, live sorted by rank

Ranking is returned, not enforced by the client: every item carries ``rank`` and
``reason.kind`` ('clock' for the deterministic half, 'judgement' for the judged
half), so a client can re-sort or filter later without a backend change.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.middleware.auth import get_service_or_user
from src.db.repositories.pending_action_repo import PendingActionRepo
from src.services.work_list import Item, assemble
from src.services.work_list_taiga import TaigaStoryStore

logger = logging.getLogger(__name__)

router = APIRouter()


# ------------------------------------------------------------------ shapes


class LinkOut(BaseModel):
    label: str
    url: str
    found: bool


class QuoteOut(BaseModel):
    who: str
    text: str
    url: Optional[str] = None


class ReasonOut(BaseModel):
    label: str
    kind: str


class ItemOut(BaseModel):
    subject: str
    title: str
    reason: ReasonOut
    rank: float
    links: List[LinkOut]
    quote: Optional[QuoteOut] = None
    due: Optional[str] = None
    assignee: Optional[str] = None
    past: bool


class WorkListOut(BaseModel):
    live: List[ItemOut]
    past: List[ItemOut]


def _out(item: Item) -> ItemOut:
    return ItemOut(
        subject=item.subject,
        title=item.title,
        reason=ReasonOut(label=item.reason.label, kind=item.reason.kind),
        rank=item.rank,
        links=[LinkOut(label=l.label, url=l.url, found=l.found) for l in item.links],
        quote=(QuoteOut(who=item.quote.who, text=item.quote.text, url=item.quote.url)
               if item.quote else None),
        due=item.due,
        assignee=item.assignee,
        past=item.past,
    )


# ------------------------------------------------------------------ sources


def subjects_for_org(repo: PendingActionRepo, org_id: int) -> List[str]:
    """Which things the claw has surfaced for this org.

    Today the only producer is the deadline follow-up claw, which records the
    story it is about as ``payload.followup_task`` ('slug#ref'). Reading the
    subject off the payload (rather than parsing the drafted message) is what
    lets the list show the task instead of the message about the task.

    Deduped, newest first, because the same story can be pinged on more than
    one occasion.
    """
    seen: List[str] = []
    for action in repo.list_for_org(org_id=org_id, status="pending"):
        key = (action.get("payload") or {}).get("followup_task")
        if key and key not in seen:
            seen.append(key)
    return seen


# ------------------------------------------------------------------ route


@router.get("/", response_model=WorkListOut)
async def get_work_list(client: Dict[str, Any] = Depends(get_service_or_user)):
    org_id = client.get("org_id")
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for this client")

    repo = PendingActionRepo()
    subjects = subjects_for_org(repo, org_id)
    if not subjects:
        return WorkListOut(live=[], past=[])

    store = TaigaStoryStore()
    try:
        result = assemble(subjects, store, taiga_host=store.host)
    except Exception as exc:  # noqa: BLE001 - a Taiga outage must not 500 the dash
        logger.warning("work-list: assembly failed for org %s: %s", org_id, exc)
        raise HTTPException(status_code=503,
                            detail="Task source unavailable") from exc

    return WorkListOut(live=[_out(i) for i in result.live],
                       past=[_out(i) for i in result.past])
