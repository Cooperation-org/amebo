"""
Personal amebo REPL — amebo in your own shell, running as YOU.

Same conversation core as the Slack/qa path (ConversationManager):

  - stable system prefix (identity + rules), never per-turn volatile data, so
    the cached prefix hash matches call-to-call and the prompt cache hits;
  - `cache_control` on the system block plus a rolling breakpoint on the last
    message, so each tool round's growing prefix is cached too;
  - turns persisted verbatim to the thread, so the next turn's prefix is
    byte-identical to what was cached;
  - compaction/summary of old turns past the token threshold.

Plus a general `shell` tool, registered only because this process is a verified
personal session (shell_tool.register_shell_tool_if_personal). Read-only
commands auto-run; anything else asks you to confirm in the terminal.

What the person sees: their question, a one-line trace per tool call, the
answer. Tool output and the model's in-between narration are not printed —
`/tools` shows the last turn's tool output in full when wanted.

Run (as the owner uid):
    AMEBO_PERSONAL_MODE=1 AMEBO_PERSONAL_UID=$(id -u) python -m src.personal.repl [-c]
"""

from __future__ import annotations

import json
import re
import os
import shutil
import sys
import threading
import time
from typing import Dict, List, Optional, Tuple

# A constant note appended to the instance identity so the model knows the shell
# tool exists. MUST be constant — anything per-turn here would change the system
# block and bust the prefix cache on every call.
_SHELL_NOTE = (
    "\n\nYou are running as this person's PERSONAL assistant in their own shell "
    "session, as them. You can run shell commands with the `shell` tool "
    "(read-only commands run immediately; anything else asks them to confirm). "
    "Think a lot, work a lot, speak little — concise and concrete, like a "
    "capable colleague. When a task needs commands, just use the shell tool. "
    "Do not narrate what you are about to do; only the final answer is shown. "
    "Answer in plain text for a terminal: short lines, no headings, no tables, "
    "no asterisks or other markdown. "
    "No closing offers or follow-up questions."
    "\n\nThis session is mostly a founder thinking out loud: go-to-market, "
    "positioning, messaging, who to reach and what to say. Answer the strategy "
    "question; do not steer toward building or coding unless asked. "
    "Team knowledge is in abra_search (search, about, read) and the projects "
    "repo /opt/shared/projects: list_projects and read_main_md for Active/, "
    "and the shell (grep, cat) for the rest, e.g. Internal/ strategy docs. "
    "For copy (taglines, pitches, messages) start from the team's own words "
    "in those sources, say where each came from, and mark lines you wrote. "
    "Name a source only if a tool call in this session returned it. "
    "When asked to run, check or look something up, call the tool first: "
    "never state a command's output, exit status, or a record's contents "
    "unless a tool call in this turn returned it."
    "\n\nWrite tools (Taiga, CRM, MAIN.md and the rest) show the person a "
    "run? [y/N] prompt in the terminal before they execute. Call them "
    "directly; do not draft and ask for approval in text first."
)

# The personal session's tool set: shell + amebo's safe read tools.
# Knowledge is abra_search (search / about / read).
_PERSONAL_TOOLS = [
    "shell", "list_projects", "read_main_md", "abra_search",
    "web_search", "web_research", "http_fetch",
]
# Instance tools the CLI does not offer. search_knowledge_base and
# lookup_contact read the per-org local tables, empty for this instance, so the
# model answered "abra has nothing on X" when abra had it. ask_user and
# goal_done only work inside a goal run; here they always return an error.
_NOT_IN_CLI = {"search_knowledge_base", "lookup_contact", "ask_user", "goal_done"}

# Modes: `default` is the general assistant, unchanged. `code` is opt-in
# (--mode=code or /mode code): adds file tools and a coding note, and runs
# commands in the directory amebo was started from.
_MODES = ("default", "code")
_CODE_TOOLS = ["read_file", "edit_file", "write_file"]
_CODE_NOTE = (
    "\n\nCODE MODE. The working directory is {cwd}; shell commands and relative "
    "paths start there. Read a file before changing it. Change files with "
    "edit_file (exact string replace) or write_file (new or whole files), not "
    "with shell redirects or sed -i. After a change, run the relevant tests if "
    "the project has them. Install packages only into the project's own "
    "virtualenv, never with --user or --break-system-packages; if a tool is "
    "missing and there is no venv, say so instead."
)

# Permissions: what runs without asking.
#   ask   reads run; file edits and other commands ask (the default)
#   edit  reads and file edits run; other commands ask
#   auto  everything runs except _ALWAYS_ASK commands
#   skip  everything runs; only sudo/su asks (amebo --skip-permissions)
_PERMISSIONS = ("ask", "edit", "auto", "skip")

