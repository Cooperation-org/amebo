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


def links_from_story(story: Dict[str, Any], taiga_host: str,
                     project_slug: str) -> List[Link]:
    """The story itself, plus any URL written into its description. Links found
    in the record are NOT flagged ``found`` — that flag is for links amebo went
    and looked up, which it records in the description with its own marker."""
    ref = story.get("ref")
    links = [Link(f"#{ref} {story.get('subject', '')}".strip(),
                  f"{taiga_host}/project/{project_slug}/us/{ref}")]
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
            url=f"{taiga_host}/project/{project_slug}/us/{ref}",
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
        items.append(Item(
            subject=f"goal:{goal.get('id')}",
            title=title,
            reason=Reason("waiting on you", "judgement"),
            # Above every other judged item: it is a question already asked of
            # this person, so nothing else judged should sit on top of it.
            rank=JUDGED_CEILING,
            links=links,
            quote=None,
            due=None,
            assignee=None,
            past=False,
        ))
    return items


@dataclass
class WorkList:
    live: List[Item] = field(default_factory=list)
    past: List[Item] = field(default_factory=list)


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
                     taiga_host: str, today: Optional[date] = None) -> WorkList:
    """Build the list straight from stories already in hand.

    The list's real source: every open story with a due date. Sourcing only from
    drafted deadline pings meant the list emptied out the moment those were
    handled, which is not what "what needs you" means.
    """
    today = today or date.today()
    live: List[Item] = []
    past: List[Item] = []
    for story in stories:
        if (story.get("status_extra_info") or {}).get("is_closed"):
            continue
        slug = store.project_slug_of(story)
        if not slug:
            continue
        comment = None
        try:
            comment = store.last_comment(story["id"])
        except Exception as exc:                      # noqa: BLE001
            logger.debug("work_list: no comments for %s: %s", story.get("id"), exc)
        item = build_item(story, project_slug=slug, taiga_host=taiga_host,
                          today=today, comment=comment)
        (past if item.past else live).append(item)
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
