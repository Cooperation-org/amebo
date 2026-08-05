"""The work list — one ranked list of what needs a human, assembled from
what the team's systems already hold.

Design rules this file implements (see docs/WORK_LIST.md):

- **Assemble, don't narrate.** An item carries the real referent (a Taiga story),
  the links it has, and a person's own words when a person said something. It
  never carries prose amebo wrote about itself.
- **Their words.** When the source record has a human comment, that comment IS
  the item's headline, attributed and linked back to where it was said. When no
  one said anything, the item has no headline — just the thing and its links.
- **One ranked list.** A deadline raises rank, it does not get its own section.
  Ranking is split into a deterministic part (the clock) and a judged part, and
  every item reports which one put it where it is.
- **Provenance on links.** A link amebo went and found is flagged `found=True`
  so the reader knows which ones to distrust. Links already on the record are not.
- **What went past drops out of the live list** into ``past``, so a missed
  deadline is visible without nagging from the top.

This module is read-only: it resolves and ranks. Acting on an item is the
executors' job (src/services/action_executors.py), and every write a human
presses goes through those, not through here.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Protocol, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


@dataclass
class Link:
    """Something the reader can click. ``found`` marks a link amebo located
    itself rather than one that was already on the record."""
    label: str
    url: str
    found: bool = False


@dataclass
class Quote:
    """A person's own words, and where they said them."""
    who: str
    text: str
    url: Optional[str] = None


@dataclass
class Reason:
    """Why this item sits where it does. ``kind`` is 'clock' when a rule put it
    there (dated, deterministic, needs no defending) or 'judgement' when the
    ranking is a call that has to justify itself in the label."""
    label: str
    kind: str  # 'clock' | 'judgement'


# What a subject's scheme means. The list is not task-only — Golda: "amebo
# supposed to be unifying all the things ... cards be different types ...
# intention centric". A card's type is already written in its subject, so it is
# read back out of the subject rather than stored a second time where the two
# could disagree.
KINDS = {
    "taiga": "task",        # a story on a board
    "goal": "goal",         # a question a claw is holding
    "draft": "draft",       # something amebo wants to send as you
    "crm": "contact",       # a follow-up someone scheduled on a CRM record
}


def kind_of(subject: str) -> str:
    """'crm:activity/19' -> 'contact'. Unknown schemes read as 'task' so a new
    source shows up as an ordinary row instead of breaking the page."""
    scheme = subject.split(":", 1)[0] if ":" in subject else ""
    return KINDS.get(scheme, "task")


@dataclass
class Item:
    subject: str                    # stable URI, e.g. 'taiga:my-project#34'
    title: str
    reason: Reason
    rank: float
    links: List[Link] = field(default_factory=list)
    quote: Optional[Quote] = None
    due: Optional[str] = None
    assignee: Optional[str] = None
    past: bool = False              # deadline already went by

    @property
    def kind(self) -> str:
        return kind_of(self.subject)


class StoryStore(Protocol):
    """What the list needs from Taiga. Implemented by TaigaStoryStore below and
    faked in tests."""

    def story(self, project_slug: str, ref: int) -> Optional[Dict[str, Any]]: ...

    def last_comment(self, story_id: int) -> Optional[Dict[str, str]]: ...


# ---------------------------------------------------------------------------
# Ranking — a deterministic half and a judged half
# ---------------------------------------------------------------------------

# The clock half. A dated item's rank is fixed by how close the date is, and no
# judged item may be scored into this band (see JUDGED_CEILING).
CLOCK_FLOOR = 1000.0
JUDGED_CEILING = 999.0


def clock_reason(due: Optional[str], today: date) -> Optional[Reason]:
    """The rule half of ranking. Returns None when the item is not dated, in
    which case the caller falls back to a judged reason."""
    if not due:
        return None
    try:
        d = date.fromisoformat(due)
    except ValueError:
        return None
    days = (d - today).days
    if days < 0:
        return Reason(f"due {d.strftime('%b %-d').lower()}", "clock")
    if days == 0:
        return Reason("today", "clock")
    if days == 1:
        return Reason("tomorrow", "clock")
    return Reason(f"in {days} days", "clock")


def clock_rank(due: str, today: date) -> float:
    """Sooner is higher. Every dated item outranks every judged one."""
    try:
        days = (date.fromisoformat(due) - today).days
    except ValueError:
        return CLOCK_FLOOR
    return CLOCK_FLOOR + max(0.0, 365.0 - days)


