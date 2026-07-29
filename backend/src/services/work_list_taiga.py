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
from typing import Any, Dict, List, Optional

from src.services.followup_claw import TaigaClient

logger = logging.getLogger(__name__)


class TaigaStoryStore:
    """Resolve 'slug#ref' to a story and find the most recent thing a person
    actually said on it."""

    def __init__(self, client: Optional[TaigaClient] = None,
                 host: Optional[str] = None):
        self._client = client or TaigaClient()
        self._projects: Dict[str, Optional[int]] = {}
        self._slugs: Dict[int, Optional[str]] = {}
        self._blocked: Dict[str, bool] = {}
        self.host = (host or os.getenv("TAIGA_UI_URL")
                     or os.getenv("TAIGA_URL", "https://taiga.linkedtrust.us")).rstrip("/")

    def project_id(self, slug: str) -> Optional[int]:
        """Slug -> id, cached for the life of the request. Taiga's /resolve
        endpoint is not available on this deployment, so the lookup goes through
        by_slug and the id is reused for every story in the same project."""
        if slug in self._projects:
            return self._projects[slug]
        try:
            project = self._client._get(f"/api/v1/projects/by_slug?slug={slug}")
        except Exception as exc:  # noqa: BLE001 - unknown slug is a 404, not a crash
            logger.debug("work_list: no project %r: %s", slug, exc)
            project = None
        pid = (project or {}).get("id")
        self._projects[slug] = pid
        return pid

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
        pid = self.project_id(project_slug)
        if not pid:
            return []
        return self._client._get(f"/api/v1/userstory-statuses?project={pid}") or []

    def open_dated_stories(self, page_size: int = 200) -> List[Dict[str, Any]]:
        """Every open story with a due date, across the boards amebo can see.

        This is the list's real source. Sourcing only from drafted deadline
        pings meant the list emptied out the moment those were dealt with, which
        is not what "what needs you" means.

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
            out.extend(s for s in batch if s.get("due_date"))
            if not batch or len(batch) < page_size or (total and page * page_size >= total):
                break
            page += 1
        return out

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
        self._projects[slug] = pid
        return slug

    def project_blocked(self, project_slug: str) -> bool:
        """True when Taiga has the whole board blocked (``blocked_code``, e.g.
        an iceboxed project). Taiga refuses every write to such a board, so its
        stories cannot be acted on at all — which is why they do not belong in a
        list of what needs a person.
        """
        if project_slug in self._blocked:
            return self._blocked[project_slug]
        try:
            project = self._client._get(
                f"/api/v1/projects/by_slug?slug={project_slug}") or {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("work_list: cannot read project %r: %s", project_slug, exc)
            project = {}
        blocked = bool(project.get("blocked_code") or project.get("is_blocked"))
        self._blocked[project_slug] = blocked
        return blocked

    def members(self, project_slug: str) -> List[Dict[str, Any]]:
        """Who can be assigned on this board, so the assignee control offers the
        real people rather than a free-text box that fails on a typo."""
        pid = self.project_id(project_slug)
        if not pid:
            return []
        return self._client._get(f"/api/v1/projects/{pid}") .get("members", []) or []

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
