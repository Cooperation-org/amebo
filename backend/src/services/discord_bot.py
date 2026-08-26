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
             DISCORD_INSTANCE_SLUG=workersvc
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
import json
import logging
import os
from typing import Dict, List, Optional, Tuple

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

        @self.tree.command(
            name="drop-task",
            description="Create an equity task in Taiga (In Progress), equity paid on Done"
        )
        @app_commands.describe(
            project="Taiga project slug (defaults to vc)",
            title="Task title",
            equity="Equity points (cook tokens)",
            cash="Cash amount (optional)",
            assignee="Taiga username (optional, defaults to you; autocompletes from project)",
            description="Task description (optional)",
            deadline="Due date as YYYY-MM-DD (e.g. 2026-09-15)",
            status="Task status (autocompletes from project)",
        )
        @app_commands.autocomplete(
            status=self._status_autocomplete,
            assignee=self._assignee_autocomplete,
        )
        async def drop_task(
            interaction: discord.Interaction,
            title: str,
            equity: int,
            project: str = "vc",
            cash: int = 0,
            assignee: str = "",
            description: str = "",
            deadline: str = "",
            status: str = "",
        ):
            await self._slash_drop_task(
                interaction, project, title, equity, cash, assignee,
                description, deadline, status,
            )

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

    async def _slash_drop_task(
        self,
        interaction: discord.Interaction,
        project: str,
        title: str,
        equity: int,
        cash: int,
        assignee: str,
        description: str,
        deadline: str,
        status: str,
    ):
        """
        Create a Taiga task in 'In Progress' and store equity in pending_equity_tasks.
        When Taiga fires a Done webhook, equity is distributed to the Pie via GovKit.
        """
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
        if equity < 0 or cash < 0:
            await interaction.response.send_message(
                "Equity and cash must be zero or positive.", ephemeral=True
            )
            return

        if deadline:
            from src.tools.gated_actuators import _valid_due_date
            if not _valid_due_date(deadline):
                await interaction.response.send_message(
                    f"Deadline must be YYYY-MM-DD and today or later "
                    f"(got '{deadline}').",
                    ephemeral=True,
                )
                return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # Guard: the runner must be enrolled in GovKit. amebo owns no identity
        # — GovKit's Membership row is the one home of the discord_user_id →
        # taiga_username map, and the Taiga Done webhook resolves equity by
        # taiga_username. A speaker GovKit does not know — or whose Membership
        # has no taiga_username — would create a Taiga story with no Membership
        # to credit on Done, and the webhook would fail there. Refuse here so
        # the user gets the instruction, not a late error.
        speaker = policy.identify(
            discord_user_id=str(interaction.user.id),
            display_name=interaction.user.display_name,
            role_names=[r.name for r in getattr(interaction.user, "roles", [])],
        )
        refusal, assignee = _drop_task_guard(speaker, assignee)
        if refusal:
            await interaction.followup.send(refusal, ephemeral=True)
            return

        govkit_org_slug = policy.config.govkit_org or ""

        try:
            result = await asyncio.to_thread(
                _create_drop_task,
                project=project,
                subject=title,
                equity=equity,
                cash=cash,
                assignee=assignee or None,
                description=description or None,
                deadline=deadline or None,
                status=status or None,
                discord_user_id=str(interaction.user.id),
                discord_username=interaction.user.display_name,
                org_id=org_id,
                govkit_org_slug=govkit_org_slug,
            )
            await interaction.followup.send(result, ephemeral=True)
        except Exception as exc:
            logger.error("Discord /drop-task failed: %s", exc, exc_info=True)
            await interaction.followup.send(
                f"❌ Could not create the task: {exc}", ephemeral=True
            )

    async def _status_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """
        Slash option autocomplete for `status`. Reads the typed `project` value
        from the interaction's options, asks mcp-taiga for that project's status
        NAMES, and returns up to 25 Choices. Discord renders the result as a
        dropdown. We never touch numeric status IDs — the wrapper resolves them
        at create time, so the dropdown stays per-project without hardcoding.
        """
        from src.tools.cli_read_tools import run_cli

        project = ""
        for opt in (interaction.data.options or []):
            if opt.name == "project":
                project = str(opt.value or "").strip()

        fallback = [
            app_commands.Choice(name=n, value=n) for n in _DEFAULT_STATUSES
        ]

        if not project:
            return fallback

        try:
            out = await asyncio.to_thread(
                run_cli, ["mcp-taiga", "statuses", project, "--json"], 5
            )
        except Exception as exc:
            logger.warning("status autocomplete failed: %s", exc)
            return fallback

        if not out or not out.lstrip().startswith("["):
            return fallback
        try:
            rows = json.loads(out)
        except json.JSONDecodeError:
            return fallback

        names = [
            r.get("name")
            for r in rows
            if isinstance(r, dict) and r.get("name")
        ]
        if not names:
            return fallback

        # Discord caps autocomplete at 25 choices; truncate Choice name/value
        # at 100 chars (Discord's hard limit on choice labels).
        return [
            app_commands.Choice(name=n[:100], value=n[:100]) for n in names[:25]
        ]

    async def _assignee_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """
        Slash option autocomplete for `assignee`. Reads the typed `project`
        value from the interaction's options, asks mcp-taiga for that project's
        members via `mcp-taiga members <project> --json`, and returns up to 25
        username Choices. Names are the Taiga usernames (the same string the
        Done webhook resolves by); mcp-taiga maps usernames to user IDs at
        assign time. We never hardcode the user list — it is fetched per
        project so a new joiner shows up immediately and removed members
        disappear.
        """
        from src.tools.cli_read_tools import run_cli

        project = ""
        for opt in (interaction.data.options or []):
            if opt.name == "project":
                project = str(opt.value or "").strip()

        if not project:
            # No project to filter by; an empty dropdown nudges the user to
            # pick a project first. There is no sensible global "default
            # assignee" set the way there is for status names.
            return []

        try:
            out = await asyncio.to_thread(
                run_cli, ["mcp-taiga", "members", project, "--json"], 5
            )
        except Exception as exc:
            logger.warning("assignee autocomplete failed: %s", exc)
            return []

        if not out or not out.lstrip().startswith("["):
            return []
        try:
            rows = json.loads(out)
        except json.JSONDecodeError:
            return []

        names = [
            r.get("username")
            for r in rows
            if isinstance(r, dict) and r.get("username")
        ]
        # Discord caps autocomplete at 25 choices; truncate Choice name/value
        # at 100 chars (Discord's hard limit on choice labels).
        return [
            app_commands.Choice(name=n[:100], value=n[:100]) for n in names[:25]
        ]


