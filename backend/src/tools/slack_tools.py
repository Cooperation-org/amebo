"""
slack_post tool — let the claw post messages to Slack.

Hard rules:
- A `mention_user_id` is required when the goal config says so (default true).
  Posts without an @-mention to a named recipient don't produce a
  notification, which defeats the purpose of "pinging" someone.
- The bot token comes from env (`SLACK_BOT_TOKEN`). Tool refuses to run
  without it.
- Channel must be a name like `#standup` or a Slack channel ID (Cxxx).
  We pass it through; Slack rejects unknown values.
- Text length capped at 8KB to stay well under Slack's 40KB block limit.

Returned string includes the channel + ts of the posted message so the
dispatcher can record it in goal_events for traceability.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


SLACK_POST_ENDPOINT = "https://slack.com/api/chat.postMessage"
MAX_TEXT_LEN = 8 * 1024


class SlackPostError(RuntimeError):
    """Raised when Slack returns an error or the API call fails."""


def _bot_token() -> str:
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        raise SlackPostError("SLACK_BOT_TOKEN is not configured.")
    return token


def slack_post_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    channel = (tool_input.get("channel") or "").strip()
    text = tool_input.get("text") or ""
    thread_ts = tool_input.get("thread_ts")
    mention_user_id: Optional[str] = tool_input.get("mention_user_id") or None
    # WP13 attribution (I7): a caller can pass mention_person_id (a platform_users
    # id) instead of a raw Slack id; resolve it to the person's Slack handle via
    # member_tool_accounts, scoped to the acting org.
    if not mention_user_id and tool_input.get("mention_person_id"):
        oc = context.get("org_context") if isinstance(context, dict) else None
        org_id = getattr(oc, "org_id", None) or (context.get("org_id") if isinstance(context, dict) else None)
        if org_id:
            try:
                from src.db.repositories.member_tool_account_repo import MemberToolAccountRepo
                mention_user_id = MemberToolAccountRepo().slack_mention(
                    org_id, tool_input["mention_person_id"])
            except Exception:
                logger.exception("mention_person_id resolution failed")

    # Per-goal guardrail context decides whether @-mention is required.
    # Defaults to True since most "ping someone" use cases need it.
    require_mention = True
    guardrails = context.get("guardrails") if isinstance(context, dict) else None
    if guardrails is not None:
        require_mention = getattr(guardrails, "slack_require_mention", True)

    if not channel:
        return "Error: channel is required."
    if not text or not text.strip():
        return "Error: text is required."
    if len(text) > MAX_TEXT_LEN:
        return f"Error: text must be <= {MAX_TEXT_LEN} chars."

    if require_mention and not mention_user_id:
        return (
            "Error: mention_user_id is required for this goal — a Slack ping "
            "without an @-mention does not notify the recipient. Pass the "
            "user's Slack id (e.g. UHUUD9ERZ) so the message becomes a real ping."
        )

    body = text
    if mention_user_id:
        # Always lead with the mention so it's the first thing the recipient sees.
        if f"<@{mention_user_id}>" not in body:
            body = f"<@{mention_user_id}> {body}"

    try:
        token = _bot_token()
    except SlackPostError as exc:
        return f"Error: {exc}"

    payload: Dict[str, Any] = {
        "channel": channel,
        "text": body,
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    try:
        resp = requests.post(
            SLACK_POST_ENDPOINT,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            timeout=10,
        )
    except requests.exceptions.RequestException as exc:
        logger.exception("slack_post request failed")
        return f"Error: Slack API request failed — {exc}"

    if resp.status_code != 200:
        return f"Error: Slack API returned HTTP {resp.status_code}: {resp.text[:200]}"

    body_json = resp.json()
    if not body_json.get("ok"):
        return f"Error: Slack API: {body_json.get('error') or body_json}"

    posted_channel = body_json.get("channel", channel)
    posted_ts = body_json.get("ts", "")
    logger.info("slack_post ok channel=%s ts=%s", posted_channel, posted_ts)
    return (
        f"Posted to {posted_channel} (ts={posted_ts})."
        + (f" Mentioned <@{mention_user_id}>." if mention_user_id else "")
    )


SLACK_POST_SCHEMA = {
    "type": "object",
    "properties": {
        "channel": {
            "type": "string",
            "description": "Channel name (e.g. '#standup') or Slack channel id.",
        },
        "text": {
            "type": "string",
            "description": "Message body. Markdown links/mentions allowed.",
        },
        "thread_ts": {
            "type": "string",
            "description": "Optional thread_ts to reply in an existing thread.",
        },
        "mention_user_id": {
            "type": "string",
            "description": (
                "Slack user id of the person to notify (e.g. UHUUD9ERZ). "
                "Required when the goal wants a true ping — without this the "
                "post is just channel chatter and does not notify anyone."
            ),
        },
    },
    "required": ["channel", "text"],
}