# Tool rounds allowed within a single turn before we force an answer.
_MAX_TOOL_ROUNDS = int(os.getenv("AMEBO_CLI_MAX_TOOL_ROUNDS", "16"))
_MAX_TOKENS = int(os.getenv("AMEBO_CLI_MAX_TOKENS", "4000"))
# A coding task (read, edit, test, fix, repeat) takes many more rounds.
_CODE_MAX_TOOL_ROUNDS = int(os.getenv("AMEBO_CLI_CODE_MAX_TOOL_ROUNDS", "60"))
# Code mode writes whole files through tool calls; 4000 cuts them off.
_CODE_MAX_TOKENS = int(os.getenv("AMEBO_CLI_CODE_MAX_TOKENS", "16000"))
# Each turn's tool calls stay in the session history (see run_repl).
# Past this estimated size it drops back to the stored, compacted history.
_CODE_HISTORY_MAX_TOKENS = int(os.getenv("AMEBO_CLI_CODE_HISTORY_TOKENS", "80000"))

_TTY = sys.stdout.isatty()
_DIM = "\033[2m" if _TTY else ""
_BOLD = "\033[1m" if _TTY else ""
_RESET = "\033[0m" if _TTY else ""


def _width() -> int:
    return shutil.get_terminal_size((100, 24)).columns