def judged_rank(story: Dict[str, Any]) -> float:
    """The judged half, kept deliberately small and explainable. Nothing here
    may exceed JUDGED_CEILING, so judgement can never bury a dated item."""
    score = 0.0
    if story.get("assigned_to"):
        score += 20.0                       # someone owns it -> it can actually move
    if not story.get("description"):
        score -= 10.0                       # nothing to act on yet
    return min(JUDGED_CEILING, max(0.0, score))


def judged_reason(story: Dict[str, Any]) -> Reason:
    if not story.get("assigned_to"):
        return Reason("no owner", "judgement")
    if not story.get("description"):
        return Reason("nothing written down", "judgement")
    return Reason("open", "judgement")


# ---------------------------------------------------------------------------
# Building an item from a story
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s\)>\]]+")


def story_url(ui_base: str, project_slug: str, ref: Any) -> str:
    """Where a person goes to see a story.

    Marten, never Taiga's own interface — Golda: "NO links that way only marten
    interface svelte good, taiga interface NO". One place builds this so a link
    to Taiga cannot creep back in through a second one.
    """
    return f"{ui_base.rstrip('/')}/p/{project_slug}/board?story={ref}"


def links_from_story(story: Dict[str, Any], taiga_host: str,
                     project_slug: str) -> List[Link]:
    """The story itself, plus any URL written into its description. Links found
    in the record are NOT flagged ``found`` — that flag is for links amebo went
    and looked up, which it records in the description with its own marker."""
    ref = story.get("ref")
    links = [Link(f"#{ref} {story.get('subject', '')}".strip(),
                  story_url(taiga_host, project_slug, ref))]
    for url in _URL_RE.findall(story.get("description") or ""):
        links.append(Link(_short(url), url))
    return links


def _short(url: str) -> str:
    """A link label a person can read: host + first path segment."""
    stripped = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
    parts = stripped.split("/")
    return parts[0] if len(parts) == 1 else f"{parts[0]}/{parts[1]}"


def _display_name(story: Dict[str, Any], key: str) -> Optional[str]:
    info = story.get(f"{key}_extra_info") or {}
    return info.get("username") or info.get("full_name")


def build_item(story: Dict[str, Any], *, project_slug: str, taiga_host: str,
               today: date, comment: Optional[Dict[str, str]] = None) -> Item:
    """One story becomes one item. The most recent human comment, if there is
    one, becomes the headline; otherwise the item leads with the thing itself."""
    ref = story.get("ref")
    due = story.get("due_date")
    clock = clock_reason(due, today)
    reason = clock or judged_reason(story)
    rank = clock_rank(due, today) if clock else judged_rank(story)
    past = bool(due and _is_past(due, today))

    quote = None
    if comment and comment.get("text"):
        quote = Quote(
            who=comment.get("who") or "someone",
            text=comment["text"],
            url=story_url(taiga_host, project_slug, ref),
        )

    return Item(
        subject=f"taiga:{project_slug}#{ref}",
        title=story.get("subject") or f"#{ref}",
        reason=reason,
        rank=rank,
        links=links_from_story(story, taiga_host, project_slug),
        quote=quote,
        due=due,
        assignee=_display_name(story, "assigned_to"),
        past=past,
    )


def _is_past(due: str, today: date) -> bool:
    try:
        return date.fromisoformat(due) < today
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def items_from_drafts(actions: Sequence[Dict[str, Any]],
                      already: Sequence[str] = ()) -> List[Item]:
    """Gated drafts the claw is holding become items too.

    A draft whose subject is already in the list as a story is dropped: the task
    is the thing, and the message about the task is not a second row. What is
    left is a draft that stands on its own — an email or a post amebo wants to
    send as you — and that genuinely needs a decision.
    """
    seen = set(already)
    items: List[Item] = []
    for action in actions:
        payload = action.get("payload") or {}
        key = payload.get("followup_task")
        if key and f"taiga:{key}" in seen:
            continue
        text = payload.get("text") or action.get("preview") or ""
        links = [Link(_short(u), u) for u in _URL_RE.findall(text)]
        items.append(Item(
            subject=f"draft:{action.get('id')}",
            title=(text.strip().splitlines() or [""])[0][:120] or "(empty draft)",
            reason=Reason("waiting on you", "judgement"),
            rank=JUDGED_CEILING,
            links=links,
            quote=None,
            due=None,
            assignee=None,
            past=False,
        ))
    return items


