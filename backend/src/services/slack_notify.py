"""Post a claw's one line to Slack.

The dispatcher's notifier used to be a logger unless somebody plugged a Slack
adapter in at construction time, and nobody ever did (goal_scheduler.py and
routes/goals.py both build ``GoalDispatcher()`` bare). So every "goal
completed" and every alert went to the journal and no human saw one
(golda 2026-09-06: "the system is completely failing ... nobody uses it").

A channel is ``slack:#name``, ``#name`` or a bare id like ``C0A3UGN864D``.
Names resolve through the bot's own channel list, cached for the process.
The token comes from the same place the slack_post tool gets it.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[CGD][A-Z0-9]{8,}$")
_cache: Dict[str, str] = {}
_lock = threading.Lock()


def looks_like_slack(channel: Optional[str]) -> bool:
    c = (channel or "").strip()
    return bool(c) and (c.startswith("slack:") or c.startswith("#")
                        or bool(_ID_RE.match(c)))


def _token() -> str:
    from src.tools.slack_tools import _bot_token
    return _bot_token(None)


def resolve_channel(channel: str, token: Optional[str] = None) -> Optional[str]:
    """``slack:#name`` / ``#name`` -> channel id via the bot's channel list;
    an id passes through. None when the bot cannot see such a channel."""
    c = channel.strip()
    if c.startswith("slack:"):
        c = c[len("slack:"):]
    if _ID_RE.match(c):
        return c
    name = c.lstrip("#").strip()
    if not name:
        return None
    with _lock:
        if name in _cache:
            return _cache[name]
    token = token or _token()
    cursor = ""
    for _ in range(10):
        resp = requests.get(
            "https://slack.com/api/conversations.list",
            params={"types": "public_channel,private_channel", "limit": 500,
                    "exclude_archived": "true", "cursor": cursor},
            headers={"Authorization": f"Bearer {token}"}, timeout=15)
        body = resp.json()
        if not body.get("ok"):
            logger.warning("slack_notify: conversations.list: %s", body.get("error"))
            return None
        with _lock:
            for ch in body.get("channels", []):
                _cache[ch["name"]] = ch["id"]
        if name in _cache:
            return _cache[name]
        cursor = (body.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
    return None


def post(channel: str, message: str) -> bool:
    """One message, no mention, no formatting beyond what was given. False on
    any failure, logged; the caller treats that as 'nobody heard'."""
    try:
        token = _token()
        cid = resolve_channel(channel, token)
        if not cid:
            logger.warning("slack_notify: no channel for %r", channel)
            return False
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            json={"channel": cid, "text": message},
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json; charset=utf-8"},
            timeout=15)
        body = resp.json()
        if not body.get("ok"):
            logger.warning("slack_notify: post to %s failed: %s", cid, body.get("error"))
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - a notify must never take the claw down
        logger.warning("slack_notify: %s", exc)
        return False
