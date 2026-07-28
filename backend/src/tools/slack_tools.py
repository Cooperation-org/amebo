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


def _workspace_from_context(context) -> Optional[str]:
    if not isinstance(context, dict):
        return None
    oc = context.get("org_context")
    venue = getattr(oc, "venue", None)
    if venue is not None and getattr(venue, "workspace_ref", None):
        return venue.workspace_ref
    return context.get("workspace_id")


def _org_id_from_context(context) -> Optional[int]:
    if not isinstance(context, dict):
        return None
    oc = context.get("org_context")
    oc_org = getattr(oc, "org_id", None)
    if oc_org is not None:
        return oc_org
    return context.get("org_id")


def _bot_token(context=None) -> str:
    """The Slack bot token for the acting workspace (WP4): resolved from the
    per-workspace credential store (set at install), falling back to the env
    SLACK_BOT_TOKEN for the legacy single-workspace deployment until cutover.

    The env fallback is allowed ONLY for the designated legacy org (or a
    deployment that declares one shared credential pool) — the same rule
    cli_read_tools._conn enforces for the CLI tools. For any other org,
    falling back would post into the LEGACY org's Slack under its bot: an
    outbound action attributed to the wrong tenant. A web venue
    (workspace ``web-<slug>``) has no Slack credential of its own by
    construction, so it is exactly the case that used to reach the fallback.
    """
    ws = _workspace_from_context(context)
    if ws and not ws.startswith("web-"):
        try:
            from src.services.credential_service import CredentialService
            creds = CredentialService().get_credentials(ws)
            if creds and creds.get("bot_token"):
                return creds["bot_token"]
        except Exception:
            logger.exception("per-workspace slack token lookup failed for %s", ws)

    from src.credentials.connections import env_credentials_shared
    org_id = _org_id_from_context(context)
    legacy = os.getenv("LEGACY_ENV_ORG_ID", "")
    # org_id None = legacy direct path from before OrgContext existed; those
    # callers keep working, same allowance as _conn makes.
    may_use_env = (
        env_credentials_shared()
        or org_id is None
        or (legacy != "" and str(org_id) == legacy)
    )
    if not may_use_env:
        raise SlackPostError(
            "refusing to post: this org has no Slack workspace connected, and "
            "the token in the environment belongs to a different org.")
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        raise SlackPostError(
            "no Slack bot token (no stored credential for this workspace and "
            "SLACK_BOT_TOKEN is unset).")
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
        token = _bot_token(context)
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


SLACK_REPLIES_ENDPOINT = "https://slack.com/api/conversations.replies"
SLACK_USERS_INFO_ENDPOINT = "https://slack.com/api/users.info"
MAX_THREAD_MESSAGES = 100
THREAD_TEXT_TRUNCATE = 1500


def _conversation_from_context(context) -> Dict[str, Any]:
    """The live conversation descriptor, or {} when there isn't one.

    Set by channel handlers that know where they are (Slack). Claws, the
    CLI and scheduled runs have no conversation, and must not crash here.
    """
    if not isinstance(context, dict):
        return {}
    conv = context.get("conversation")
    return conv if isinstance(conv, dict) else {}


def _resolve_slack_names(token: str, user_ids) -> Dict[str, str]:
    """Slack user id -> display name, best effort.

    One call per distinct participant; a thread has a handful. Any lookup
    that fails leaves the raw id, which is still readable enough.
    """
    names: Dict[str, str] = {}
    for uid in user_ids:
        if not uid:
            continue
        try:
            resp = requests.get(
                SLACK_USERS_INFO_ENDPOINT,
                params={"user": uid},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            data = resp.json()
            if data.get("ok"):
                profile = data.get("user", {})
                names[uid] = (
                    profile.get("profile", {}).get("display_name")
                    or profile.get("real_name")
                    or profile.get("name")
                    or uid
                )
        except Exception:
            logger.debug("users.info lookup failed for %s", uid, exc_info=True)
    return names


def read_slack_thread_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Read the messages of a Slack thread, oldest first.

    Defaults to the thread this conversation is happening in, so the model
    can answer "look above in this thread". Explicit channel/thread_ts let
    it read a thread someone linked instead.
    """
    conv = _conversation_from_context(context)

    channel = (tool_input.get("channel") or "").strip() or conv.get("channel_id")
    thread_ts = (tool_input.get("thread_ts") or "").strip() or conv.get("thread_ref")

    if not channel or not thread_ts:
        if conv.get("channel_type") not in (None, "slack"):
            return (
                "Error: this conversation is not on Slack "
                f"(it is on {conv.get('channel_type')}), so there is no Slack "
                "thread to read. Pass channel and thread_ts explicitly to read "
                "a specific Slack thread."
            )
        return (
            "Error: no Slack thread in context. Pass channel (e.g. C0123ABC) "
            "and thread_ts to read a specific thread."
        )

    try:
        limit = int(tool_input.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, MAX_THREAD_MESSAGES))

    try:
        token = _bot_token(context)
    except SlackPostError as exc:
        return f"Error: {exc}"

    try:
        resp = requests.get(
            SLACK_REPLIES_ENDPOINT,
            params={"channel": channel, "ts": thread_ts, "limit": limit},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except requests.exceptions.RequestException as exc:
        logger.exception("read_slack_thread request failed")
        return f"Error: Slack API request failed — {exc}"

    if resp.status_code != 200:
        return f"Error: Slack API returned HTTP {resp.status_code}: {resp.text[:200]}"

    body = resp.json()
    if not body.get("ok"):
        err = body.get("error") or body
        if err == "missing_scope":
            return (
                "Error: the Slack app is missing the history scope needed to "
                f"read threads (needed: {body.get('needed')}). Ask an admin to "
                "add it and reinstall the app."
            )
        return f"Error: Slack API: {err}"

    messages = body.get("messages", [])
    if not messages:
        return "That thread has no messages (or the bot cannot see it)."

    names = _resolve_slack_names(token, {m.get("user") for m in messages})

    lines = []
    for msg in messages:
        uid = msg.get("user") or msg.get("bot_id") or "unknown"
        who = names.get(uid, uid)
        text = (msg.get("text") or "").strip()
        if len(text) > THREAD_TEXT_TRUNCATE:
            text = text[:THREAD_TEXT_TRUNCATE] + " …[truncated]"
        lines.append(f"[{msg.get('ts', '')}] {who}: {text}")

    header = (
        f"Slack thread {thread_ts} in {channel} — {len(messages)} message(s), "
        "oldest first:"
    )
    return header + "\n\n" + "\n\n".join(lines)


READ_SLACK_THREAD_SCHEMA = {
    "type": "object",
    "properties": {
        "channel": {
            "type": "string",
            "description": (
                "Slack channel id (e.g. C0123ABC). Omit to read the thread "
                "this conversation is already in."
            ),
        },
        "thread_ts": {
            "type": "string",
            "description": (
                "Timestamp of the thread's FIRST message. Omit to read the "
                "thread this conversation is already in."
            ),
        },
        "limit": {
            "type": "integer",
            "description": f"Max messages to return (1-{MAX_THREAD_MESSAGES}, default 50).",
        },
    },
    "required": [],
}


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
