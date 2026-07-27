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
        self.host = (host or os.getenv("TAIGA_UI_URL")
                     or os.getenv("TAIGA_URL", "https://taiga.linkedtrust.us")).rstrip("/")

    def story(self, project_slug: str, ref: int) -> Optional[Dict[str, Any]]:
        """A ref is only unique within a project, so resolve through the project
        slug rather than guessing a global id."""
        resolved = self._client._get(
            f"/api/v1/resolve?project={project_slug}&us={ref}")
        story_id = (resolved or {}).get("us")
        if not story_id:
            return None
        return self._client._get(f"/api/v1/userstories/{story_id}")

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
