"""Work list REST API — one ranked list of what needs a human.

The surface that replaces reading a wall of "may I send this?" drafts. An item
here is the real thing (a Taiga story) with the links it has and, when a person
said something on it, their words. Amebo contributes assembly and provenance,
never prose about itself.

Auth matches pending_actions.py: a user JWT, a service X-API-Key, or the session
cookie. The authenticated client's org_id is the authority; callers never pass
one.

Endpoints:
    GET  /api/work-list/          live + past items, live sorted by rank
    GET  /api/work-list/detail    one item's full record + what people said on it
    POST /api/work-list/edit      apply a change the human just pressed

Writes here are NOT gated. The draft-approval gate exists to stop the claw acting
unilaterally; when the human presses the button there is nothing to gate. They run
through the same registered executors the gate would have run on approval, so
there is one write path and no new authority. Every edit is checked against the
org's own list first, so a subject the org was never shown cannot be edited by
passing it in.

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
from src.services.work_list import (
    Item, assemble, items_from_goals, parse_subject,
)
from src.services.work_list_taiga import TaigaStoryStore
from src.tools.gated_actuators import (
    execute_taiga_close, execute_taiga_comment, execute_taiga_update,
)

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

    # Questions amebo is holding for this person. These had their own page; one
    # list means they belong here, not nowhere.
    from src.db.repositories.goal_repo import GoalRepo
    try:
        waiting = GoalRepo().list_for_org(org_id=org_id, status="waiting_user")
    except Exception as exc:  # noqa: BLE001
        logger.warning("work-list: goals unreadable for org %s: %s", org_id, exc)
        waiting = []
    live: List[Item] = items_from_goals(waiting)
    past: List[Item] = []

    if subjects:
        store = TaigaStoryStore()
        try:
            result = assemble(subjects, store, taiga_host=store.host)
            live.extend(result.live)
            past = result.past
        except Exception as exc:  # noqa: BLE001 - a Taiga outage must not empty
            # the whole list; the goals half is still real work.
            logger.warning("work-list: taiga half failed for org %s: %s", org_id, exc)

    live.sort(key=lambda i: (-i.rank, i.title))
    return WorkListOut(live=[_out(i) for i in live],
                       past=[_out(i) for i in past])


# ------------------------------------------------------------------ detail


class CommentOut(BaseModel):
    who: str
    text: str
    when: Optional[str] = None


class DetailOut(BaseModel):
    subject: str
    ref: int
    project: str
    title: str
    description: Optional[str] = None
    status: Optional[str] = None
    due: Optional[str] = None
    assignee: Optional[str] = None
    url: str
    comments: List[CommentOut]
    # The board's own statuses, in board order, so the dropdown matches Marten
    # instead of offering a list amebo invented.
    statuses: List[str] = []
    # Who can be assigned on this board — a real list, not a free-text box that
    # fails silently on a typo.
    members: List[str] = []


def _guard(subject: str, org_id: int) -> tuple:
    """A subject may only be touched if it is on this org's own list. Without
    this the project slug would be caller-supplied, and on a deployment where one
    Taiga token reaches several boards that is the whole authorization story."""
    parsed = parse_subject(subject.replace("taiga:", "", 1))
    if not parsed:
        raise HTTPException(status_code=400, detail="Unreadable subject")
    if subject not in {f"taiga:{s}" for s in subjects_for_org(PendingActionRepo(), org_id)}:
        raise HTTPException(status_code=404, detail="Not on your list")
    return parsed


@router.get("/detail", response_model=DetailOut)
async def get_detail(subject: str,
                     client: Dict[str, Any] = Depends(get_service_or_user)):
    org_id = client.get("org_id")
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for this client")
    slug, ref = _guard(subject, org_id)

    store = TaigaStoryStore()
    story = store.story(slug, ref)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    return DetailOut(
        subject=subject,
        ref=ref,
        project=slug,
        title=story.get("subject") or f"#{ref}",
        description=story.get("description"),
        status=(story.get("status_extra_info") or {}).get("name"),
        due=story.get("due_date"),
        assignee=(story.get("assigned_to_extra_info") or {}).get("username"),
        url=f"{store.host}/project/{slug}/us/{ref}",
        comments=[CommentOut(**c) for c in store.comments(story["id"])],
        statuses=[st.get("name") for st in store.statuses(slug) if st.get("name")],
        members=[m.get("username") for m in store.members(slug) if m.get("username")],
    )


# ------------------------------------------------------------------ edit


class EditIn(BaseModel):
    subject: str
    # The story's own title. Named apart from `subject` (the item URI) so the
    # two are never confused on the wire.
    title: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    comment: Optional[str] = None
    close: bool = False
    archive: bool = False
    # Irreversible, and the only thing here that is. The client asks for it
    # explicitly behind a confirm; nothing else on the surface can reach it.
    delete: bool = False


class EditOut(BaseModel):
    applied: List[str]


@router.post("/edit", response_model=EditOut)
async def edit(body: EditIn,
               client: Dict[str, Any] = Depends(get_service_or_user)):
    """Apply what the human just pressed, immediately.

    'Later' is one of these: it writes a new due date on the story. Nothing is
    stored in amebo for a snooze — the task carries its own date, and the claw
    surfaces it again when that date comes round.
    """
    org_id = client.get("org_id")
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for this client")
    slug, ref = _guard(body.subject, org_id)

    base = {"org_id": org_id, "project": slug, "ref": ref}
    applied: List[str] = []

    try:
        fields = {k: v for k, v in
                  (("due_date", body.due_date), ("description", body.description),
                   ("status", body.status), ("subject", body.title),
                   ("assignee", body.assignee)) if v}
        if fields:
            execute_taiga_update({"org_id": org_id, "payload": {**base, **fields}})
            applied.extend(fields)
        if body.comment:
            execute_taiga_comment({"org_id": org_id,
                                   "payload": {**base, "text": body.comment}})
            applied.append("comment")
        if body.close:
            execute_taiga_close({"org_id": org_id, "payload": base})
            applied.append("close")
        if body.archive:
            store = TaigaStoryStore()
            archived = store.archived_status(slug)
            if not archived:
                # Do NOT quietly close instead — that is a different outcome.
                raise HTTPException(status_code=409,
                                    detail="This board has no archive status")
            execute_taiga_close({"org_id": org_id,
                                 "payload": {**base, "status": archived}})
            applied.append("archive")
        if body.delete:
            store = TaigaStoryStore()
            story = store.story(slug, ref)
            if not story:
                raise HTTPException(status_code=404, detail="Story not found")
            store.delete(story["id"])
            logger.info("work-list: org %s deleted %s", org_id, body.subject)
            applied.append("delete")
    except RuntimeError as exc:
        logger.warning("work-list edit failed for %s: %s", body.subject, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Handling the task from the list is what the drafted ping was for, so the
    # ping is no longer wanted: its rows are declined, which is what takes the
    # item out of the list. Without this, archiving a story leaves the row
    # sitting there because the list is driven by the pending drafts, not by the
    # story's status.
    if any(a in applied for a in ("close", "archive", "delete", "due_date")):
        _stand_down(repo=PendingActionRepo(), org_id=org_id, subject=body.subject,
                    approver=str(client.get("user") or "list"))

    if not applied:
        raise HTTPException(status_code=400, detail="Nothing to change")
    return EditOut(applied=applied)


def _stand_down(*, repo: PendingActionRepo, org_id: int, subject: str,
                approver: str) -> None:
    """Decline every pending draft about this subject. Rejected, not approved:
    the message was never sent, and recording it as sent would be a lie in the
    audit trail."""
    key = subject.replace("taiga:", "", 1)
    for action in repo.list_for_org(org_id=org_id, status="pending"):
        if (action.get("payload") or {}).get("followup_task") != key:
            continue
        repo.set_decision(action_id=str(action["id"]), org_id=org_id,
                          to_status="rejected", approver=approver,
                          decision_reason="handled from the list")
