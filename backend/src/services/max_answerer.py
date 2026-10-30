"""amebo-max: answer Slack mentions with a Claude Code session on a Max login.

The main backend (user `amebo`, Kimi) hands each mention here, waits, and
answers itself only if nobody claimed it. This process runs as the person who
owns the Max login, so everything a Slack user writes is untrusted data:

  1. The handoff carries only (team, channel, ts, thread). The text is read
     back from Slack, so nothing posted to this port is ever a prompt.
  2. Scans before Claude: the message must address amebo, the sender must be a
     full member of the workspace (no bots, guests or other workspaces), and
     the text must pass the length cap and injection patterns. A message that
     fails is left unclaimed and the backend answers it.
  3. Claim with the ✋ reaction. Both processes post as the same bot user, so
     the second claim gets Slack's `already_reacted` and stops. That reaction
     is the only shared record of who answered.
  4. Claude runs with no user settings, no MCP servers, no slash commands, a
     scrubbed environment (no API keys: an ANTHROPIC_API_KEY would bill the
     API instead of the Max login), `dontAsk` permissions, and the read-only
     allowlist below. The allowlist lives in code, not in the shared DB,
     because whoever can change it can run commands as this user.

One Claude session per Slack thread (uuid5 of channel + thread root), resumed
on each later message, so a thread keeps its context.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

CLAIM_REACTION = "raised_hand"

# Bash rules are command prefixes; Claude Code checks each part of a compound
# command separately, so `abra search x; cat ~/.env` is denied. The amebo-*
# wrappers (amebo/cli) hold the credentials and limit their own verbs.
ABRA_READ = ("search", "about", "read", "who", "related", "names")
ABRA_SCOPES = ("golda", "linkedtrust", "claude")
GIT_READ = ("log", "diff", "show", "status")
BASE_ALLOWED = [
    *[f"Bash(abra {v}:*)" for v in ABRA_READ],
    *[f"Bash(abra --scope {sc} {v}:*)" for sc in ABRA_SCOPES for v in ABRA_READ],
    "Bash(amebo-odoo:*)", "Bash(amebo-elm:*)", "Bash(amebo-taiga:*)",
    "Bash(amebo-slack-history:*)", "Bash(amebo-commit:*)",
    "Bash(amebo-abra-store:*)",
    "WebSearch",
]
TOOLS = "Bash,Read,Grep,Glob,Edit,Write,WebSearch"


def writable_dirs() -> Dict[str, Dict[str, str]]:
    """Directories Claude may read and edit, from the service environment:
    AMEBO_MAX_REPOS ("name=/path,...", git repos it commits with amebo-commit)
    and AMEBO_MAX_EDIT_DIRS ("/path,...", edited in place, e.g. static demos)."""
    repos = dict(p.split("=", 1) for p in os.getenv("AMEBO_MAX_REPOS", "").split(",") if "=" in p)
    dirs = [d for d in os.getenv("AMEBO_MAX_EDIT_DIRS", "").split(",") if d]
    return {"repos": repos, "dirs": dirs}


def allowed_tools(w: Dict[str, Any]) -> List[str]:
    rules = list(BASE_ALLOWED)
    for path in [*w["repos"].values(), *w["dirs"]]:
        # A leading // makes the rule an absolute path.
        rules += [f"{t}(/{path}/**)" for t in ("Read", "Grep", "Glob", "Edit", "Write")]
    for path in w["repos"].values():
        rules += [f"Bash(git -C {path} {v}:*)" for v in GIT_READ]
    return rules


# Environment the Claude process gets. Everything else (DB passwords, Slack
# tokens, API keys) stays in this process.
ENV_KEEP = ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "PATH", "TERM",
            "AMEBO_MAX_REPOS")

INJECTION_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above) (instructions|prompts?)",
    r"disregard (all |any )?(the )?(previous|prior|above)",
    r"system prompt",
    r"you are now",
    r"\bjailbreak\b",
    r"developer mode",
    r"</?(system|instructions?|slack_message|slack_thread)>",
    r"\.env\b",
    r"api[_ -]?key|secret|password|credentials?|private key|ssh",
    r"\b(rm|curl|wget|sudo|chmod|chown|ssh|scp|nc|bash|sh|python3?)\s+-",
]
_INJECTION = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)

PROMPT_FILE = Path(__file__).resolve().parents[2] / "prompts" / "amebo-for-claude.md"


def system_prompt() -> str:
    """prompts/amebo-for-claude.md below its header, read per message."""
    return PROMPT_FILE.read_text().split("\n---\n", 1)[-1].strip()


def thread_session_id(channel: str, thread_root: str) -> str:
    """Stable Claude session id for one Slack thread."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"slack:{channel}:{thread_root}"))


