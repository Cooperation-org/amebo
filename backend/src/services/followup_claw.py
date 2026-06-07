"""Deadline-day follow-up claw.

On a task's due date, draft a gated Slack ping naming the assignee AND the task
creator so they sort out whether it's getting done. Simplified per Golda:
no auto-reassign, no multi-stage escalation — just the deadline-day nudge, and
"let them figure it out."

Discipline:
- All outbound is a gated draft (slack_post via the draft-approval gate) — nothing
  posts without a human approving.
- The escalation target (creator) is read from the task's owner, never hardcoded.
- Dedup is by the amebo pending_actions table (payload.followup_task + same day),
  so a task is pinged at most once on its deadline day even if the claw re-runs.
- The notify channel is injected config, never hardcoded.

The Taiga read/auth is a small REST client (TaigaClient) using amebo's own
service credentials from the environment (TAIGA_USERNAME / TAIGA_PASSWORD), the
same ones mcp-taiga uses. It is injected so tests can pass a fake.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Minimal Taiga REST client (read + identity), amebo's own service account
# ---------------------------------------------------------------------------


class TaigaClient:
    """Just enough Taiga REST for the follow-up claw: log in, list a project's
    open stories, and resolve a user id to a display name."""

    def __init__(self, host: Optional[str] = None,
                 username: Optional[str] = None, password: Optional[str] = None):
        self.host = (host or os.getenv("TAIGA_URL", "https://taiga.linkedtrust.us")).rstrip("/")
        self._user = username or os.getenv("TAIGA_USERNAME")
        self._pass = password or os.getenv("TAIGA_PASSWORD")
        self._token: Optional[str] = None

    def _login(self) -> str:
        if not self._user or not self._pass:
            raise RuntimeError("TAIGA_USERNAME / TAIGA_PASSWORD not configured")
        data = json.dumps({"type": "normal", "username": self._user,
                           "password": self._pass}).encode()
        req = urllib.request.Request(self.host + "/api/v1/auth", data=data,
                                     headers={"Content-Type": "application/json"})
        self._token = json.loads(urllib.request.urlopen(req, timeout=15).read())["auth_token"]
        return self._token

    def _get(self, path: str) -> Any:
        if not self._token:
            self._login()
        req = urllib.request.Request(self.host + path,
                                     headers={"Authorization": f"Bearer {self._token}"})
        return json.loads(urllib.request.urlopen(req, timeout=20).read())

    def open_stories(self, project_id: int) -> List[Dict]:
        """Open (not closed) user stories for a project."""
        return self._get(f"/api/v1/userstories?project={project_id}&status__is_closed=false")

    def member_project_ids(self) -> List[int]:
        """Projects amebo is a member of."""
        return [p["id"] for p in self._get("/api/v1/projects?member=" + str(self._me_id()))]

    def _me_id(self) -> int:
        return self._get("/api/v1/users/me")["id"]


# ---------------------------------------------------------------------------
# The claw
# ---------------------------------------------------------------------------


def _display_name(story: Dict, key: str) -> Optional[str]:
    """Pull a username/full_name from a story's *_extra_info, or None."""
    info = story.get(f"{key}_extra_info") or {}
    return info.get("username") or info.get("full_name")


def build_ping(story: Dict) -> str:
    """The deadline-day message. Names the assignee and the creator and asks
    them to sort it out. (@-mentions need a Taiga→Slack id map — future; for now
    we name people in text.)"""
    ref = story.get("ref")
    subject = story.get("subject", "(untitled)")
    assignee = _display_name(story, "assigned_to") or "unassigned"
    creator = _display_name(story, "owner") or "unknown"
    due = story.get("due_date")
    return (
        f"⏰ Task #{ref} *{subject}* is due today ({due}).\n"
        f"• Assignee: {assignee}\n"
        f"• Created by: {creator}\n"
        f"{assignee} — are you on this? {creator} — heads up; you two figure out "
        f"whether it ships today or needs a new plan."
    )


def followup_key(project_slug: str, ref: Any) -> str:
    return f"{project_slug}#{ref}"