# How a goal names the task it is about, when it is about one: either the
# written form the claws use ("Taiga story #4 in project some-slug") or a link
# to the story in Taiga or Marten. Matching both means the tie survives however
# the description was phrased.
_GOAL_TASK_PHRASE_RE = re.compile(
    r"taiga\s+story\s+#(\d+)\s+in\s+project\s+([a-z0-9][a-z0-9_-]*)", re.I)
_GOAL_TASK_URL_RE = re.compile(
    r"https?://[^\s\)>\]]*/project/([a-z0-9][a-z0-9_-]*)/us/(\d+)", re.I)


def goal_task_refs(goal: Dict[str, Any]) -> List[tuple]:
    """Every Taiga story the goal names, as ('slug', ref), deduped, in the
    order written. A goal may hold none, one, or several tasks — the relation
    is not one-to-one, so callers must never treat the first match as "the"
    task unless it is the only one.
    """
    text = f"{goal.get('title') or ''}\n{goal.get('description') or ''}"
    out: List[tuple] = []
    seen: set = set()
    for m in _GOAL_TASK_PHRASE_RE.finditer(text):
        pair = (m.group(2), int(m.group(1)))
        if pair not in seen:
            seen.add(pair)
            out.append(pair)
    for m in _GOAL_TASK_URL_RE.finditer(text):
        pair = (m.group(1), int(m.group(2)))
        if pair not in seen:
            seen.add(pair)
            out.append(pair)
    return out


def items_from_goals(goals: Sequence[Dict[str, Any]]) -> List[Item]:
    """Goals waiting on a person become items too.

    One list means one list: a question amebo is holding is work needing this
    human just as much as a dated task is, and it used to live on its own page.
    A goal has no date, so it ranks in the judged half, and its links come out of
    its description the same way a story's do.
    """
    items: List[Item] = []
    for goal in goals:
        title = (goal.get("title") or "").strip() or "(untitled)"
        text = goal.get("description") or ""
        links = [Link(_short(u), u) for u in _URL_RE.findall(text)]
        waiting = goal.get("status") == "waiting_user"
        # A question already asked of this person outranks a goal that is merely
        # queued, and a queued goal with no trigger can never fire on its own,
        # which is worth saying on the row rather than leaving it to look idle.
        if waiting:
            reason = Reason("waiting on you", "judgement")
        elif not (goal.get("trigger_config") or {}).get("type"):
            reason = Reason("no trigger", "judgement")
        else:
            reason = Reason("queued", "judgement")
        items.append(Item(
            subject=f"goal:{goal.get('id')}",
            title=title,
            reason=reason,
            # Above every other judged item: it is a question already asked of
            # this person, so nothing else judged should sit on top of it.
            rank=JUDGED_CEILING if waiting else JUDGED_CEILING - 100,
            links=links,
            quote=None,
            due=None,
            assignee=None,
            past=False,
        ))
    return items


