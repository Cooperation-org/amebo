"""
Discord channel adapter — Discord events in, channel-contract types out.

Mirrors slack_adapter.py. Everything Discord-shaped stops here: the core sees
only InboundEnvelope and OutboundAction.

Three differences from Slack worth knowing, because they change behaviour
rather than just naming:

1. A Discord thread is a channel, not a timestamp. `thread_ref` is therefore a
   thread channel id, and a top-level mention has to *create* the thread before
   there is anything to key the conversation on. Same result as Slack: one
   thread, one continuing conversation.
2. A message is capped at 2000 characters. Long answers are split on paragraph
   then line boundaries rather than truncated.
3. Ephemeral messages exist only as a reply to an interaction (a slash
   command). A mention cannot be answered privately, so an EPHEMERAL action
   without an interaction in its metadata is sent in-channel and logged.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

import discord

from src.channels.contract import (
    ActionKind,
    Capability,
    ChannelAdapter,
    ChannelType,
    InboundEnvelope,
    MessageKind,
    OutboundAction,
    SenderIdentity,
)

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 2000
# Leaves room for the part marker appended to continued messages.
SPLIT_AT = 1900


class DiscordAdapter(ChannelAdapter):
    """
    Discord channel adapter.

    `workspace_id` is the guild (server) id — the tenant key, the same role
    Slack's team_id plays.
    """

    channel_type = ChannelType.DISCORD

    def __init__(self, client: "discord.Client", workspace_id: str):
        self.client = client
        self.workspace_id = str(workspace_id)

    def capabilities(self) -> List[Capability]:
        return [
            Capability.THREADS,
            Capability.REACTIONS,
            Capability.EPHEMERAL,      # slash-command replies only; see module docstring
            Capability.RICH_TEXT,
            Capability.EDIT_MESSAGE,
            Capability.BUTTONS,
            Capability.FILE_UPLOAD,
            Capability.TYPING_INDICATOR,
        ]

    # ----- Inbound: Discord events -> InboundEnvelope -----

    def envelope_from_message(
        self,
        message: "discord.Message",
        text: str,
        thread_ref: Optional[str],
        instance_slug: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> InboundEnvelope:
        """
        Build an envelope from a message that is addressed to amebo.

        `text` is passed in already cleaned (the bot mention stripped) and
        `thread_ref` resolved by the caller, because creating the thread is an
        API call the bot service makes, not something an envelope can do.
        """
        author = message.author
        channel_name = self._channel_name(message.channel)

        sender = SenderIdentity(
            sender_id=str(author.id),
            display_name=display_name or author.display_name,
            channel_type=ChannelType.DISCORD,
            raw_id=str(author.id),
            metadata={"username": author.name},
        )

        return InboundEnvelope(
            sender=sender,
            channel_type=ChannelType.DISCORD,
            workspace_id=self.workspace_id,
            text=text,
            kind=MessageKind.THREAD_REPLY if self._in_thread(message) else MessageKind.TEXT,
            thread_ref=thread_ref,
            channel_name=channel_name,
            timestamp=message.created_at or datetime.now(),
            instance_slug=instance_slug,
            metadata={
                "discord_channel_id": str(message.channel.id),
                "discord_message_id": str(message.id),
                "discord_guild_id": str(message.guild.id) if message.guild else None,
                "is_dm": message.guild is None,
            },
        )

    def envelope_from_interaction(
        self,
        interaction: "discord.Interaction",
        text: str,
        command: str,
        instance_slug: Optional[str] = None,
        display_name: Optional[str] = None,
        private: bool = True,
    ) -> InboundEnvelope:
        """Build an envelope from a slash command. Stateless, like Slack's."""
        user = interaction.user
        sender = SenderIdentity(
            sender_id=str(user.id),
            display_name=display_name or user.display_name,
            channel_type=ChannelType.DISCORD,
            raw_id=str(user.id),
            metadata={"username": user.name},
        )

        return InboundEnvelope(
            sender=sender,
            channel_type=ChannelType.DISCORD,
            workspace_id=self.workspace_id,
            text=text,
            kind=MessageKind.COMMAND,
            thread_ref=None,
            channel_name=self._channel_name(interaction.channel),
            timestamp=datetime.now(),
            instance_slug=instance_slug,
            metadata={
                "discord_channel_id": str(interaction.channel_id),
                "discord_command": command,
                "discord_guild_id": str(interaction.guild_id) if interaction.guild_id else None,
                "private": private,
            },
        )

    # ----- Outbound: OutboundAction -> Discord API calls -----

    async def send(self, action: OutboundAction) -> Optional[str]:
        """Execute an outbound action. Returns a message id where there is one."""
        try:
            if action.kind in (ActionKind.REPLY, ActionKind.SEND):
                return await self._send_text(action)
            if action.kind == ActionKind.EPHEMERAL:
                return await self._send_ephemeral(action)
            if action.kind == ActionKind.UPDATE:
                return await self._send_update(action)
            if action.kind == ActionKind.REACT:
                return await self._send_reaction(action)
            if action.kind == ActionKind.TYPING:
                channel = await self._resolve_channel(action)
                if channel:
                    await channel.typing()
                return None
            if action.kind == ActionKind.CONFIRM:
                text = f"{action.confirm_prompt}\n\n_{action.confirm_action}_"
                return await self._send_text(action, override_text=text)
            logger.warning("Unhandled action kind: %s", action.kind)
            return None
        except discord.DiscordException as exc:
            logger.error("Discord send failed: %s", exc, exc_info=True)
            return None

    async def _send_text(
        self, action: OutboundAction, override_text: Optional[str] = None
    ) -> Optional[str]:
        channel = await self._resolve_channel(action)
        if channel is None:
            logger.warning("No Discord channel to send to (thread_ref=%s)", action.thread_ref)
            return None
        body = format_for_discord(override_text or action.text, action.format_hints)
        last_id = None
        for chunk in split_message(body):
            sent = await channel.send(chunk)
            last_id = str(sent.id)
        return last_id

    async def _send_ephemeral(self, action: OutboundAction) -> Optional[str]:
        """
        Private reply. Only possible while answering a slash command — the
        interaction object rides along in metadata for exactly this.
        """
        interaction = action.metadata.get("discord_interaction")
        body = format_for_discord(action.text, action.format_hints)
        if interaction is None:
            logger.info("Ephemeral requested outside an interaction; sending in channel")
            return await self._send_text(action)
        for chunk in split_message(body):
            await interaction.followup.send(chunk, ephemeral=True)
        return None

    async def _send_update(self, action: OutboundAction) -> Optional[str]:
        channel = await self._resolve_channel(action)
        if channel is None or not action.target_message_ref:
            return None
        message = await channel.fetch_message(int(action.target_message_ref))
        body = format_for_discord(action.text, action.format_hints)
        chunks = split_message(body)
        await message.edit(content=chunks[0])
        for extra in chunks[1:]:
            await channel.send(extra)
        return str(message.id)

    async def _send_reaction(self, action: OutboundAction) -> None:
        channel = await self._resolve_channel(action)
        if channel is None or not action.target_message_ref:
            return None
        message = await channel.fetch_message(int(action.target_message_ref))
        await message.add_reaction(action.text)
        return None

    # ----- Internal helpers -----

    async def _resolve_channel(self, action: OutboundAction):
        """
        Where this action goes: the thread if there is one, else the channel it
        came from. Falls back to fetching when the object is not cached.
        """
        target_id = action.thread_ref or action.metadata.get("discord_channel_id")
        if not target_id:
            return None
        channel = self.client.get_channel(int(target_id))
        if channel is not None:
            return channel
        try:
            return await self.client.fetch_channel(int(target_id))
        except discord.DiscordException as exc:
            logger.warning("Could not resolve Discord channel %s: %s", target_id, exc)
            return None

    @staticmethod
    def _in_thread(message: "discord.Message") -> bool:
        return isinstance(message.channel, discord.Thread)

    @staticmethod
    def _channel_name(channel) -> str:
        name = getattr(channel, "name", None)
        if name:
            return name
        return "DM" if isinstance(channel, discord.DMChannel) else str(getattr(channel, "id", ""))

    async def start(self):
        """Connection management lives in DiscordBot; the adapter only speaks."""
        pass

    async def stop(self):
        pass


# ----- Formatting (module-level: pure, and worth testing on its own) -----


def format_for_discord(text: str, hints: Optional[Dict] = None) -> str:
    """
    Discord renders standard markdown, so the text mostly passes through.
    Adds the same source/confidence footer the Slack bot appends.
    """
    if not text:
        return ""

    out = text.strip()

    if hints:
        sources = hints.get("sources", [])
        parts = []
        for source in sources[:3]:
            channel = source.get("channel", "")
            user = source.get("user", "")
            if channel and user:
                parts.append(f"#{channel} ({user})")
            elif channel:
                parts.append(f"#{channel}")
        if parts:
            out += f"\n\n-# Sources: {' · '.join(parts)}"

        confidence = hints.get("confidence")
        if confidence is not None:
            out += f"\n-# Confidence: {confidence}%"

    return out


def split_message(text: str, limit: int = SPLIT_AT) -> List[str]:
    """
    Split text into Discord-sized pieces, breaking at paragraph then line
    boundaries so an answer never gets cut mid-sentence. Always returns at
    least one piece.
    """
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