def _one_line(s: str, room: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= room else s[: max(room - 1, 1)] + "…"


class _Status:
    """A single spinner line on stderr while the model or a tool is busy.
    Cleared before anything else is printed, so the transcript stays clean."""

    def __init__(self):
        self._label = ""
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._t0 = 0.0

    def start(self, label: str):
        self._label = label
        self._t0 = time.time()
        if not _TTY or self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def set(self, label: str):
        self._label = label

    def pause(self) -> Optional[str]:
        """Stop the spinner so a prompt can be seen; returns the label to
        resume with (None if it was not spinning)."""
        if not self._thread:
            return None
        label = self._label
        self.stop()
        return label

    def resume(self, label: Optional[str]):
        if label is not None:
            self.start(label)

    def stop(self):
        if not self._thread:
            return
        self._stop.set()
        self._thread.join()
        self._thread = None
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

    def _spin(self):
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        while not self._stop.is_set():
            el = int(time.time() - self._t0)
            line = f"  {frames[i % len(frames)]} {self._label} {_DIM}{el}s{_RESET}"
            sys.stderr.write("\r\033[K" + _one_line(line, _width() - 2))
            sys.stderr.flush()
            i += 1
            self._stop.wait(0.1)


# Auto mode (amebo -y): everything runs without asking except these — they
# still prompt. Matched as substrings of the whitespace-normalized command.
_ALWAYS_ASK = (
    "sudo ", "rm -rf /", "rm -rf ~", "rm -rf *", "rm -r /", "mkfs", "dd if=",
    "shutdown", "reboot", "git push --force", "git push -f", "git reset --hard",
    "git clean", "drop table", "drop database", "truncate ", "systemctl stop",
    "systemctl restart", "systemctl disable", "kill -9", "pkill", "killall",
    "chmod -r", "chown -r", "> /etc/", "> /dev/",
)


# Skip mode still asks before a command becomes root.
_ELEVATE = re.compile(r"(^|[\s;&|(`$])(sudo|su|doas|pkexec)(\s|$)")


def _skip_confirm(command: str) -> bool:
    if _ELEVATE.search(command):
        return _terminal_confirm(command)
    return True


def _auto_confirm(command: str) -> bool:
    norm = " ".join(command.split()).lower()
    if any(p in norm for p in _ALWAYS_ASK):
        return _terminal_confirm(command)
    return True


def _terminal_confirm_edit(path: str, diff: str) -> bool:
    try:
        ans = input(f"\n{_indent(diff, 2)}\n  {_BOLD}apply to {path}?{_RESET} [y/N] ").strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def _providers() -> Dict[str, str]:
    """provider -> the env var holding its API key."""
    from src.services.llm_client import _COMPATIBLE_PROVIDERS
    keys = {"anthropic": "ANTHROPIC_API_KEY"}
    keys.update({p: spec[0] for p, spec in _COMPATIBLE_PROVIDERS.items()})
    return keys


def _pick_llm(spec: str):
    """Switch this process to `spec`: a provider name (kimi, minimax,
    anthropic) or a model id (claude-*, kimi-*, MiniMax-*). Returns
    (client, model, provider), or an error string.

    An explicit choice is honored as-is: no day-long fallback trip (that
    protects the shared service's budget), so the model shown is the model
    that answers, and a failure shows as an error."""
    from src.services.llm_client import _COMPATIBLE_PROVIDERS, _build_client, _model_for
    providers = _providers()
    spec = (spec or "").strip()
    low = spec.lower()
    requested = None
    if low in providers:
        provider = low
    elif low.startswith("claude-"):
        provider, requested = "anthropic", spec
    else:
        provider = next((p for p in _COMPATIBLE_PROVIDERS if low.startswith(p + "-")), None)
        if provider is None:
            return (f"unknown model '{spec}' — a provider ({', '.join(providers)}) "
                    "or a model id (claude-…, kimi-…, MiniMax-…)")
        os.environ[_COMPATIBLE_PROVIDERS[provider][3]] = spec  # e.g. KIMI_MODEL
    if not os.getenv(providers[provider]):
        return f"{providers[provider]} is not set — export it, then /model {spec}"
    client = _build_client(provider)
    if client is None:
        return f"could not start a {provider} client"
    model = _model_for(provider, requested or os.getenv("AMEBO_CLI_MODEL")
                       or os.getenv("AMEBO_QA_MODEL", "claude-sonnet-4-6"))
    return client, model, provider


def _error_line(exc: Exception, provider: str) -> str:
    """One line for a failed call: provider, HTTP status, the API's own message."""
    body = getattr(exc, "body", None)
    msg = None
    if isinstance(body, dict):
        err = body.get("error")
        msg = err.get("message") if isinstance(err, dict) else None
    code = getattr(exc, "status_code", None)
    return f"{provider}{f' {code}' if code else ''}: {msg or exc}"


def _flag(argv: List[str], name: str) -> Optional[str]:
    """Value of --name=X or --name X, else None."""
    for i, a in enumerate(argv):
        if a.startswith(f"--{name}="):
            return a.split("=", 1)[1]
        if a == f"--{name}" and i + 1 < len(argv):
            return argv[i + 1]
    return None


def _terminal_confirm(command: str) -> bool:
    try:
        ans = input(f"\n  {_BOLD}$ {command}{_RESET}\n  run? [y/N] ").strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def _cache_prefix(
    system_prompt: str, messages: List[Dict]
) -> Tuple[List[Dict], List[Dict]]:
    """Attach prompt-cache breakpoints: the system block (stable per thread) and
    a rolling breakpoint on the LAST message's last content block.

    The rolling last-message breakpoint means every growing prefix — prior turns
    across the session AND the tool rounds within this turn — becomes cacheable.
    The server picks the longest matching prefix, so as long as history is sent
    byte-identically (it is: turns are persisted verbatim, system carries no
    per-turn data) the cache hits. Only text and tool_result blocks carry
    cache_control; a trailing tool_use block is never marked.
    """
    system_blocks = [{
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"},
    }]

    out_msgs: List[Dict] = []
    last = len(messages) - 1
    for i, msg in enumerate(messages):
        content = msg["content"]
        if i != last:
            out_msgs.append({"role": msg["role"], "content": content})
            continue
        # Mark the last content block of the last message.
        if isinstance(content, str):
            blocks = [{
                "type": "text", "text": content,
                "cache_control": {"type": "ephemeral"},
            }]
        else:
            blocks = [dict(b) for b in content]
            if blocks and blocks[-1].get("type") in ("text", "tool_result"):
                blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
        out_msgs.append({"role": msg["role"], "content": blocks})
    return system_blocks, out_msgs


def _serialize_blocks(content, keep_thinking: bool = False) -> List[Dict]:
    """SDK content blocks -> plain dicts, so the next request re-serializes them
    identically (raw SDK blocks can hit a re-serialization bug and shift bytes).
    With thinking on, the thinking blocks are sent back with the tool round."""
    out = []
    for b in content:
        if b.type == "thinking" and keep_thinking:
            out.append({"type": "thinking", "thinking": b.thinking,
                        "signature": getattr(b, "signature", "") or ""})
        elif b.type == "text":
            out.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
    return out


def _tool_label(name: str, inp: Dict) -> str:
    """One line: tool name + its main argument. `shell` shows the command."""
    if name == "shell":
        arg = inp.get("command", "")
    else:
        vals = [str(v) for v in inp.values() if isinstance(v, (str, int, float))]
        arg = " ".join(vals)
    return f"{name} {arg}".strip()


def _result_summary(res: str) -> str:
    """What to show for a tool result: errors in full (first line), otherwise
    a line count. The full output is kept for /tools."""
    text = str(res or "").strip()
    if not text:
        return "no output"
    first = text.splitlines()[0]
    bad = first.startswith(("Error", "[exit", "Refused", "Declined", "Unknown tool"))
    n = text.count("\n") + 1
    if bad or n == 1:
        return first
    return f"{n} lines"


# mcp_taiga and odoo_cli pass any subcommand through, so they are write-class
# and ask. These subcommands only read; they run without asking.
_CLI_READ_SUBCOMMANDS = {
    "mcp_taiga": {"list", "show", "projects", "members", "statuses", "users",
                  "earnings"},
    "odoo_cli": {"status", "user-list", "contact-list", "contact-search",
                 "contact-export", "module-list", "agenda", "comms",
                 "campaign-list", "campaign-show", "contact-list-tag"},
}


def _cli_read(name: str, inp: Dict) -> bool:
    reads = _CLI_READ_SUBCOMMANDS.get(name)
    words = str(inp.get("command") or "").split()
    return bool(reads and words and words[0] in reads)


# MiniMax-M3 with thinking off answered "passwordless sudo works" without
# running anything in 7 of 10 tries on the full CLI prompt; with thinking on it
# called the tool 10 of 10. 0 turns it off.
_THINKING_TOKENS = int(os.getenv("AMEBO_CLI_THINKING_TOKENS", "1500"))


def _thinking_for(provider: str) -> Optional[Dict]:
    if provider == "minimax" and _THINKING_TOKENS > 0:
        return {"type": "enabled", "budget_tokens": _THINKING_TOKENS}
    return None


def _run_turn(client, model, system_prompt, messages, tools, tctx, principal,
              out, status, trace: List[Tuple[str, str]],
              max_tokens: int = _MAX_TOKENS,
              work_out: Optional[List[Dict]] = None,
              max_rounds: int = _MAX_TOOL_ROUNDS,
              notes: Optional[List[str]] = None,
              thinking: Optional[Dict] = None) -> str:
    """One user turn: call the model, run tool rounds, return the final text.
    `messages` is the full history+question from ConversationManager.build_messages;
    tool-round scaffolding stays local and is NOT persisted (only the final answer
    is), keeping the cross-turn prefix clean and byte-stable. Each tool call is
    printed as one line; its output goes to `trace` (for /tools), not the screen."""
    from src.tools.registry import get_tool, trust_gate
    from src.services.source_check import mark_unopened

    work = list(messages) if work_out is None else work_out
    work[:] = list(messages)
    for _round in range(max_rounds + 1):
        system_blocks, cached = _cache_prefix(system_prompt, work)
        kwargs = dict(model=model, max_tokens=max_tokens,
                      system=system_blocks, messages=cached)
        if tools:
            kwargs["tools"] = tools
        if thinking:
            kwargs["thinking"] = thinking
        # Last round: force an answer instead of another tool call.
        if _round == max_rounds and tools:
            kwargs["tool_choice"] = {"type": "none"}
        status.start("thinking")
        try:
            resp = client.messages.create(**kwargs)
        finally:
            status.stop()

        # MiniMax can return content=None (no blocks at all).
        work.append({"role": "assistant", "content": _serialize_blocks(resp.content or [])})
        if resp.stop_reason != "tool_use":
            if resp.stop_reason == "max_tokens" and notes is not None:
                notes.append("(cut off at the length limit — say continue for the rest)")
            text = "".join(b.text for b in resp.content or [] if b.type == "text").strip()
            return mark_unopened(text, _tool_outputs(work))

        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            label = _tool_label(b.name, dict(b.input))
            tool = get_tool(b.name)
            if tool is None:
                res = f"Unknown tool: {b.name}"
            else:
                denial = trust_gate(tool, principal)
                ctx = tctx
                if not denial and tool.effective_access_class != "read" \
                        and tool.category != "personal" and b.name not in _CODE_TOOLS \
                        and not _cli_read(b.name, dict(b.input)):
                    confirm_action = tctx.get("confirm_action")
                    if not (callable(confirm_action) and confirm_action(label)):
                        denial = "Refused: the person declined this action."
                    else:
                        ctx = {**tctx, "auto_execute": True}
                if denial:
                    res = denial
                else:
                    status.start(label)
                    try:
                        res = tool.execute(b.input, ctx) or ""
                    except Exception as exc:
                        # A broken tool is the model's to work around, not
                        # the end of the turn (and not a provider error).
                        res = f"Error: {b.name} failed: {type(exc).__name__}: {exc}"
                    finally:
                        status.stop()
            trace.append((label, str(res)))
            room = _width() - 4
            summary = _one_line(_result_summary(res), room // 3)
            line = _one_line(label, room - len(summary) - 3)
            out(f"  {_DIM}· {line} ⎿ {summary}{_RESET}")
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": res})
        work.append({"role": "user", "content": results})
    # Some providers ignore tool_choice "none". Stop anyway, and close the
    # turn with an assistant message so "continue" can pick it back up.
    stopped = f"(stopped after {max_rounds} rounds of tool calls — say continue to keep going)"
    work.append({"role": "assistant", "content": [{"type": "text", "text": stopped}]})
    return stopped


def _tool_outputs(work: List[Dict]) -> List[str]:
    """Every tool result in this turn's messages, as text."""
    return [str(c.get("content", "")) for m in work if m["role"] == "user"
            and isinstance(m["content"], list)
            for c in m["content"] if isinstance(c, dict) and c.get("type") == "tool_result"]


def _resume_session(uid: int) -> Optional[str]:
    """source_ref of this user's most recent CLI session that has turns, if any.
    Empty sessions are skipped: every start creates one, so `amebo` then
    `exit` would otherwise make `amebo -c` resume nothing."""
    from src.db.repositories.thread_repo import ThreadRepo
    rows = ThreadRepo().list_by_ref_prefix("cli", f"cli-{uid}-", limit=1)
    return rows[0]["source_ref"] if rows else None


def _ago(s) -> str:
    """Seconds ago -> '5m ago'."""
    if s is None:
        return ""
    s = int(s)
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= n:
            return f"{s // n}{unit} ago"
    return "just now"


def _choose_session(uid: int, arg: str, out, ask=input,
                    current: Optional[str] = None) -> Optional[str]:
    """List this user's past CLI sessions and return the chosen source_ref.
    arg: a number from the list, or empty to show the list and ask."""
    from src.db.repositories.thread_repo import ThreadRepo
    # The session you are in is not one to resume; leaving it in made
    # `/resume 1` a silent no-op once it had a turn (it is the newest).
    rows = [r for r in ThreadRepo().list_by_ref_prefix("cli", f"cli-{uid}-")
            if r["source_ref"] != current]
    if not rows:
        out("  no past sessions")
        return None
    if not arg:
        room = _width() - 24
        for i, r in enumerate(rows, 1):
            out(f"  {i:>2}  {_ago(r['age_seconds']):>8}  "
                f"{_one_line(r['first_question'] or '(no question)', room)}")
        try:
            arg = ask("  resume which? [number, Enter to cancel] ").strip()
        except EOFError:
            return None
        if not arg:
            return None
    if not arg.isdigit() or not 1 <= int(arg) <= len(rows):
        out(f"  pick a number 1-{len(rows)}")
        return None
    return rows[int(arg) - 1]["source_ref"]


def _show_last_exchange(mgr, out):
    """After a resume, show where the conversation left off."""
    from src.db.repositories.thread_repo import ThreadRepo
    for t in ThreadRepo().get_turns(mgr.thread_id)[-2:]:
        who = "you ›" if t["role"] == "user" else "amebo ›"
        out(f"{_DIM}{who} {_clip_lines(t['content'])}{_RESET}")


def _clip_lines(text: str, lines: int = 8) -> str:
    """The first few lines and the end of a long turn, so a resumed pasted
    document or long answer does not fill the screen."""
    rows = []
    for ln in str(text).splitlines():
        rows += [ln[i:i + _width()] for i in range(0, max(len(ln), 1), _width())]
    if len(rows) <= lines:
        return str(text)
    keep = lines - 2
    return "\n".join(rows[:keep] + [f"  … {len(rows) - keep - 1} more lines …", rows[-1]])


def _setup_readline():
    try:
        import readline  # noqa: F401  (line editing + history for input())
    except ImportError:
        return
    hist = os.path.expanduser("~/.amebo_history")
    try:
        readline.read_history_file(hist)
    except OSError:
        pass
    readline.set_history_length(1000)
    import atexit
    atexit.register(lambda: _save_history(readline, hist))


def _save_history(readline, path):
    try:
        readline.write_history_file(path)
    except OSError:
        pass


def run_repl(in_stream=None, out=print, argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    resume = any(a in ("-c", "--continue") for a in argv)
    pick = any(a in ("-r", "--resume") for a in argv)
    auto = any(a in ("-y", "--yes") for a in argv) or os.getenv("AMEBO_CLI_AUTO") == "1"
    skip = "--skip-permissions" in argv
    start_mode = _flag(argv, "mode") or "default"
    perms = _flag(argv, "permissions") or ("skip" if skip else "auto" if auto else "ask")
    if start_mode not in _MODES:
        out(f"unknown mode '{start_mode}' — one of: {', '.join(_MODES)}")
        return 2
    if perms not in _PERMISSIONS:
        out(f"unknown permissions '{perms}' — one of: {', '.join(_PERMISSIONS)}")
        return 2

    _log_to_file()

    # Provider/model are config, decoupled from this mode. Override for THIS
    # process only; the Slack service keeps whatever it was started with.
    if os.getenv("AMEBO_CLI_PROVIDER"):
        os.environ["AMEBO_LLM_PROVIDER"] = os.environ["AMEBO_CLI_PROVIDER"]

    from src.tools.shell_tool import register_shell_tool_if_personal
    registered = register_shell_tool_if_personal()
    from src.tools.file_tools import register_file_tools_if_personal
    register_file_tools_if_personal()
    from src.tools.registry import get_tool, _tool_to_schema, get_tools_for_instance
    from src.services.org_context import OrgContext
    from src.services.trust import Principal
    from src.services.conversation_manager import ConversationManager
    from src.services.llm_client import get_llm_client, resolve_model

    if not registered:
        out("shell off — set AMEBO_PERSONAL_MODE=1 and run as AMEBO_PERSONAL_UID. "
            "Read tools only.")

    org_id = int(os.getenv("AMEBO_PERSONAL_ORG_ID", "1"))
    instance_id = int(os.getenv("AMEBO_PERSONAL_INSTANCE_ID", "1"))
    person_id = int(os.getenv("AMEBO_PERSONAL_PERSON_ID", "0")) or None
    ctx = OrgContext(org_id=org_id, instance_id=instance_id, actor_type="user",
                     actor_person_id=person_id, authority="service")
    # This session is verified-personal: it only started because os.getuid()
    # matched the declared owner (shell_tool's guard). That uid check IS the
    # auth, so the principal is SERVICE-trust — the owner on their own box.
    principal = Principal(transport="cli", person_id=person_id, is_service=True)

    def tools_for(m: str) -> List[Dict]:
        # The CLI gets everything the instance offers in Slack (allowed_tools +
        # admin_tools), plus the personal tools. Writes confirm per /permissions.
        names = _PERSONAL_TOOLS + (_CODE_TOOLS if m == "code" else [])
        schemas = [_tool_to_schema(get_tool(n)) for n in names if get_tool(n)]
        have = {t["name"] for t in schemas}
        schemas += [t for t in get_tools_for_instance(mgr._instance, admin=True)
                    if t["name"] not in have and t["name"] not in _NOT_IN_CLI]
        return schemas

    # The directory amebo was started from (the launcher cds into the backend).
    work_dir = os.getenv("AMEBO_CLI_CWD") or os.getcwd()
    code_note = _CODE_NOTE.format(cwd=work_dir)

    start_model = _flag(argv, "model")
    if start_model:
        picked = _pick_llm(start_model)
        if isinstance(picked, str):
            out(picked)
            return 2
        client, model, _ = picked
    else:
        client = get_llm_client()
        if client is None:
            out("No LLM client — the configured provider's API key is not set "
                "(ANTHROPIC_API_KEY for anthropic, MINIMAX_API_KEY for minimax).")
            return 1
        # Model: CLI override > standard QA model > default. resolve_model maps it
        # onto whatever the active provider actually serves.
        model = resolve_model(
            os.getenv("AMEBO_CLI_MODEL") or os.getenv("AMEBO_QA_MODEL", "claude-sonnet-4-6")
        )
    from src.services.llm_client import get_provider
    llm = {"client": client, "model": model,
           "provider": picked[2] if start_model else get_provider()}

    # Persistent thread → history is stored verbatim and replayed byte-identically
    # each turn, which is what makes the prefix cache hit. `-c` resumes the last
    # session; AMEBO_CLI_SESSION names one; default is fresh per process.
    uid = os.getuid()
    session = os.getenv("AMEBO_CLI_SESSION")
    resumed = False
    if not session and resume:
        session = _resume_session(uid)
        resumed = session is not None
    if not session and pick:
        session = _choose_session(uid, "", out)
        if session is None:  # cancelled, or nothing to resume
            return 0
        resumed = True
    session = session or f"cli-{uid}-{os.getpid()}"
    mgr = ConversationManager(
        source_type="cli", source_ref=session,
        instance_slug=os.getenv("AMEBO_CLI_INSTANCE", "whatscookin"),
    )

    reader = in_stream or sys.stdin
    interactive = reader is sys.stdin and sys.stdin.isatty()
    if interactive:
        _setup_readline()
    mode = {"mode": start_mode, "perms": perms}
    from src.services.goal_dispatcher import primary_workspace_id
    # workspace_id scopes Slack history search to this org's workspace.
    tctx = {"org_context": ctx, "org_id": org_id,
            "workspace_id": primary_workspace_id(org_id)}

    code_history: List[Dict] = []

    def set_mode(m: str):
        mode["mode"] = m
        code_history.clear()
        tctx["cwd"] = work_dir if m == "code" else None

    set_mode(start_mode)
    out(f"{_DIM}amebo · {model} · shell {'on' if registered else 'off'}"
        f"{' · resumed' if resumed else ''}"
        f"{' · code' if mode['mode'] == 'code' else ''}"
        f"{'' if perms == 'ask' else ' · ' + perms} · /help{_RESET}")

    if resumed:
        _show_last_exchange(mgr, out)

    status = _Status()

    def confirm(command: str) -> bool:
        # The spinner redraws its line every 0.1s; stop it or it wipes the
        # prompt and what the person types.
        label = status.pause()
        try:
            if mode["perms"] == "skip":
                return _skip_confirm(command)
            return (_auto_confirm(command) if mode["perms"] == "auto"
                    else _terminal_confirm(command))
        finally:
            status.resume(label)

    def confirm_edit(path: str, diff: str) -> bool:
        if mode["perms"] in ("edit", "auto", "skip"):
            return True
        label = status.pause()
        try:
            return _terminal_confirm_edit(path, diff)
        finally:
            status.resume(label)

    tctx["confirm"] = confirm
    tctx["confirm_edit"] = confirm_edit

    def confirm_action(label: str) -> bool:
        # Write tools from the instance (Taiga, CRM, MAIN.md, ...). The person
        # is here, so a confirmed write runs now instead of drafting for approval.
        if mode["perms"] in ("auto", "skip"):
            return True
        label_was = status.pause()
        try:
            ans = input(f"\n  {_BOLD}{label}{_RESET}\n  run? [y/N] ").strip().lower()
        except EOFError:
            return False
        finally:
            status.resume(label_was)
        return ans in ("y", "yes")

    tctx["confirm_action"] = confirm_action
    last_trace: List[Tuple[str, str]] = []
    while True:
        try:
            line = (input(f"\n{_BOLD}you ›{_RESET} ") if reader is sys.stdin
                    else reader.readline())
        except EOFError:
            break
        except KeyboardInterrupt:
            out("")
            continue
        if not line and reader is not sys.stdin:
            break
        user = _valid_utf8(line).strip()
        if user in ("exit", "quit", "/exit", "/quit"):
            break
        if not user:
            continue
        if user in ("/help", "?"):
            out("  /tools    full output of the last turn's tool calls\n"
                "  /resume   list past sessions and switch to one (amebo -r; "
                "amebo -c resumes the last)\n"
                "  /session  this session's name\n"
                "  Ctrl-C    stop the current turn\n"
                "  /auto     toggle auto mode: commands run without asking "
                "(sudo, rm -rf, force-push, service stop still ask); amebo -y starts in it\n"
                "  /mode     default | code — code adds file editing, runs in the start "
                "directory (amebo --mode=code)\n"
                "  /model    show or switch: a provider (kimi, minimax, anthropic) or a "
                "model id, e.g. /model claude-opus-5-5 (amebo --model=…)\n"
                "  /permissions  ask | edit | auto | skip — what runs without asking "
                "(amebo --permissions=edit; skip: only sudo asks, amebo --skip-permissions)\n"
                "  exit      quit")
            continue
        if user in ("/auto", "/config"):
            mode["perms"] = "ask" if mode["perms"] == "auto" else "auto"
            on = mode["perms"] == "auto"
            out(f"  auto {'on' if on else 'off'}"
                + (" — commands run without asking; sudo, rm -rf, force-push, "
                   "service stop still ask" if on else " — every write asks"))
            continue
        if user == "/mode" or user.startswith("/mode "):
            arg = user[len("/mode"):].strip()
            if arg in _MODES:
                set_mode(arg)
            elif arg:
                out(f"  unknown mode '{arg}' — one of: {', '.join(_MODES)}")
                continue
            out(f"  mode {mode['mode']}"
                + (f" — file editing on, commands run in {work_dir}"
                   if mode["mode"] == "code" else ""))
            continue
        if user == "/model" or user.startswith("/model "):
            arg = user[len("/model"):].strip()
            if arg:
                picked = _pick_llm(arg)
                if isinstance(picked, str):
                    out(f"  {picked}")
                    continue
                llm["client"], llm["model"], llm["provider"] = picked
            out(f"  model {llm['model']} ({llm['provider']})")
            if not arg:
                out("  " + " · ".join(
                    f"{p} {'key set' if os.getenv(k) else 'no key (' + k + ')'}"
                    for p, k in _providers().items()))
            continue
        if user == "/permissions" or user.startswith("/permissions "):
            arg = user[len("/permissions"):].strip()
            if arg in _PERMISSIONS:
                mode["perms"] = arg
            elif arg:
                out(f"  unknown permissions '{arg}' — one of: {', '.join(_PERMISSIONS)}")
                continue
            out(f"  permissions {mode['perms']} — " + {
                "ask": "file edits and commands ask",
                "edit": "file edits run; commands ask",
                "auto": "everything runs; sudo, rm -rf, force-push, service stop still ask",
                "skip": "everything runs; sudo still asks",
            }[mode["perms"]])
            continue
        if user == "/resume" or user.startswith("/resume "):
            picked_ref = _choose_session(uid, user[len("/resume"):].strip(), out,
                                         current=session)
            if picked_ref:
                session = picked_ref
                mgr = ConversationManager(
                    source_type="cli", source_ref=session,
                    instance_slug=os.getenv("AMEBO_CLI_INSTANCE", "whatscookin"),
                )
                code_history.clear()
                last_trace = []
                _show_last_exchange(mgr, out)
            continue
        if user == "/session":
            out(f"  {session}")
            continue
        if user == "/tools":
            if not last_trace:
                out("  (no tool calls yet)")
            for label, res in last_trace:
                out(f"\n  {_BOLD}· {label}{_RESET}\n{_indent(res)}")
            continue

        # build_messages gives system(identity+rules) + persisted history + this
        # question, with NO per-turn knowledge stuffed in (knowledge_context="")
        # so the system prefix stays byte-stable and cacheable; tools fetch what
        # the model needs instead.
        system_prompt, messages = mgr.build_messages(new_question=user, knowledge_context="")
        system_prompt = system_prompt + _SHELL_NOTE
        coding = mode["mode"] == "code"
        if coding:
            system_prompt += code_note
        # Replay this session's turns WITH their tool calls. The stored history
        # is question/answer only; a model shown answers with no tool call
        # behind them claims edits it never made, and names sources it never
        # read ("which doc said that?").
        # Today's date rides on this question only: the system prefix stays
        # cacheable, and without it the model guessed dates ("due today
        # (2026-09-19)" two weeks late).
        messages[-1] = {**messages[-1], "content":
                        f"[{time.strftime('%Y-%m-%d %A')}] {messages[-1]['content']}"}
        if code_history:
            messages = code_history + [messages[-1]]
        last_trace = []
        work: List[Dict] = []
        notes: List[str] = []
        try:
            answer = _run_turn(llm["client"], llm["model"], system_prompt, messages,
                               tools_for(mode["mode"]), tctx,
                               principal, out, status, last_trace,
                               max_tokens=_CODE_MAX_TOKENS if coding else _MAX_TOKENS,
                               work_out=work,
                               max_rounds=_CODE_MAX_TOOL_ROUNDS if coding else _MAX_TOOL_ROUNDS,
                               notes=notes,
                               thinking=_thinking_for(llm["provider"]))
        except KeyboardInterrupt:
            status.stop()
            out(f"\n  {_DIM}interrupted{_RESET}")
            continue
        except Exception as exc:  # keep the session alive; show the cause
            status.stop()
            out(f"\n  error: {_error_line(exc, llm['provider'])}")
            continue
        # The shared rules let a Slack answer be "(silence)" or emoji only
        # (sent as nothing / a reaction). Here that would print as text.
        if not _NO_REPLY.match(answer):
            out(f"\n{_BOLD}amebo ›{_RESET} {_render(answer)}")
        for note in notes:
            out(f"  {_DIM}{note}{_RESET}")
        if not answer:
            # An empty assistant turn in the history makes MiniMax return no
            # content on every later call, so the session would be stuck.
            out(f"  {_DIM}(no answer came back — not saved; ask again){_RESET}")
            continue
        if work and work[-1]["role"] == "assistant" and work[-1]["content"] and \
                len(json.dumps(work)) // 4 < _CODE_HISTORY_MAX_TOKENS:
            code_history[:] = work
        else:
            code_history.clear()
        # Persist only the clean question/answer pair (not tool scaffolding) and
        # compact if over threshold.
        # Past the threshold this also summarizes older turns, a model call
        # that can take a while: show it, and let Ctrl-C skip it.
        status.start("saving")
        try:
            mgr.add_exchange(user, answer)
        except KeyboardInterrupt:
            out(f"\n  {_DIM}interrupted while saving — this exchange may not be in history{_RESET}")
        except Exception as exc:  # the answer is shown; don't lose the session
            out(f"\n  {_DIM}not saved to history: {exc}{_RESET}")
        finally:
            status.stop()
    return 0


def _log_to_file():
    """Backend modules log (and some call logging.basicConfig at INFO on
    import); in the terminal that printed tracebacks and every HTTP request
    into the transcript. Root logging goes to ~/.cache/amebo/cli.log instead;
    set before any of them import, so their basicConfig is a no-op."""
    import logging
    path = os.path.expanduser("~/.cache/amebo/cli.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler: logging.Handler = logging.FileHandler(path)
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)


def _valid_utf8(s: str) -> str:
    """Bytes that are not UTF-8 (a stray Latin-1 paste, a binary byte) reach
    Python as lone surrogates, which no API or database accepts. Turn them
    into U+FFFD so the rest of the line still goes through."""
    try:
        return s.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    except UnicodeEncodeError:
        return s.encode("utf-8", "replace").decode("utf-8")


_MD_BOLD = re.compile(r"\*\*(.+?)\*\*|(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")


_NO_REPLY = re.compile(r"^\s*([`:]*\(?silence\)?[`:]*|(:[a-z0-9_+\-]+:\s*)+)\s*$", re.IGNORECASE)


def _render(text: str) -> str:
    """Markdown/Slack bold (**x**, *x*) as terminal bold, without the
    asterisks. The identity prompt is written for Slack."""
    return _MD_BOLD.sub(lambda m: f"{_BOLD}{m.group(1) or m.group(2)}{_RESET}", text)


def _indent(s: str, n: int = 4) -> str:
    pad = " " * n
    return "\n".join(pad + ln for ln in str(s).splitlines())


if __name__ == "__main__":
    sys.exit(run_repl())
