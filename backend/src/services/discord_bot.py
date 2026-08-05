"""
Discord bot — amebo in a Discord server.

Behaves like the Slack bot: it answers when @-mentioned, keeps a conversation
per thread, and offers /ask, /askall and /task. Plain channel chatter is
ignored, exactly as in Slack.

What Discord adds is roles, so commands that change something outside Discord
(today: /task) are checked against the policy in channels/discord_policy.py
before they run. Questions are open to everyone in the server.

Configuration is split on purpose:

  env    — the secret and which instance this process serves:
             DISCORD_BOT_TOKEN=…
             DISCORD_INSTANCE_SLUG=workerswesee
  DB     — everything about the particular server, on the instance row, read
           fresh on every message: guild id, GovKit org, which roles may act,
           which channels are in scope. See discord_policy.DiscordConfig.

Nothing in this file names a team. Point it at a different instance slug and it
is a different team's bot.

Run: it starts alongside the Slack listener from src/main.py. Standalone for
development: python -m src.services.discord_bot
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, Optional, Tuple

import discord
from discord import app_commands

from src.channels.contract import ActionKind, OutboundAction
from src.channels.discord_adapter import DiscordAdapter, format_for_discord, split_message
from src.channels.discord_policy import DiscordConfig, DiscordPolicy, Permission, Speaker
from src.channels.task_command import parse_task_command
from src.db.connection import DatabaseConnection
from src.db.repositories.instance_repo import InstanceRepo
from src.services.qa_service import QAService
from psycopg2 import extras

logger = logging.getLogger(__name__)

GREETINGS = {"hi", "hello", "hey", "sup", "yo"}

GREETING_TEXT = (
    "Hi {name}! Ask me about the team's work, projects, or anything in our notes.\n"
    "I answer in a thread, so you can just keep replying there — no need to "
    "mention me again."
)

# Discord thread names are capped; keep them readable rather than exact.
THREAD_NAME_LIMIT = 80
THREAD_ARCHIVE_MINUTES = 1440  # 24h of quiet before Discord archives a thread


def resolve_instance_and_org(instance_slug: str) -> Tuple[Optional[Dict], Optional[int]]:
    """
    The instance row this bot serves, and the org to attribute actions to.

    Read on every message rather than cached: instance config is DB config and
    changing it must not need a restart, same as Slack's allowed_tools.
    """
    if not instance_slug:
        return None, None
    repo = InstanceRepo()
    instance = repo.get_by_slug(instance_slug)
    if not instance:
        logger.warning("No amebo instance with slug %s", instance_slug)
        return None, None
    org_ids = repo.orgs_for_instance(instance["id"])
    org_id = org_ids[0] if org_ids else instance.get("org_id")
    return instance, org_id


def log_query_usage(org_id: Optional[int], question: str) -> None:
    """Usage metric + audit line, the same pair the Slack path writes."""
    if org_id is None:
        return
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO usage_metrics (org_id, metric_type, count, period_start, period_end)
                VALUES (%s, 'queries', 1, CURRENT_DATE, CURRENT_DATE + INTERVAL '1 day')
                ON CONFLICT (org_id, metric_type, period_start)
                DO UPDATE SET count = usage_metrics.count + 1
                """,
                (org_id,),
            )
            cur.execute(
                """
                INSERT INTO audit_logs (org_id, action, resource_type, resource_id, details)
                VALUES (%s, 'qa_query', 'discord', %s, %s)
                """,
                (org_id, str(org_id), extras.Json({
                    "question_length": len(question),
                    "source": "discord",
                })),
            )
            conn.commit()
    except Exception as exc:
        logger.warning("Failed to log Discord query usage: %s", exc)
        conn.rollback()
    finally:
        DatabaseConnection.return_connection(conn)