def scan_text(text: str, max_chars: int) -> Optional[str]:
    """Why the text must not reach Claude, or None if it passes."""
    if not text.strip():
        return "empty"
    if len(text) > max_chars:
        return f"longer than {max_chars} chars"
    m = _INJECTION.search(text)
    if m:
        return f"matches injection pattern {m.group(0)!r}"
    return None


def scrubbed_env() -> Dict[str, str]:
    return {k: os.environ[k] for k in ENV_KEEP if k in os.environ}


def format_thread(messages: List[Dict[str, Any]], names: Dict[str, str],
                  bot_user_id: str) -> str:
    lines = []
    for m in messages:
        who = "amebo" if (m.get("user") == bot_user_id or m.get("bot_id")) \
            else names.get(m.get("user", ""), m.get("user", "someone"))
        text = (m.get("text") or "").replace(f"<@{bot_user_id}>", "@amebo")
        lines.append(f"{who}: {text}")
    return "<slack_thread>\n" + "\n".join(lines) + "\n</slack_thread>"


class MaxAnswerer:
    def __init__(self, bot_token: str, workdir: str, claude_bin: str = "claude",
                 timeout_seconds: int = 600, max_chars: int = 4000,
                 concurrency: int = 1, per_hour: int = 20):
        self.web = AsyncWebClient(token=bot_token)
        self.workdir = workdir
        # The Claude process gets its own PATH (AMEBO_MAX_PATH): the backend
        # .env sets PATH for the backend, and it lacks claude and the amebo CLIs.
        self.path = os.getenv("AMEBO_MAX_PATH") or os.environ.get("PATH", "")
        # Full path: uvloop's spawn does not search PATH.
        self.claude_bin = shutil.which(claude_bin, path=self.path)
        if not self.claude_bin:
            raise RuntimeError(f"{claude_bin!r} not found on PATH")
        self.timeout_seconds = timeout_seconds
        self.max_chars = max_chars
        self._slots = asyncio.Semaphore(concurrency)
        self.per_hour = per_hour
        self._claims: List[float] = []
        self._thread_locks: Dict[str, asyncio.Lock] = {}
        self._bot_user_id: Optional[str] = None
        self._bot_team_id: Optional[str] = None

    async def bot_identity(self):
        if not self._bot_user_id:
            auth = await self.web.auth_test()
            self._bot_user_id = auth["user_id"]
            self._bot_team_id = auth["team_id"]
        return self._bot_user_id, self._bot_team_id

    async def handle(self, channel: str, ts: str, thread_root: str) -> str:
        """Answer one Slack message. Returns what happened, for the log."""
        lock = self._thread_locks.setdefault(f"{channel}:{thread_root}", asyncio.Lock())
        async with lock:
            return await self._handle(channel, ts, thread_root)

    async def _handle(self, channel: str, ts: str, thread_root: str) -> str:
        bot_uid, bot_team = await self.bot_identity()
        replies = await self.web.conversations_replies(
            channel=channel, ts=thread_root, limit=200)
        messages = [m for m in replies.get("messages", [])
                    if float(m.get("ts", 0)) <= float(ts)]
        msg = next((m for m in messages if m.get("ts") == ts), None)
        if not msg:
            return "skip: message not found in thread"

        mentioned = f"<@{bot_uid}>" in (msg.get("text") or "")
        parent = messages[0] if messages else {}
        if not (mentioned or parent.get("user") == bot_uid):
            return "skip: not addressed to amebo"

        sender = msg.get("user")
        if not sender or msg.get("bot_id"):
            return "skip: not from a person"
        info = (await self.web.users_info(user=sender)).get("user", {})
        if (info.get("is_bot") or info.get("is_restricted")
                or info.get("is_ultra_restricted") or info.get("deleted")
                or info.get("team_id") != bot_team):
            return "skip: sender is not a full member of this workspace"

        why = scan_text(msg.get("text") or "", self.max_chars)
        if why:
            return f"skip: {why}"

        now = time.monotonic()
        self._claims = [t for t in self._claims if now - t < 3600]
        if len(self._claims) >= self.per_hour:
            return f"skip: {self.per_hour} answers in the last hour"

        try:
            await self.web.reactions_add(channel=channel, timestamp=ts, name=CLAIM_REACTION)
        except SlackApiError as e:
            if e.response.get("error") == "already_reacted":
                return "skip: already claimed"
            raise
        self._claims.append(now)

        names = await self._names({m.get("user") for m in messages if m.get("user")})
        session = thread_session_id(channel, thread_root)
        try:
            async with self._slots:
                answer = await self._ask_claude(session, channel, messages, names, bot_uid)
        except Exception as e:
            logger.exception("amebo-max: claude failed for %s/%s", channel, ts)
            await self.web.chat_postMessage(
                channel=channel, thread_ts=thread_root,
                text=f"Sorry, I encountered an error: {e}")
            return "error"

        from src.services.slack_commands import _deliver
        sent = await _deliver(self.web, answer, channel, thread_root, ts)
        return "answered" if sent else "silent"

    async def _names(self, user_ids) -> Dict[str, str]:
        names = {}
        for uid in user_ids:
            try:
                u = (await self.web.users_info(user=uid)).get("user", {})
                names[uid] = (u.get("profile", {}).get("display_name")
                              or u.get("real_name") or uid)
            except SlackApiError:
                names[uid] = uid
        return names

    async def _ask_claude(self, session: str, channel: str, messages, names, bot_uid) -> str:
        """Resume the thread's session with the newest message, or start it
        with the whole thread."""
        latest = format_thread(messages[-1:], names, bot_uid)
        out = await self._run_claude(["--resume", session], latest, channel)
        if out is None:
            whole = format_thread(messages, names, bot_uid)
            out = await self._run_claude(["--session-id", session], whole, channel)
        if out is None:
            raise RuntimeError("claude did not start a session")
        return out

    async def _run_claude(self, session_args: List[str], prompt: str,
                          channel: str) -> Optional[str]:
        """Run one turn. None when --resume finds no session to resume.
        The channel is passed in the environment for amebo-slack-history."""
        w = writable_dirs()
        where = "\n".join([f"  repo {n}: {p}" for n, p in w["repos"].items()]
                          + [f"  directory (no git, edits are live): {d}" for d in w["dirs"]])
        add_dirs = [a for p in [*w["repos"].values(), *w["dirs"]] for a in ("--add-dir", p)]
        args = [
            self.claude_bin, "-p", *session_args, *add_dirs,
            "--setting-sources", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--tools", TOOLS,
            "--permission-mode", "dontAsk",
            "--allowedTools", *allowed_tools(w),
            # A hook or config planted in .git would run as this user on the
            # next amebo-commit.
            "--disallowedTools", *[f"{t}(/{p}/.git/**)" for p in w["repos"].values()
                                   for t in ("Edit", "Write")],
            # Repos hold their own secrets files.
            *[f"{t}(/{p}/**/{f})" for p in [self.workdir, *w["repos"].values(), *w["dirs"]]
              for t in ("Read", "Grep", "Edit", "Write")
              for f in (".env", ".env.*", "*.env", "*.pem", "*.key")],
            "--system-prompt", system_prompt() + "\n\nWritable:\n" + where,
            "--output-format", "json",
        ]
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=self.workdir, env={**scrubbed_env(), "PATH": self.path, "AMEBO_MAX_CHANNEL": channel},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(prompt.encode()), self.timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"claude timed out after {self.timeout_seconds}s")
        text = out.decode(errors="replace").strip()
        if proc.returncode != 0 and "--resume" in session_args \
                and "No conversation found" in (text + err.decode(errors="replace")):
            return None
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            raise RuntimeError(f"claude exit {proc.returncode}: "
                               f"{(err.decode(errors='replace') or text)[-300:]}")
        if result.get("is_error"):
            if "--resume" in session_args and "No conversation found" in str(result.get("result")):
                return None
            raise RuntimeError(f"claude: {str(result.get('result'))[:300]}")
        denied = result.get("permission_denials") or []
        if denied:
            logger.warning("amebo-max: denied tool calls %s", denied)
        return result.get("result") or ""


async def claimed_by_max(web: AsyncWebClient, max_cfg: Optional[Dict[str, Any]],
                         channel: str, ts: str, thread_root: str) -> bool:
    """Backend side. Hand the mention to amebo-max, wait, then claim it.

    True if amebo-max claimed it (the caller does nothing). False if the
    backend now holds the claim, or no amebo-max is configured, and should
    answer itself.
    """
    if not max_cfg or not max_cfg.get("url"):
        return False
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(max_cfg["url"], timeout=aiohttp.ClientTimeout(total=5),
                              json={"channel": channel, "ts": ts,
                                    "thread_ts": thread_root}) as r:
                if r.status != 202:
                    logger.warning("amebo-max refused handoff: HTTP %s", r.status)
                    return False
    except Exception as e:
        logger.warning("amebo-max unreachable, answering here: %s", e)
        return False

    await asyncio.sleep(int(max_cfg.get("wait_seconds", 300)))
    try:
        await web.reactions_add(channel=channel, timestamp=ts, name=CLAIM_REACTION)
    except SlackApiError as e:
        if e.response.get("error") == "already_reacted":
            return True
        logger.warning("claim reaction failed, answering anyway: %s", e)
    return False