def run_deadline_followups(
    org_id: int,
    channel: str,
    *,
    taiga: Optional[TaigaClient] = None,
    project_ids: Optional[List[int]] = None,
    gate=None,
    already_pinged=None,
    today: Optional[str] = None,
) -> Dict[str, Any]:
    """Find tasks due today across the given projects and draft one gated Slack
    ping per task (assignee + creator). Returns a summary dict.

    Injectable: ``taiga`` (TaigaClient or fake), ``gate`` (a callable
    ``(channel, text, followup_task) -> result`` — defaults to the real gated
    actuator), ``already_pinged`` (``key -> bool`` dedup — defaults to the
    pending_actions check). ``today`` defaults to the real date.
    """
    if not channel:
        logger.warning("followup_claw: no notify channel configured; skipping.")
        return {"drafted": 0, "skipped": 0, "reason": "no_channel"}

    taiga = taiga or TaigaClient()
    today = today or date.today().isoformat()
    if project_ids is None:
        project_ids = taiga.member_project_ids()
    if already_pinged is None:
        already_pinged = lambda key: _already_pinged_db(org_id, key, today)
    if gate is None:
        gate = lambda channel, text, key: _draft_slack(org_id, channel, text, key)

    drafted, skipped = 0, 0
    for pid in project_ids:
        try:
            stories = taiga.open_stories(pid)
        except Exception as e:  # one bad project must not stop the sweep
            logger.warning("followup_claw: could not read project %s: %s", pid, e)
            continue
        for s in stories:
            if s.get("due_date") != today:
                continue
            slug = (s.get("project_extra_info") or {}).get("slug") or str(pid)
            key = followup_key(slug, s.get("ref"))
            if already_pinged(key):
                skipped += 1
                continue
            gate(channel, build_ping(s), key)
            drafted += 1
    logger.info("followup_claw: drafted=%s skipped=%s (channel=%s)", drafted, skipped, channel)
    return {"drafted": drafted, "skipped": skipped, "channel": channel, "date": today}


# ---------------------------------------------------------------------------
# Real implementations of the injectable bits
# ---------------------------------------------------------------------------


def _draft_slack(org_id: int, channel: str, text: str, key: str) -> str:
    """Route a deadline ping through the draft-approval gate (gated → pending).

    Goes straight to the gate (not slack_post_impl) so the payload can carry
    ``followup_task`` for same-day dedup; the post itself reuses the registered
    execute_slack_post executor, so approval posts it like any other slack draft.
    """
    from src.services.draft_approval_service import DraftApprovalService
    from src.tools.gated_actuators import execute_slack_post
    gate = DraftApprovalService()
    result = gate.gate_or_execute(
        org_id=org_id,
        action_type="slack_post",
        acting_identity=f"amebo:{org_id}",
        executor=execute_slack_post,
        target=channel,
        payload={"channel": channel, "text": text, "followup_task": key},
        preview=f"Deadline ping to {channel}: {text[:120]}",
    )
    return "drafted" if result.gated else (result.result or "executed")


def main() -> None:
    """Entry point for the daily timer. Runs the deadline sweep for every
    instance that has a ``notify_channel`` configured (config-driven: no channel
    set → nothing happens). All drafts are gated, so this is safe to run
    unattended — it never posts on its own."""
    from src.db.connection import DatabaseConnection
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT org_id, slug, config->>'notify_channel'
                   FROM instances
                   WHERE org_id IS NOT NULL
                     AND config->>'notify_channel' IS NOT NULL
                     AND config->>'notify_channel' <> ''"""
            )
            rows = cur.fetchall()
    finally:
        DatabaseConnection.return_connection(conn)

    if not rows:
        logger.info("followup_claw: no instance has notify_channel set; nothing to do.")
        return
    for org_id, slug, channel in rows:
        try:
            summary = run_deadline_followups(org_id, channel)
            logger.info("followup_claw[%s]: %s", slug, summary)
        except Exception:
            logger.exception("followup_claw failed for org %s (%s)", org_id, slug)


def _already_pinged_db(org_id: int, key: str, today: str) -> bool:
    """True if a slack_post pending_action for this task was already created
    today (any status) — so we ping once per deadline day."""
    from src.db.connection import DatabaseConnection
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM pending_actions
                WHERE org_id = %s
                  AND action_type = 'slack_post'
                  AND payload->>'followup_task' = %s
                  AND requested_at::date = %s::date
                LIMIT 1
                """,
                (org_id, key, today),
            )
            return cur.fetchone() is not None
    finally:
        DatabaseConnection.return_connection(conn)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
