"""Taiga-backed StoryStore for the work list.

Kept apart from ``work_list`` on purpose: the list's ranking rules are pure and
testable with a fake store, and every vendor detail (Taiga's resolve endpoint,
its history format) lives here in the leaf. Reuses the TaigaClient the deadline
follow-up claw already authenticates with, so there is one Taiga credential path,
not two.

Only reads. Writes a human presses go through the registered executors in
src/tools/gated_actuators.py.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Sequence

from src.services.followup_claw import TaigaClient

logger = logging.getLogger(__name__)


class TaigaStoryStore:
    """Resolve 'slug#ref' to a story and find the most recent thing a person
    actually said on it."""

    def __init__(self, client: Optional[TaigaClient] = None,
                 host: Optional[str] = None):
        self._client = client or TaigaClient()
        self._payloads: Dict[str, Optional[Dict[str, Any]]] = {}
        self._slugs: Dict[int, Optional[str]] = {}
        # Filled by prime_slugs() from one listing: the slugs of boards Taiga
        # has blocked, which is all the list loop needs to know about them.
        self._blocked: set = set()
        self._primed = False
        # Where a person is sent to see a story: Marten, never Taiga's own
        # interface. Golda: "NO links that way only marten interface svelte
        # good, taiga interface NO."
        self.host = (host or os.getenv("MARTEN_URL")
                     or "https://marten.linkedtrust.us").rstrip("/")

    def project(self, slug: str) -> Optional[Dict[str, Any]]:
        """The project's full record, fetched once per store. by_slug carries the
        id, blocked_code, us_statuses and members together, so the detail sheet
        costs one project call instead of one per question asked of it. Taiga's
        /resolve endpoint is not available on this deployment."""
        if slug in self._payloads:
            return self._payloads[slug]
        try:
            payload = self._client._get(f"/api/v1/projects/by_slug?slug={slug}")
        except Exception as exc:  # noqa: BLE001 - unknown slug is a 404, not a crash
            logger.debug("work_list: no project %r: %s", slug, exc)
            payload = None
        self._payloads[slug] = payload
        return payload

    def project_id(self, slug: str) -> Optional[int]:
        return (self.project(slug) or {}).get("id")

    def story(self, project_slug: str, ref: int) -> Optional[Dict[str, Any]]:
        """A ref is only unique within a project, so the project is part of the
        lookup — never a bare global id."""
        pid = self.project_id(project_slug)
        if not pid:
            return None
        # by_ref, not a ?ref= filter: the list endpoint ignores ref and would
        # hand back the project's first story instead of the one asked for.
        return self._client._get(
            f"/api/v1/userstories/by_ref?project={pid}&ref={ref}")

    def statuses(self, project_slug: str) -> List[Dict[str, Any]]:
        """The project's own status names, in board order, so the dropdown shows
        what Marten shows rather than a list amebo made up."""
        return (self.project(project_slug) or {}).get("us_statuses") or []

    def open_stories(self, page_size: int = 200) -> List[Dict[str, Any]]:
        """Every open story across the boards amebo can see, dated or not.

        This is the list's real source. Sourcing only from drafted deadline
        pings meant the list emptied out the moment those were dealt with, which
        is not what "what needs you" means. Undated stories come back too —
        Golda: it goes in the list even if it has no date — and who they belong
        on is decided when the list is assembled, not here.

        Taiga paginates at 30 by default and reports the true total in
        ``x-pagination-count``; ask for a bigger page and walk until the count is
        met, so nothing is silently cut off at page one.
        """
        out: List[Dict[str, Any]] = []
        page = 1
        while True:
            batch, total = self._client._get_paged(
                f"/api/v1/userstories?status__is_closed=false"
                f"&page_size={page_size}&page={page}")
            out.extend(batch)
            if not batch or len(batch) < page_size or (total and page * page_size >= total):
                break
            page += 1
        return out

    def open_dated_stories(self, page_size: int = 200) -> List[Dict[str, Any]]:
        """Only the stories somebody put a date on. Kept because a caller that
        wants deadlines and nothing else should say so rather than filter."""
        return [s for s in self.open_stories(page_size) if s.get("due_date")]

    def prime_slugs(self) -> None:
        """Learn every project's slug in one call.

        Without this, naming the board a story sits on costs a request per
        board, made one after another while the page waits. Taiga will list all
        the projects amebo can see at once, so it is asked once.

        Only the two facts the list itself needs are taken from that call — the
        slug, and whether the board is blocked. NOT the whole record: the list
        endpoint leaves out ``us_statuses``, so caching its lighter payload as
        if it were the full one would leave the detail sheet with no statuses
        and the archive action reporting a board has nowhere to archive to.

        Fail-soft: if the list will not load, everything still resolves one at a
        time, just slowly.
        """
        if self._primed:
            return
        try:
            projects = self._client._get("/api/v1/projects") or []
        except Exception as exc:  # noqa: BLE001
            logger.debug("work_list: could not list projects: %s", exc)
            return
        for project in projects:
            slug = project.get("slug")
            if project.get("id") is not None:
                self._slugs[project["id"]] = slug
            if slug and project.get("blocked_code"):
                self._blocked.add(slug)
        self._primed = True

    def project_slug_of(self, story: Dict[str, Any]) -> Optional[str]:
        """The slug for a story's project, cached, so building an item does not
        cost one API call per row."""
        pid = story.get("project")
        if pid is None:
            return None
        if pid in self._slugs:
            return self._slugs[pid]
        project = self._client._get(f"/api/v1/projects/{pid}") or {}
        slug = project.get("slug")
        self._slugs[pid] = slug
        if slug:
            self._payloads[slug] = project
        return slug

    def project_blocked(self, project_slug: str) -> bool:
        """True when Taiga has the whole board blocked (``blocked_code``, e.g.
        an iceboxed project). Taiga refuses every write to such a board, so its
        stories cannot be acted on at all — which is why they do not belong in a
        list of what needs a person.
        """
        if self._primed:
            return project_slug in self._blocked
        project = self.project(project_slug) or {}
        return bool(project.get("blocked_code") or project.get("is_blocked"))

    def members(self, project_slug: str) -> List[Dict[str, Any]]:
        """Who can be assigned on this board, so the assignee control offers the
        real people rather than a free-text box that fails on a typo."""
        return (self.project(project_slug) or {}).get("members") or []

    def archived_status(self, project_slug: str) -> Optional[str]:
        """The board's archive status, by its own flag — not by guessing a name.
        None when the board has no archived status, in which case the caller must
        not silently do something else instead."""
        for st in self.statuses(project_slug):
            if st.get("is_archived"):
                return st.get("name")
        return None

    def delete(self, story_id: int) -> None:
        """Irreversible. No CLI covers this, so it is a direct REST call, and the
        route only reaches it behind an explicit confirm."""
        self._client._request("DELETE", f"/api/v1/userstories/{story_id}")

    def comments(self, story_id: int) -> List[Dict[str, str]]:
        """Every human comment on the story, oldest first — the thread.

        Taiga returns history newest-first and mixes field edits in with speech;
        entries with no ``comment`` are edits, not words, and are dropped.
        """
        history = self._client._get(f"/api/v1/history/userstory/{story_id}") or []
        out: List[Dict[str, str]] = []
        for entry in history:
            text = (entry.get("comment") or "").strip()
            if not text or entry.get("delete_comment_date"):
                continue
            user = entry.get("user") or {}
            out.append({
                "who": user.get("name") or user.get("username") or "someone",
                "text": text,
                "when": (entry.get("created_at") or "")[:10] or None,
            })
        out.reverse()
        return out

    # Taiga keeps history per story, so there is no one call that fetches the
    # last word on thirty of them. Asked one after another that was the slowest
    # part of opening the list; asked together it is one round trip's worth of
    # waiting. Bounded because Taiga is shared with the rest of the team and a
    # list refresh must not read as a burst of load to them.
    _COMMENT_FETCHERS = 8

    def last_comments(self, story_ids: Sequence[int]) -> Dict[int, Dict[str, str]]:
        """{story_id -> its newest human comment}, fetched together.

        A story whose history will not load is left out rather than failing the
        list: the row is still real work, it just leads with its own title.
        """
        ids = [i for i in dict.fromkeys(story_ids) if i]
        if not ids:
            return {}
        out: Dict[int, Dict[str, str]] = {}
        with ThreadPoolExecutor(max_workers=min(self._COMMENT_FETCHERS, len(ids))) as pool:
            for story_id, comment in zip(ids, pool.map(self._safe_comment, ids)):
                if comment:
                    out[story_id] = comment
        return out

    def _safe_comment(self, story_id: int) -> Optional[Dict[str, str]]:
        try:
            return self.last_comment(story_id)
        except Exception as exc:  # noqa: BLE001 - one unreadable history
            logger.debug("work_list: no comments for %s: %s", story_id, exc)
            return None

    def last_comment(self, story_id: int) -> Optional[Dict[str, str]]:
        """The newest human comment on the story, or None.

        Taiga's history mixes field changes and comments in one feed; entries
        with an empty ``comment`` are edits, not speech, and are skipped. Amebo's
        own service account is skipped too — the list leads with a person's
        words, never with the agent's.
        """
        history = self._client._get(f"/api/v1/history/userstory/{story_id}") or []
        me = (os.getenv("TAIGA_USERNAME") or "").lower()
        for entry in history:                      # newest first
            text = (entry.get("comment") or "").strip()
            if not text or entry.get("delete_comment_date"):
                continue
            user = entry.get("user") or {}
            who = user.get("name") or user.get("username") or "someone"
            if me and who.lower() == me:
                continue
            return {"who": who, "text": text}
        return None