class DiscordBot(discord.Client):
    """The gateway connection and the event handlers."""

    def __init__(self, instance_slug: str):
        intents = discord.Intents.default()
        # Privileged in the developer portal: without it every message arrives
        # with empty content and the bot looks broken rather than silent.
        intents.message_content = True
        super().__init__(intents=intents)

        self.instance_slug = instance_slug
        self.tree = app_commands.CommandTree(self)
        self.adapter: Optional[DiscordAdapter] = None
        self._register_commands()

    # ----- config, read fresh -----

    def load_policy(self) -> Tuple[Optional[Dict], Optional[int], DiscordPolicy]:
        instance, org_id = resolve_instance_and_org(self.instance_slug)
        config = DiscordConfig.from_instance(instance)
        return instance, org_id, DiscordPolicy(config)

    def in_scope(self, guild_id: Optional[int], config: DiscordConfig) -> bool:
        """
        Only serve the configured server. An unset guild_id serves whichever
        server the bot was invited to, which is right for a single-server bot
        being set up for the first time.
        """
        if not config.guild_id:
            return True
        return str(guild_id or "") == config.guild_id

    # ----- lifecycle -----

    async def on_ready(self):
        self.adapter = DiscordAdapter(client=self, workspace_id=str(self._guild_id()))
        instance, _, policy = self.load_policy()
        if instance is None:
            logger.error(
                "Discord bot is running but instance '%s' does not exist — "
                "it will not answer anything.", self.instance_slug,
            )
        try:
            await self.tree.sync()
            logger.info("Discord slash commands synced")
        except discord.DiscordException as exc:
            logger.warning("Could not sync slash commands: %s", exc)
        logger.info(
            "Discord bot ready as %s in %d server(s), instance=%s",
            self.user, len(self.guilds), self.instance_slug,
        )

    def _guild_id(self) -> str:
        return str(self.guilds[0].id) if self.guilds else ""

    # ----- inbound messages -----

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.author.id == (self.user.id if self.user else None):
            return

        instance, org_id, policy = self.load_policy()
        if instance is None:
            return
        if not self.in_scope(message.guild.id if message.guild else None, policy.config):
            return

        addressed, text = self._addressed_to_us(message)
        if not addressed:
            return

        channel_name = getattr(message.channel, "name", None)
        # A thread inherits scope from the channel it hangs off.
        if isinstance(message.channel, discord.Thread):
            channel_name = getattr(message.channel.parent, "name", channel_name)
        if not policy.config.channel_allowed(channel_name):
            return

        speaker = policy.identify(
            discord_user_id=str(message.author.id),
            display_name=message.author.display_name,
            role_names=[r.name for r in getattr(message.author, "roles", [])],
        )

        if not text or text.lower() in GREETINGS:
            await self._greet(message, speaker)
            return

        await self._answer(message, text, speaker, instance, org_id)

    def _addressed_to_us(self, message: discord.Message) -> Tuple[bool, str]:
        """
        Is this for amebo, and what did they actually say?

        Three ways to address it, matching Slack: an @-mention, a reply inside a
        thread amebo opened (no mention needed — it is already a conversation),
        or a DM.
        """
        content = (message.content or "").strip()

        if self.user and self.user.mentioned_in(message) and not message.mention_everyone:
            cleaned = content
            for mention in (f"<@{self.user.id}>", f"<@!{self.user.id}>"):
                cleaned = cleaned.replace(mention, "")
            return True, cleaned.strip()

        if isinstance(message.channel, discord.Thread):
            if self.user and message.channel.owner_id == self.user.id:
                return True, content

        if message.guild is None:
            return True, content

        return False, ""

    async def _greet(self, message: discord.Message, speaker: Speaker):
        thread_ref = await self._ensure_thread(message, "Hello")
        await self._deliver(
            message,
            thread_ref,
            GREETING_TEXT.format(name=speaker.display_name),
        )

    async def _answer(
        self,
        message: discord.Message,
        question: str,
        speaker: Speaker,
        instance: Dict,
        org_id: Optional[int],
    ):
        thread_ref = await self._ensure_thread(message, question)

        channel = self.get_channel(int(thread_ref)) if thread_ref else message.channel
        try:
            async with channel.typing():
                result = await self._ask(
                    question=question,
                    thread_ref=thread_ref,
                    speaker=speaker,
                    instance=instance,
                    org_id=org_id,
                    channel_id=str(channel.id),
                )
        except Exception as exc:
            logger.error("Discord answer failed: %s", exc, exc_info=True)
            await self._deliver(message, thread_ref, f"Sorry, I hit an error: {exc}")
            return

        await self._deliver(
            message,
            thread_ref,
            result.get("answer", "(no response)"),
            hints={
                "sources": result.get("sources", []),
                "confidence": result.get("confidence", 50),
            },
        )
        log_query_usage(org_id, question)

    async def _ask(
        self,
        question: str,
        thread_ref: Optional[str],
        speaker: Speaker,
        instance: Dict,
        org_id: Optional[int],
        channel_id: str,
    ) -> Dict:
        """
        Run the agent loop off the event loop.

        QAService is synchronous and can take many seconds. Calling it inline
        would stall the gateway heartbeat and drop the connection, so it runs in
        a worker thread.
        """
        workspace_id = str(self._guild_id() or instance["slug"])

        def run() -> Dict:
            qa = QAService(workspace_id=workspace_id, org_id=org_id)
            return qa.answer_question(
                question=question,
                n_context_messages=10,
                thread_ref=thread_ref,
                source_type="discord",
                author_info=speaker.author_info,
                instance_slug=instance["slug"],
                conversation={
                    "channel_type": "discord",
                    "channel_id": channel_id,
                    "thread_ref": thread_ref,
                },
            )

        return await asyncio.to_thread(run)

    async def _ensure_thread(self, message: discord.Message, seed: str) -> Optional[str]:
        """
        The thread this conversation lives in, creating it if this is the start.

        Conversation memory is keyed on the thread, so a top-level mention has
        to open one before there is anything to remember against. If the bot
        cannot create threads in this channel, fall back to replying in the
        channel — degraded, not broken.
        """
        if isinstance(message.channel, discord.Thread):
            return str(message.channel.id)
        if message.guild is None:
            return str(message.channel.id)

        name = " ".join(seed.split())[:THREAD_NAME_LIMIT] or "amebo"
        try:
            thread = await message.create_thread(
                name=name, auto_archive_duration=THREAD_ARCHIVE_MINUTES
            )
            return str(thread.id)
        except discord.DiscordException as exc:
            logger.warning("Could not open a thread in #%s: %s", message.channel, exc)
            return None

    async def _deliver(
        self,
        message: discord.Message,
        thread_ref: Optional[str],
        text: str,
        hints: Optional[Dict] = None,
    ):
        action = OutboundAction(
            kind=ActionKind.REPLY if thread_ref else ActionKind.SEND,
            text=text,
            thread_ref=thread_ref,
            format_hints=hints or {},
            metadata={"discord_channel_id": str(message.channel.id)},
        )
        if self.adapter is None:
            self.adapter = DiscordAdapter(client=self, workspace_id=str(self._guild_id()))
        await self.adapter.send(action)

    # ----- slash commands -----

    def _register_commands(self):
        @self.tree.command(name="ask", description="Ask amebo a question (only you see the answer)")
        @app_commands.describe(question="What do you want to know?")
        async def ask(interaction: discord.Interaction, question: str):
            await self._slash_ask(interaction, question, private=True)

        @self.tree.command(name="askall", description="Ask amebo a question in front of the channel")
        @app_commands.describe(question="What do you want to know?")
        async def askall(interaction: discord.Interaction, question: str):
            await self._slash_ask(interaction, question, private=False)

        @self.tree.command(name="task", description="Create a task (stewards and admins)")
        @app_commands.describe(
            details="<project> <subject…> due:YYYY-MM-DD [assign:username] [cash:N]"
        )
        async def task(interaction: discord.Interaction, details: str):
            await self._slash_task(interaction, details)

    async def _slash_ask(self, interaction: discord.Interaction, question: str, private: bool):
        instance, org_id, policy = self.load_policy()
        if instance is None:
            await interaction.response.send_message(
                "I'm not configured for this server yet.", ephemeral=True
            )
            return
        if not self.in_scope(interaction.guild_id, policy.config):
            await interaction.response.send_message(
                "I don't serve this server.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=private, thinking=True)

        speaker = policy.identify(
            discord_user_id=str(interaction.user.id),
            display_name=interaction.user.display_name,
            role_names=[r.name for r in getattr(interaction.user, "roles", [])],
        )

        try:
            result = await self._ask(
                question=question,
                thread_ref=None,
                speaker=speaker,
                instance=instance,
                org_id=org_id,
                channel_id=str(interaction.channel_id),
            )
        except Exception as exc:
            logger.error("Discord /ask failed: %s", exc, exc_info=True)
            await interaction.followup.send(f"Sorry, I hit an error: {exc}", ephemeral=private)
            return

        body = format_for_discord(
            result.get("answer", "(no response)"),
            {
                "sources": result.get("sources", []),
                "confidence": result.get("confidence", 50),
            },
        )
        if not private:
            body = f"**{interaction.user.display_name} asked:** {question}\n\n{body}"
        for chunk in split_message(body):
            await interaction.followup.send(chunk, ephemeral=private)

        log_query_usage(org_id, question)

    async def _slash_task(self, interaction: discord.Interaction, details: str):
        """
        Deterministic front door, same as Slack: the human typed exactly what
        they want, so it is created immediately rather than gated. The role
        check is the gate.
        """
        instance, _, policy = self.load_policy()
        if instance is None:
            await interaction.response.send_message(
                "I'm not configured for this server yet.", ephemeral=True
            )
            return

        speaker = policy.identify(
            discord_user_id=str(interaction.user.id),
            display_name=interaction.user.display_name,
            role_names=[r.name for r in getattr(interaction.user, "roles", [])],
        )
        if not policy.allows(speaker, Permission.ACT):
            await interaction.response.send_message(
                policy.denial_message(Permission.ACT), ephemeral=True
            )
            return

        payload, err = parse_task_command(details)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            from src.tools.gated_actuators import execute_taiga_create
            result = await asyncio.to_thread(execute_taiga_create, {"payload": payload})
            await interaction.followup.send(
                f"✅ {result.strip()}  (due {payload['due_date']})", ephemeral=True
            )
        except Exception as exc:
            logger.error("Discord /task failed: %s", exc, exc_info=True)
            await interaction.followup.send(
                f"❌ Could not create the task: {exc}", ephemeral=True
            )


def build_bot() -> Optional[DiscordBot]:
    """The configured bot, or None when this deployment has no Discord."""
    token = os.getenv("DISCORD_BOT_TOKEN")
    slug = os.getenv("DISCORD_INSTANCE_SLUG")
    if not token:
        return None
    if not slug:
        logger.warning(
            "DISCORD_BOT_TOKEN is set but DISCORD_INSTANCE_SLUG is not — "
            "the bot would not know whose questions to answer. Not starting."
        )
        return None
    return DiscordBot(instance_slug=slug)


async def run():
    """Connect and stay connected. Returns immediately if unconfigured."""
    bot = build_bot()
    if bot is None:
        logger.info("Discord not configured - skipping")
        return
    await bot.start(os.getenv("DISCORD_BOT_TOKEN"))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(run())
