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
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.middleware.auth import get_service_or_user
from src.db.repositories.pending_action_repo import PendingActionRepo
from src.services.work_list import (
    Item, assemble_stories, goal_task_refs, items_from_drafts, items_from_goals,
    parse_subject, story_url,
)
from src.services.viewer_identity import taiga_username
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

    # Questions amebo is holding for this person. These had their own page; one
    # list means they belong here, not nowhere.
    # Only the ones actually holding a question. A 'pending' goal is amebo's own
    # queued work — it is owned by amebo, so it belongs on nobody's list until
    # it needs an answer. Golda: "I DO NOT WANT TO SEE things assigned amebo
    # ... unless it has questions for me."
    from src.db.repositories.goal_repo import GoalRepo
    try:
        repo_g = GoalRepo()
        waiting = repo_g.list_for_org(org_id=org_id, status="waiting_user")
    except Exception as exc:  # noqa: BLE001
        logger.warning("work-list: goals unreadable for org %s: %s", org_id, exc)
        waiting = []
    live: List[Item] = items_from_goals(waiting)
    past: List[Item] = []

    # Whose list this is. Unmapped viewers get everything, not nothing — see
    # viewer_identity for where the map lives and why.
    try:
        from src.db.repositories.instance_repo import InstanceRepo
        instance = InstanceRepo().get_by_org(org_id) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("work-list: instance config unreadable for %s: %s", org_id, exc)
        instance = {}
    viewer = taiga_username(client, instance.get("config"))

    # Source 2: dated work on the boards.
    store = TaigaStoryStore()
    try:
        result = assemble_stories(store.open_dated_stories(), store,
                                  taiga_host=store.host,
                                  agent_username=os.getenv("TAIGA_USERNAME"),
                                  viewer_username=viewer)
        live.extend(result.live)
        past = result.past
    except Exception as exc:  # noqa: BLE001 - one source failing must not empty
        # the list; the others are still real work.
        logger.warning("work-list: taiga source failed for org %s: %s", org_id, exc)

    # Source 3: drafts the claw is holding that are not about a task already
    # listed above.
    try:
        drafts = PendingActionRepo().list_for_org(org_id=org_id, status="pending")
        live.extend(items_from_drafts(
            drafts, already=[i.subject for i in live] + [i.subject for i in past]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("work-list: drafts source failed for org %s: %s", org_id, exc)

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
    # 'task' or 'goal' — the sheet shows different controls for each, because a
    # goal has no board, no assignee and no due date to edit.
    kind: str = "task"
    ref: int
    # How a person names this item out loud. '#34' for a story, the claw's short
    # id for a goal. Something with no identifier cannot be referred to at all.
    code: Optional[str] = None
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
    trigger: Optional[str] = None
    # Who can be assigned on this board — a real list, not a free-text box that
    # fails silently on a typo.
    members: List[str] = []


def _guard(subject: str, org_id: int) -> tuple:
    """A subject may only be touched if it is something this org's list can
    actually contain.

    The project slug is caller-supplied, so this is the authorization boundary:
    the board must be one amebo is a member of, and not blocked. It used to
    require a pending draft instead, which was right when drafts were the only
    source and wrong the moment the list started reading the boards directly —
    every row that had no draft 404'd here and opened onto nothing.
    """
    parsed = parse_subject(subject.replace("taiga:", "", 1))
    if not parsed:
        raise HTTPException(status_code=400, detail="Unreadable subject")
    slug, _ref = parsed

    store = TaigaStoryStore()
    if not store.project_id(slug):
        raise HTTPException(status_code=404, detail="No such board")
    if store.project_blocked(slug):
        raise HTTPException(status_code=409,
                            detail="That board is blocked in Taiga")
    return parsed


def _task_detail(subject: str, slug: str, ref: int,
                 store: TaigaStoryStore) -> Optional[DetailOut]:
    """The task's full record, or None when the story cannot be read."""
    story = store.story(slug, ref)
    if not story:
        return None
    return DetailOut(
        subject=subject,
        ref=ref,
        code=f"#{ref}",
        project=slug,
        title=story.get("subject") or f"#{ref}",
        description=story.get("description"),
        status=(story.get("status_extra_info") or {}).get("name"),
        due=story.get("due_date"),
        assignee=(story.get("assigned_to_extra_info") or {}).get("username"),
        url=story_url(store.host, slug, ref),
        comments=[CommentOut(**c) for c in store.comments(story["id"])],
        statuses=[st.get("name") for st in store.statuses(slug) if st.get("name")],
        members=[m.get("username") for m in store.members(slug) if m.get("username")],
    )


def _goal_detail(goal_id: str, org_id: int) -> DetailOut:
    from src.db.repositories.goal_repo import GoalRepo
    goal = GoalRepo().get(goal_id)
    if not goal or goal.get("org_id") != org_id:
        raise HTTPException(status_code=404, detail="Not on your list")

    # A goal that is holding exactly one Taiga task opens AS that task: the
    # sheet shows the task's own record and controls, and every edit — archive
    # included — lands on the task, because the task is what the person means.
    # Only when it is the one task: the relation is not one-to-one, and a goal
    # holding several tasks (or none) is its own thing and shows as itself.
    refs = goal_task_refs(goal)
    if len(refs) == 1:
        slug, ref = refs[0]
        try:
            store = TaigaStoryStore()
            if store.project_id(slug) and not store.project_blocked(slug):
                detail = _task_detail(f"taiga:{slug}#{ref}", slug, ref, store)
                if detail:
                    return detail
        except Exception as exc:  # noqa: BLE001 - fall back to the goal itself
            logger.warning("work-list: goal %s task %s#%s unreadable: %s",
                           goal_id, slug, ref, exc)

    return DetailOut(
        subject=f"goal:{goal_id}",
        kind="goal",
        ref=0,
        # The first block of the uuid, which is how the claws are named
        # everywhere else (amebo-claw list, /claws/<id>). A goal used to open
        # with no identifier at all, so there was nothing to say it BY.
        code=str(goal_id)[:8],
        project="amebo",
        title=goal.get("title") or "(untitled)",
        description=goal.get("description"),
        status=goal.get("status"),
        url="",
        comments=[],
        # Only the transitions that mean something for a goal.
        statuses=["pending", "paused", "completed"],
        # A goal is amebo's work by definition — there is no other hand it can
        # be put in, and showing an empty owner read as "cannot be assigned".
        assignee="amebo",
        members=["amebo"],
        trigger=(goal.get("trigger_config") or {}).get("type"),
    )


def _draft_detail(action_id: str, org_id: int) -> DetailOut:
    """A draft the claw is holding, opened as itself.

    The list has always offered these rows; the detail endpoint only knew how to
    read 'taiga:' and 'goal:' subjects, so every draft row opened onto
    "Unreadable subject". What the person needs to see is the words amebo wants
    to send in their name, and where they would go.
    """
    action = PendingActionRepo().get(action_id)
    if not action or action.get("org_id") != org_id:
        raise HTTPException(status_code=404, detail="Not on your list")

    payload = action.get("payload") or {}
    text = payload.get("text") or action.get("preview") or ""
    return DetailOut(
        subject=f"draft:{action_id}",
        kind="draft",
        ref=0,
        project=action.get("action_type") or "draft",
        title=(text.strip().splitlines() or [""])[0][:120] or "(empty draft)",
        description=text,
        status=action.get("status"),
        assignee=action.get("target"),
        url="",
        comments=[],
        statuses=[],
    )


@router.get("/detail", response_model=DetailOut)
async def get_detail(subject: str,
                     client: Dict[str, Any] = Depends(get_service_or_user)):
    org_id = client.get("org_id")
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for this client")
    if subject.startswith("goal:"):
        return _goal_detail(subject.split(":", 1)[1], org_id)
    if subject.startswith("draft:"):
        return _draft_detail(subject.split(":", 1)[1], org_id)
    slug, ref = _guard(subject, org_id)

    detail = _task_detail(subject, slug, ref, TaigaStoryStore())
    if not detail:
        raise HTTPException(status_code=404, detail="Story not found")
    return detail


# ------------------------------------------------------------------ edit


class EditIn(BaseModel):
    subject: str
    # Goals only: '' one-shot, 'cron' daily until done, 'manual' on request.
    trigger: Optional[str] = None
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

    if body.subject.startswith("goal:"):
        return _edit_goal(body, org_id)

    if body.subject.startswith("draft:"):
        return _edit_draft(body, org_id,
                           approver=str(client.get("user") or client.get("email")
                                        or "list"))

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


def _edit_draft(body: "EditIn", org_id: int, *, approver: str) -> "EditOut":
    """What the human can do to a draft from the list.

    Saying something to a draft is not a note filed against it: it declines this
    wording and hands the words back to the claw, which redrafts with them. That
    is what DraftApprovalService.feedback already does, so it is used rather than
    a second path invented here.

    Sending is deliberately NOT here. Approving a draft acts as the person — it
    sends the mail, posts the post — so it stays on the pending-actions approve
    route where the audit trail is, and it is never something a field on this
    sheet can trigger by accident.
    """
    from src.services.draft_approval_service import (DraftApprovalService,
                                                     PendingActionNotFound)
    service = DraftApprovalService()
    action_id = body.subject.split(":", 1)[1]

    try:
        if body.comment:
            service.feedback(action_id, approver=approver, org_id=org_id,
                             feedback=body.comment)
            return EditOut(applied=["feedback"])
        if body.archive or body.delete or body.close:
            service.reject(action_id, approver=approver, org_id=org_id,
                           reason="declined from the list")
            return EditOut(applied=["reject"])
    except PendingActionNotFound as exc:
        raise HTTPException(status_code=404, detail="Not on your list") from exc

    raise HTTPException(status_code=400,
                        detail="A draft takes your words or a decline, nothing else")


def _edit_goal(body: "EditIn", org_id: int) -> "EditOut":
    """Update or cancel a goal. Delete is a real delete: a cancelled goal that
    lingers is just noise on the list."""
    from src.db.repositories.goal_repo import GoalRepo
    repo = GoalRepo()
    goal_id = body.subject.split(":", 1)[1]
    goal = repo.get(goal_id)
    if not goal or goal.get("org_id") != org_id:
        raise HTTPException(status_code=404, detail="Not on your list")

    applied: List[str] = []
    if body.delete:
        repo.delete(goal_id, org_id)
        return EditOut(applied=["delete"])

    if body.title is not None or body.description is not None:
        if repo.update_text(goal_id, org_id, title=body.title,
                            description=body.description):
            applied.append("text")

    if body.trigger is not None:
        # A cron goal keeps returning until something says it is done; an empty
        # trigger means one-shot. Both are the human's call to make here.
        trigger = ({"type": "cron", "expression": "0 9 * * *"} if body.trigger == "cron"
                   else {"type": "manual"} if body.trigger == "manual"
                   else None)
        repo.set_trigger(goal_id, org_id, trigger)
        applied.append("schedule")
    # 'archive' and 'close' both mean "stop working this" for a goal.
    status = body.status or ("completed" if (body.close or body.archive) else None)
    if status:
        repo.set_status(goal_id, status, completed=(status == "completed"))
        applied.append(status)

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
