"""amebo posts only in channels, never in a direct message.

One check every Slack send path calls. A user id (U/W), a DM id (D), an
``@name`` target, or a conversation Slack reports as an IM or group DM is
refused. Unknown is refused too: a post that cannot be confirmed to land in
a channel does not go out.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_DM_ID_RE = re.compile(r"^[DUW][A-Z0-9]{8,}$")
_CHANNEL_ID_RE = re.compile(r"^[CG][A-Z0-9]{8,}$")

REFUSAL = "refused: amebo posts only in channels, never in a direct message"


def is_dm_target(channel: str, token: Optional[str] = None) -> bool:
    """True when posting to ``channel`` would land in a DM or group DM, or
    when that cannot be ruled out."""
    c = (channel or "").strip()
    if c.startswith("slack:"):
        c = c[len("slack:"):]
    if not c or c.startswith("@") or _DM_ID_RE.match(c):
        return True
    if c.startswith("#"):
        return False
    if not _CHANNEL_ID_RE.match(c):
        return True
    if not token:
        return c.startswith("G")
    try:
        body = requests.get(
            "https://slack.com/api/conversations.info",
            params={"channel": c},
            headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("slack_no_dm: conversations.info %s: %s", c, exc)
        return True
    if not body.get("ok"):
        logger.warning("slack_no_dm: conversations.info %s: %s", c, body.get("error"))
        return True
    ch = body.get("channel") or {}
    return bool(ch.get("is_im") or ch.get("is_mpim"))


def is_dm_channel_id(channel: str) -> bool:
    """Offline check for inbound events: a D id is a DM."""
    return bool(re.match(r"^D[A-Z0-9]{8,}$", (channel or "").strip()))