# Taiga's default user-story status names (New, In Progress, Ready for Test,
# Done). Used as the autocomplete fallback when the user has not yet typed a
# project, so the dropdown is never empty. mcp-taiga resolves these to IDs at
# create time via get_status_id — we never hardcode the numeric IDs here.
_DEFAULT_STATUSES = ("New", "In Progress", "Ready for Test", "Done")


def _drop_task_guard(speaker: Speaker, requested_assignee: str) -> Tuple[str, str]:
    """
    Apply the /drop-task speaker guard.

    Returns (refusal_message, effective_assignee):
      refusal_message non-empty — refuse the command; caller sends it as an
        ephemeral explainer. The bot does NOT proceed to Taiga.
      refusal_message "" — proceed; effective_assignee is what to pass to
        Taiga (the speaker's mapped taiga_username if the caller did not
        name one, else the caller's value verbatim).

    Rule: an explicit `requested_assignee` always wins — anyone in the Discord
    server can drop a task on behalf of someone else by naming them. The
    GovKit map is only consulted as a fallback for the runner's own username
    when they didn't specify one. Two refusal cases, both only when no
    assignee was given:
      (a) the speaker is not enrolled in GovKit at all (no Membership row
          keyed on this discord_user_id) — no fallback to default from;
      (b) the speaker IS enrolled but Membership.taiga_username is empty —
          the Done webhook would fail at the membership lookup.
    Both surface as a clear instruction at slash time instead of an opaque
    error hours later on the webhook.
    """
    if requested_assignee:
        return "", requested_assignee
    if not speaker.known:
        return (
            "I don't have you in the cohort's member list yet. "
            "Ask a steward to add your Discord id to your GovKit "
            "membership (Settings → Profile → Discord), then run this again.",
            "",
        )
    if not speaker.member.taiga_username:
        return (
            "You're in the cohort but your GovKit profile doesn't have a "
            "Taiga username linked yet. Ask an admin (Golda) to set your "
            "Taiga username in your GovKit profile, then run this again.",
            "",
        )
    return "", speaker.member.taiga_username


def _create_drop_task(
    project: str,
    subject: str,
    equity: int,
    cash: int,
    assignee: Optional[str],
    description: Optional[str],
    discord_user_id: str,
    discord_username: str,
    org_id: Optional[int],
    govkit_org_slug: str = "",
    deadline: Optional[str] = None,
    status: Optional[str] = None,
) -> str:
    """
    Create a Taiga story in 'In Progress' with equity/cash tags, store in
    pending_equity_tasks, return a confirmation string.
    Runs in a thread pool (async-to-thread) so it does not block the gateway.
    """
    from src.tools.cli_read_tools import run_cli
    from src.db.repositories.pending_equity_task_repo import PendingEquityTaskRepo

    status_name = status or "In Progress"
    argv = ["mcp-taiga", "create", project, subject, "--status", status_name]
    if description:
        argv += ["--description", description]
    if deadline:
        argv += ["--due", deadline]
    if assignee:
        argv += ["--assign", assignee]
    if equity > 0:
        argv += ["--team", str(equity)]
    if cash > 0:
        argv += ["--cash", str(cash)]

    out = run_cli(argv)
    # mcp-taiga prints "Created #<ref>: ..." on success
    if "Created #" not in out:
        raise RuntimeError(f"Taiga task creation failed: {out.strip()}")

    # Extract ref from "Created #42: ..."
    ref_part = out.strip().split("Created #")[1].split(":")[0]
    taiga_ref = int(ref_part)

    # Store in pending equity table
    repo = PendingEquityTaskRepo()
    row_id = repo.create(
        taiga_ref=taiga_ref,
        taiga_project=project,
        org_id=org_id or 0,
        govkit_org_slug=govkit_org_slug,
        discord_user_id=discord_user_id,
        discord_username=discord_username,
        assignee=assignee,
        subject=subject,
        equity=equity,
        cash=cash,
    )

    equity_str = f"{equity} equity" if equity else ""
    cash_str = f"${cash}" if cash else ""
    parts = [p for p in [equity_str, cash_str] if p]
    reward = f" + {', '.join(parts)}" if parts else ""
    return (
        f"✅ Task Created: [{project} #{taiga_ref}] {subject}"
        f"{reward} — equity will be added to Pie when marked Done in Taiga."
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
