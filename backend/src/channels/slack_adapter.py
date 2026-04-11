"""
Slack channel adapter — translates between Slack events and the channel contract.

This wraps the existing slack_commands.py and slack_listener.py functionality
behind the ChannelAdapter interface. The existing services still work unchanged;
this adapter sits in front of them.

Migration path:
1. [DONE] Define adapter that produces InboundEnvelope from Slack events
2. [TODO] Wire core dispatch to accept InboundEnvelope instead of raw Slack args
3. [TODO] Move response formatting from slack_commands.py into send()
4. [TODO] Update main.py to start SlackAdapter instead of raw listeners
"""

import re
import logging
from datetime import datetime
from typing import Optional, List

from slack_sdk.web.async_client import AsyncWebClient

from src.channels.contract import (
    ChannelAdapter, ChannelType, Capability,
    InboundEnvelope, OutboundAction, ActionKind, MessageKind,
    SenderIdentity,
)

logger = logging.getLogger(__name__)


class SlackAdapter(ChannelAdapter):
    """
    Slack channel adapter.

    Capabilities:
    - Threads (Slack threads via thread_ts)
    - Reactions (emoji reactions)
    - Ephemeral messages (chat_postEphemeral)
    - Rich text (mrkdwn formatting)
    - Message editing (chat_update)
    - Typing indicator (not natively, but can fake with "thinking" message)
    """

    channel_type = ChannelType.SLACK

    def __init__(self, bot_token: str, workspace_id: str):
        self.bot_token = bot_token
        self.workspace_id = workspace_id
        self.web_client = AsyncWebClient(token=bot_token)
        self._user_cache = {}  # user_id -> display_name

    def capabilities(self) -> List[Capability]:
        return [
            Capability.THREADS,
            Capability.REACTIONS,
            Capability.EPHEMERAL,
            Capability.RICH_TEXT,
            Capability.EDIT_MESSAGE,
            Capability.TYPING_INDICATOR,
        ]

    # ----- Inbound: Slack events -> InboundEnvelope -----

    async def envelope_from_mention(
        self, event: dict
    ) -> InboundEnvelope:
        """
        Convert a Slack app_mention event into an InboundEnvelope.

        Handles:
        - Stripping bot mention from text
        - Resolving user display name
        - Setting thread_ref from thread_ts or message ts
        """
        user_id = event.get("user", "unknown")
        raw_text = event.get("text", "")
        channel_id = event.get("channel", "")
        thread_ts = event.get("thread_ts", event.get("ts"))

        # Strip bot mention
        text = re.sub(r'<@[A-Z0-9]+>', '', raw_text).strip()

        # Resolve display name
        display_name = await self._resolve_user_name(user_id)

        # Resolve channel name
        channel_name = await self._resolve_channel_name(channel_id)

        sender = SenderIdentity(
            sender_id=user_id,
            display_name=display_name,
            channel_type=ChannelType.SLACK,
            raw_id=user_id,
        )

        return InboundEnvelope(
            sender=sender,
            channel_type=ChannelType.SLACK,
            workspace_id=self.workspace_id,
            text=text,
            kind=MessageKind.TEXT,
            thread_ref=thread_ts,
            channel_name=channel_name,
            timestamp=datetime.now(),
            metadata={
                "slack_channel_id": channel_id,
                "slack_thread_ts": thread_ts,
                "slack_ts": event.get("ts"),
                "raw_text": raw_text,
            },
        )

    async def envelope_from_slash_command(
        self, payload: dict
    ) -> InboundEnvelope:
        """
        Convert a Slack slash command payload into an InboundEnvelope.

        Slash commands are stateless (no thread context) unless we create one.
        Maps /ask -> MessageKind.COMMAND.
        """
        user_id = payload.get("user_id", "unknown")
        text = payload.get("text", "").strip()
        channel_id = payload.get("channel_id", "")
        command = payload.get("command", "/ask")

        display_name = await self._resolve_user_name(user_id)
        channel_name = await self._resolve_channel_name(channel_id)

        sender = SenderIdentity(
            sender_id=user_id,
            display_name=display_name,
            channel_type=ChannelType.SLACK,
            raw_id=user_id,
        )

        return InboundEnvelope(
            sender=sender,
            channel_type=ChannelType.SLACK,
            workspace_id=self.workspace_id,
            text=text,
            kind=MessageKind.COMMAND,
            thread_ref=None,  # Slash commands don't have thread context
            channel_name=channel_name,
            timestamp=datetime.now(),
            metadata={
                "slack_channel_id": channel_id,
                "slack_command": command,
            },
        )

    async def envelope_from_dm(
        self, event: dict
    ) -> InboundEnvelope:
        """Convert a direct message event into an InboundEnvelope."""
        user_id = event.get("user", "unknown")
        text = event.get("text", "")
        channel_id = event.get("channel", "")
        thread_ts = event.get("thread_ts", event.get("ts"))

        display_name = await self._resolve_user_name(user_id)

        sender = SenderIdentity(
            sender_id=user_id,
            display_name=display_name,
            channel_type=ChannelType.SLACK,
            raw_id=user_id,
        )

        return InboundEnvelope(
            sender=sender,
            channel_type=ChannelType.SLACK,
            workspace_id=self.workspace_id,
            text=text,
            kind=MessageKind.TEXT,
            thread_ref=thread_ts,
            channel_name="DM",
            timestamp=datetime.now(),
            metadata={
                "slack_channel_id": channel_id,
                "slack_thread_ts": thread_ts,
                "is_dm": True,
            },
        )

    # ----- Outbound: OutboundAction -> Slack API calls -----

    async def send(self, action: OutboundAction) -> Optional[str]:
        """
        Execute an outbound action via Slack API.

        Returns Slack message ts on success (for threading/editing).
        """
        channel_id = action.metadata.get("slack_channel_id", "")
        if not channel_id and action.channel_name:
            # Could resolve channel name -> ID here if needed
            logger.warning(f"No slack_channel_id in action metadata, channel_name={action.channel_name}")
            return None

        try:
            if action.kind == ActionKind.REPLY:
                return await self._send_reply(channel_id, action)
            elif action.kind == ActionKind.EPHEMERAL:
                return await self._send_ephemeral(channel_id, action)
            elif action.kind == ActionKind.UPDATE:
                return await self._send_update(channel_id, action)
            elif action.kind == ActionKind.SEND:
                return await self._send_message(channel_id, action)
            elif action.kind == ActionKind.REACT:
                return await self._send_reaction(channel_id, action)
            elif action.kind == ActionKind.TYPING:
                # Slack doesn't have a typing indicator API for bots.
                # Could send a "thinking..." message and update later.
                return None
            elif action.kind == ActionKind.CONFIRM:
                # Render confirmation as an ephemeral message with text prompt.
                # Future: use Slack interactive buttons.
                return await self._send_confirm(channel_id, action)
            else:
                logger.warning(f"Unhandled action kind: {action.kind}")
                return None
        except Exception as e:
            logger.error(f"Slack send failed: {e}", exc_info=True)
            return None

    async def _send_reply(self, channel_id: str, action: OutboundAction) -> Optional[str]:
        """Reply in a thread."""
        text = self._format_for_slack(action.text, action.format_hints)
        result = await self.web_client.chat_postMessage(
            channel=channel_id,
            thread_ts=action.thread_ref,
            text=text,
        )
        return result.get("ts")

    async def _send_ephemeral(self, channel_id: str, action: OutboundAction) -> None:
        """Send ephemeral message visible only to one user."""
        if not action.recipient_id:
            logger.warning("Ephemeral action without recipient_id")
            return None
        text = self._format_for_slack(action.text, action.format_hints)
        await self.web_client.chat_postEphemeral(
            channel=channel_id,
            user=action.recipient_id,
            text=text,
        )
        return None  # Ephemeral messages don't have a ts

    async def _send_update(self, channel_id: str, action: OutboundAction) -> Optional[str]:
        """Update a previously sent message."""
        if not action.target_message_ref:
            logger.warning("Update action without target_message_ref")
            return None
        text = self._format_for_slack(action.text, action.format_hints)
        result = await self.web_client.chat_update(
            channel=channel_id,
            ts=action.target_message_ref,
            text=text,
        )
        return result.get("ts")

    async def _send_message(self, channel_id: str, action: OutboundAction) -> Optional[str]:
        """Send a new message (not in a thread)."""
        text = self._format_for_slack(action.text, action.format_hints)
        result = await self.web_client.chat_postMessage(
            channel=channel_id,
            text=text,
        )
        return result.get("ts")

    async def _send_reaction(self, channel_id: str, action: OutboundAction) -> None:
        """Add a reaction to a message."""
        if not action.target_message_ref:
            return None
        await self.web_client.reactions_add(
            channel=channel_id,
            timestamp=action.target_message_ref,
            name=action.text,  # The emoji name
        )
        return None

    async def _send_confirm(self, channel_id: str, action: OutboundAction) -> None:
        """
        Send a confirmation prompt. For now, text-based.
        Future: Slack interactive buttons.
        """
        confirm_text = f"{action.confirm_prompt}\n\n_Action: {action.confirm_action}_"
        if action.recipient_id:
            await self.web_client.chat_postEphemeral(
                channel=channel_id,
                user=action.recipient_id,
                text=confirm_text,
            )
        else:
            await self.web_client.chat_postMessage(
                channel=channel_id,
                thread_ts=action.thread_ref,
                text=confirm_text,
            )
        return None

    # ----- Formatting -----

    def _format_for_slack(self, text: str, hints: Dict = None) -> str:
        """
        Apply Slack-native formatting to outbound text.

        Converts generic format hints into Slack mrkdwn.
        """
        if not text:
            return ""

        # Convert markdown bold (**text**) to Slack bold (*text*)
        text = re.sub(r'\*\*([^\*]+?)\*\*', r'*\1*', text)

        # Strip emoji shortcodes
        text = re.sub(r':[\w_]+:', '', text)

        # Clean up excessive newlines
        text = re.sub(r'\n{3,}', '\n\n', text).strip()

        # Add source footer if hints provide it
        if hints:
            sources = hints.get("sources", [])
            if sources:
                source_parts = []
                for s in sources[:3]:
                    ch = s.get("channel", "")
                    usr = s.get("user", "")
                    if ch and usr:
                        source_parts.append(f"#{ch} ({usr})")
                    elif ch:
                        source_parts.append(f"#{ch}")
                if source_parts:
                    text += f"\n\n_Sources: {' · '.join(source_parts)}_"

            confidence = hints.get("confidence")
            if confidence is not None:
                text += f"\n_Confidence: {confidence}%_"

        return text

    # ----- Internal helpers -----

    async def _resolve_user_name(self, user_id: str) -> str:
        """Resolve Slack user_id to display name. Cached."""
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        try:
            info = await self.web_client.users_info(user=user_id)
            name = (
                info["user"].get("profile", {}).get("display_name")
                or info["user"].get("real_name")
                or info["user"].get("name")
                or user_id
            )
            self._user_cache[user_id] = name
            return name
        except Exception:
            return user_id

    async def _resolve_channel_name(self, channel_id: str) -> str:
        """Resolve Slack channel_id to channel name."""
        try:
            info = await self.web_client.conversations_info(channel=channel_id)
            return info["channel"]["name"]
        except Exception:
            return channel_id

    async def start(self):
        """
        Start is handled externally by the existing Socket Mode setup.
        This adapter wraps event handling, not connection management.
        See migration path in module docstring.
        """
        pass

    async def stop(self):
        """Cleanup."""
        self._user_cache.clear()