def _comments_for(store: Any, story_ids: Sequence[Any]) -> Dict[Any, Dict[str, str]]:
    """The last word on each story, asked for together when the store can do
    that and one at a time when it cannot — a fake store in a test implements
    only ``last_comment``, and a missing comment must never cost a row."""
    ids = [i for i in story_ids if i]
    if not ids:
        return {}
    batch = getattr(store, "last_comments", None)
    if callable(batch):
        try:
            return batch(ids)
        except Exception as exc:  # noqa: BLE001
            logger.debug("work_list: batch comment fetch failed: %s", exc)
    out: Dict[Any, Dict[str, str]] = {}
    for story_id in ids:
        try:
            comment = store.last_comment(story_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("work_list: no comments for %s: %s", story_id, exc)
            continue
        if comment:
            out[story_id] = comment
    return out


@dataclass
class WorkList:
    live: List[Item] = field(default_factory=list)
    past: List[Item] = field(default_factory=list)


def build_crm_item(activity: Dict[str, Any], *, today: date,
                   record_url: str,
                   message: Optional[Dict[str, str]] = None) -> Item:
    """One scheduled follow-up becomes one card.

    It is dated by construction, so it ranks on the same clock as a story: a
    call due tomorrow sits beside a task due tomorrow, which is the whole point
    of one list. The record it hangs off — the person or company — is the link,
    and the last thing anyone actually said on that record is the headline.
    """
    due = activity.get("date_deadline") or None
    reason = clock_reason(due, today) or Reason("no date", "judgement")
    rank = clock_rank(due, today) if due else JUDGED_CEILING - 200
    who = activity.get("user_id")
    name = who[1] if isinstance(who, (list, tuple)) and len(who) > 1 else None

    quote = None
    if message and message.get("text"):
        quote = Quote(who=message.get("who") or "someone",
                      text=message["text"][:400],
                      url=message.get("url") or record_url)

    record = (activity.get("res_name") or "").strip()
    return Item(
        subject=f"crm:activity/{activity.get('id')}",
        title=(activity.get("summary") or "").strip() or record or "(follow-up)",
        reason=reason,
        rank=rank,
        links=[Link(record or "in the CRM", record_url)] if record_url else [],
        quote=quote,
        due=due,
        assignee=name,
        past=bool(due and _is_past(due, today)),
    )


def assemble_crm(activities: Sequence[Dict[str, Any]], store: Any, *,
                 today: Optional[date] = None,
                 viewer_uids: Optional[Sequence[int]] = None) -> WorkList:
    """Scheduled CRM follow-ups, filtered to the viewer, ranked on the clock.

    ``viewer_uids`` are the Odoo user ids of the person reading — ids, never
    names, because two accounts in this CRM both read "Golda Velez" and
    matching on the name would hand one person the other's follow-ups.

    Plural because one human can hold more than one account in the same system
    (here: an ``admin`` login and a named one), and work scheduled on either is
    still theirs. Empty (nobody mapped this login) filters nothing out, matching
    how the board source treats an unmapped viewer: too much beats an empty page.
    """
    from src.services.work_list_crm import form_url

    today = today or date.today()
    wanted = set(viewer_uids or ())
    mine = [a for a in activities
            if not wanted or _activity_uid(a) in (None, *wanted)]

    # One message lookup per model, not per row.
    quotes: Dict[str, Dict[int, Dict[str, str]]] = {}
    by_model: Dict[str, List[int]] = {}
    for a in mine:
        model = a.get("res_model")
        if model and a.get("res_id"):
            by_model.setdefault(model, []).append(a["res_id"])
    for model, ids in by_model.items():
        try:
            quotes[model] = store.last_messages(model, ids)
        except Exception as exc:  # noqa: BLE001 - the quote is a nicety
            logger.debug("work_list: no CRM messages for %s: %s", model, exc)
            quotes[model] = {}

    live: List[Item] = []
    past: List[Item] = []
    for a in mine:
        model, rid = a.get("res_model"), a.get("res_id")
        url = form_url(model, rid) if model and rid else ""
        item = build_crm_item(a, today=today, record_url=url,
                              message=quotes.get(model, {}).get(rid))
        (past if item.past else live).append(item)

    live.sort(key=lambda i: (-i.rank, i.title))
    past.sort(key=lambda i: (i.due or "", i.title))
    return WorkList(live=live, past=past)


# Where an engaged-but-unscheduled CRM record sits in the judged half. Below a
# question amebo is holding for you (JUDGED_CEILING) because a person waiting on
# an answer beats a record waiting on a next step, and well clear of the clock
# band, because none of this is dated.
OPEN_CONTEXT_FLOOR = 400.0
OPEN_CONTEXT_STAGE_STEP = 60.0   # each stage further along is more real
OPEN_CONTEXT_QUIET_CAP = 180.0   # past six months quiet, longer stops meaning more


def _quiet_days(stamp: Optional[str], today: date) -> Optional[int]:
    """Days since the record last moved. Odoo writes '2026-03-03 12:00:00'; only
    the date half matters here."""
    if not stamp:
        return None
    try:
        return max(0, (today - date.fromisoformat(str(stamp)[:10])).days)
    except ValueError:
        return None


def build_open_context_item(lead: Dict[str, Any], *, today: date,
                            stage_rank: Dict[int, int],
                            message: Optional[Dict[str, str]] = None) -> Item:
    """An opportunity someone engaged and then left without a next step.

    It has no date, so it cannot rank on the clock. What stands in for one: how
    far along it is (a record at 'Connected' has more waiting on it than one at
    'Reached Out') and how long it has been quiet. Both are stated in the label,
    because a judged rank has to justify itself.
    """
    stage = lead.get("stage_id")
    stage_id = stage[0] if isinstance(stage, (list, tuple)) and stage else None
    stage_name = (stage[1] if isinstance(stage, (list, tuple)) and len(stage) > 1
                  else "")
    quiet = _quiet_days(lead.get("date_last_stage_update"), today)

    rank = OPEN_CONTEXT_FLOOR
    rank += OPEN_CONTEXT_STAGE_STEP * stage_rank.get(stage_id, 0)
    rank += min(float(quiet or 0), OPEN_CONTEXT_QUIET_CAP)
    rank = min(JUDGED_CEILING - 1.0, rank)

    if quiet is None:
        label = f"{stage_name.lower()}, nothing scheduled".strip(", ")
    else:
        label = f"{stage_name.lower()}, nothing scheduled for {quiet} days"

    partner = lead.get("partner_id")
    partner_name = (partner[1] if isinstance(partner, (list, tuple))
                    and len(partner) > 1 else None)

    links = [Link(label=partner_name or "the record",
                  url=_crm_form_url("crm.lead", lead.get("id")))]

    return Item(
        subject=f"crm:lead/{lead.get('id')}",
        title=(lead.get("name") or "").strip() or partner_name or "(opportunity)",
        reason=Reason(label.strip(", "), "judgement"),
        rank=rank,
        links=links,
        quote=(Quote(who=message["who"], text=message["text"],
                     url=message.get("url")) if message else None),
        due=None,
        assignee=_odoo_name(lead.get("user_id")),
    )


def assemble_crm_open_context(leads: Sequence[Dict[str, Any]], store: Any, *,
                              today: Optional[date] = None,
                              viewer_uids: Optional[Sequence[int]] = None,
                              stage_names: Optional[Dict[int, str]] = None
                              ) -> List[Item]:
    """Engaged opportunities with no next step, filtered to the viewer.

    Same viewer rule as the follow-up source: ids not names, and an unowned
    record stays on every list because it is waiting on whoever picks it up.
    Nothing here is dated, so nothing here can be past — it all comes back as
    one live list.
    """
    today = today or date.today()
    wanted = set(viewer_uids or ())
    mine = [l for l in leads
            if not wanted or _odoo_uid(l.get("user_id")) in (None, *wanted)]
    if not mine:
        return []

    # Further along the pipeline ranks higher. The order comes from the CRM's own
    # stage sequence, so adding a stage in Odoo does not need a change here.
    ordered = sorted((stage_names or {}).keys())
    stage_rank = {sid: i for i, sid in enumerate(ordered)}

    # The person's own last words, read off the contact the opportunity hangs on
    # — a lead record carries no chatter of its own. One query for the page.
    quotes: Dict[int, Dict[str, str]] = {}
    partner_ids = [_odoo_uid(l.get("partner_id")) for l in mine]
    partner_ids = [p for p in partner_ids if p]
    if partner_ids:
        try:
            quotes = store.last_messages("res.partner", partner_ids)
        except Exception as exc:  # noqa: BLE001 - the quote is a nicety
            logger.debug("work_list: no CRM messages for contacts: %s", exc)

    items = [build_open_context_item(
                l, today=today, stage_rank=stage_rank,
                message=quotes.get(_odoo_uid(l.get("partner_id"))))
             for l in mine]
    items.sort(key=lambda i: (-i.rank, i.title))
    return items


def _crm_form_url(model: str, record_id: Any) -> str:
    from src.services.work_list_crm import form_url
    return form_url(model, record_id)


def _odoo_name(rel: Any) -> Optional[str]:
    """The display half of an Odoo relation, or None when it is unset. Odoo
    returns an empty relation as ``False``."""
    if isinstance(rel, (list, tuple)) and len(rel) > 1:
        return rel[1]
    return None


def _odoo_uid(rel: Any) -> Optional[int]:
    """The id half of an Odoo relation. ``False`` is an int in Python, so the
    bool has to be ruled out first or an unset relation reads as id 0."""
    if isinstance(rel, bool) or rel is None:
        return None
    if isinstance(rel, (list, tuple)):
        return rel[0] if rel else None
    return rel if isinstance(rel, int) else None


def _activity_uid(activity: Dict[str, Any]) -> Optional[int]:
    """The Odoo user id on a follow-up, or None when it has no owner.

    Odoo returns an empty relation as ``False``, and in Python ``False`` is an
    int — so the bool has to be ruled out first or an unowned follow-up reads
    as user 0 and falls off everybody's list.
    """
    who = activity.get("user_id")
    if isinstance(who, bool) or who is None:
        return None
    if isinstance(who, (list, tuple)):
        return who[0] if who else None
    return who if isinstance(who, int) else None


def parse_subject(key: str) -> Optional[tuple]:
    """'business-development-june-july#34' -> ('business-development-june-july', 34)."""
    if "#" not in key:
        return None
    slug, _, ref = key.rpartition("#")
    try:
        return slug, int(ref)
    except ValueError:
        return None


def assemble_stories(stories: Sequence[Dict[str, Any]], store: Any, *,
                     taiga_host: str, today: Optional[date] = None,
                     agent_username: Optional[str] = None,
                     viewer_username: Optional[str] = None) -> WorkList:
    """Build the list straight from stories already in hand.

    The list's real source: every open story with a due date. Sourcing only from
    drafted deadline pings meant the list emptied out the moment those were
    handled, which is not what "what needs you" means.

    ``agent_username`` is amebo's own Taiga account. Work handed to amebo is not
    work waiting on a person, so it never appears on a person's list — putting a
    batch of them on the board is what filled Golda's up.

    ``viewer_username`` is the person reading. Given one, the list is theirs:
    what they own, plus what nobody owns yet (which is waiting on whoever picks
    it up). Someone else's task is their business, not yours. Without one —
    nobody mapped this login — the list is not filtered at all, because a list
    that has silently hidden everything looks broken rather than tidy.
    """
    today = today or date.today()
    live: List[Item] = []
    past: List[Item] = []
    skipped_blocked: List[str] = []
    handed_over = 0
    someone_elses = 0

    # Which stories survive the filters, before anything is asked about them.
    # Their comments are then fetched together rather than one story at a time,
    # which was the slowest thing about opening the list.
    kept: List[tuple] = []
    for story in stories:
        if (story.get("status_extra_info") or {}).get("is_closed"):
            continue
        owner = _display_name(story, "assigned_to")
        if agent_username and owner == agent_username:
            handed_over += 1
            continue
        if viewer_username and owner and owner != viewer_username:
            someone_elses += 1
            continue
        slug = store.project_slug_of(story)
        if not slug:
            continue
        # Taiga refuses every write to a blocked board (an iceboxed project),
        # so nothing here can be acted on. A row you cannot act on does not
        # belong in a list of what needs you.
        if getattr(store, "project_blocked", None) and store.project_blocked(slug):
            skipped_blocked.append(slug)
            continue
        kept.append((story, slug))

    comments = _comments_for(store, [s.get("id") for s, _ in kept])
    for story, slug in kept:
        item = build_item(story, project_slug=slug, taiga_host=taiga_host,
                          today=today, comment=comments.get(story.get("id")))
        (past if item.past else live).append(item)
    if skipped_blocked:
        # Never a silent drop: say what was left out and why.
        logger.info("work_list: %d stories skipped on blocked boards (%s)",
                    len(skipped_blocked), ", ".join(sorted(set(skipped_blocked))))
    if handed_over:
        logger.info("work_list: %d stories held off the list, assigned to %s",
                    handed_over, agent_username)
    if someone_elses:
        logger.info("work_list: %d stories belong to someone other than %s",
                    someone_elses, viewer_username)
    live.sort(key=lambda i: (-i.rank, i.title))
    past.sort(key=lambda i: (i.due or "", i.title))
    return WorkList(live=live, past=past)


def assemble(keys: Sequence[str], store: StoryStore, *, taiga_host: str,
             today: Optional[date] = None) -> WorkList:
    """Resolve each 'slug#ref' to a story, build an item, rank, and split what
    went past out of the live list. A key that will not resolve is dropped with
    a log line rather than failing the whole list."""
    today = today or date.today()
    live: List[Item] = []
    past: List[Item] = []

    for key in keys:
        parsed = parse_subject(key)
        if not parsed:
            logger.warning("work_list: cannot parse subject %r", key)
            continue
        slug, ref = parsed
        try:
            story = store.story(slug, ref)
        except Exception as exc:                      # noqa: BLE001 - one bad story
            logger.warning("work_list: %s#%s unreadable: %s", slug, ref, exc)
            continue
        if not story:
            continue
        if (story.get("status_extra_info") or {}).get("is_closed"):
            # Closed or archived elsewhere (Marten, Taiga) — not live work,
            # whatever the drafts still say.
            continue
        comment = None
        try:
            comment = store.last_comment(story["id"])
        except Exception as exc:                      # noqa: BLE001
            logger.debug("work_list: no comments for %s#%s: %s", slug, ref, exc)
        item = build_item(story, project_slug=slug, taiga_host=taiga_host,
                          today=today, comment=comment)
        (past if item.past else live).append(item)

    live.sort(key=lambda i: (-i.rank, i.title))
    past.sort(key=lambda i: (i.due or "", i.title))
    return WorkList(live=live, past=past)
