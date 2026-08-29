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
    "Answer in plain text for a terminal: short lines, no headings, no tables. "
    "No closing offers or follow-up questions."
)

# The personal session's tool set: shell + amebo's safe read tools.
_PERSONAL_TOOLS = [
    "shell", "list_projects", "read_main_md", "search_knowledge_base",
    "abra_search", "lookup_contact", "web_search", "web_research",
]

# Tool rounds allowed within a single turn before we force an answer.
_MAX_TOOL_ROUNDS = int(os.getenv("AMEBO_CLI_MAX_TOOL_ROUNDS", "16"))
_MAX_TOKENS = int(os.getenv("AMEBO_CLI_MAX_TOKENS", "4000"))

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


def _auto_confirm(command: str) -> bool:
    norm = " ".join(command.split()).lower()
    if any(p in norm for p in _ALWAYS_ASK):
        return _terminal_confirm(command)
    return True


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


def _serialize_blocks(content) -> List[Dict]:
    """SDK content blocks -> plain dicts, so the next request re-serializes them
    identically (raw SDK blocks can hit a re-serialization bug and shift bytes)."""
    out = []
    for b in content:
        if b.type == "text":
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


def _run_turn(client, model, system_prompt, messages, tools, tctx, principal,
              out, status, trace: List[Tuple[str, str]]) -> str:
    """One user turn: call the model, run tool rounds, return the final text.
    `messages` is the full history+question from ConversationManager.build_messages;
    tool-round scaffolding stays local and is NOT persisted (only the final answer
    is), keeping the cross-turn prefix clean and byte-stable. Each tool call is
    printed as one line; its output goes to `trace` (for /tools), not the screen."""
    from src.tools.registry import get_tool, trust_gate

    work = list(messages)
    for _round in range(_MAX_TOOL_ROUNDS + 1):
        system_blocks, cached = _cache_prefix(system_prompt, work)
        kwargs = dict(model=model, max_tokens=_MAX_TOKENS,
                      system=system_blocks, messages=cached)
        if tools:
            kwargs["tools"] = tools
        # Last round: force an answer instead of another tool call.
        if _round == _MAX_TOOL_ROUNDS and tools:
            kwargs["tool_choice"] = {"type": "none"}
        status.start("thinking")
        try:
            resp = client.messages.create(**kwargs)
        finally:
            status.stop()

        work.append({"role": "assistant", "content": _serialize_blocks(resp.content)})
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text").strip()

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
                if denial:
                    res = denial
                else:
                    status.start(label)
                    try:
                        res = tool.execute(b.input, tctx) or ""
                    finally:
                        status.stop()
            trace.append((label, str(res)))
            room = _width() - 4
            summary = _one_line(_result_summary(res), room // 3)
            line = _one_line(label, room - len(summary) - 3)
            out(f"  {_DIM}· {line} ⎿ {summary}{_RESET}")
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": res})
        work.append({"role": "user", "content": results})
    return "(no answer)"


def _resume_session(uid: int) -> Optional[str]:
    """source_ref of this user's most recent CLI session, if any."""
    from src.db.repositories.thread_repo import ThreadRepo
    row = ThreadRepo().latest_by_ref_prefix("cli", f"cli-{uid}-")
    return row["source_ref"] if row else None


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
    auto = any(a in ("-y", "--yes") for a in argv) or os.getenv("AMEBO_CLI_AUTO") == "1"

    # Provider/model are config, decoupled from this mode. Override for THIS
    # process only; the Slack service keeps whatever it was started with.
    if os.getenv("AMEBO_CLI_PROVIDER"):
        os.environ["AMEBO_LLM_PROVIDER"] = os.environ["AMEBO_CLI_PROVIDER"]

    from src.tools.shell_tool import register_shell_tool_if_personal
    registered = register_shell_tool_if_personal()
    from src.tools.registry import get_tool, _tool_to_schema
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

    tools = [_tool_to_schema(get_tool(n)) for n in _PERSONAL_TOOLS if get_tool(n)]

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

    # Persistent thread → history is stored verbatim and replayed byte-identically
    # each turn, which is what makes the prefix cache hit. `-c` resumes the last
    # session; AMEBO_CLI_SESSION names one; default is fresh per process.
    uid = os.getuid()
    session = os.getenv("AMEBO_CLI_SESSION")
    resumed = False
    if not session and resume:
        session = _resume_session(uid)
        resumed = session is not None
    session = session or f"cli-{uid}-{os.getpid()}"
    mgr = ConversationManager(
        source_type="cli", source_ref=session,
        instance_slug=os.getenv("AMEBO_CLI_INSTANCE", "whatscookin"),
    )

    reader = in_stream or sys.stdin
    interactive = reader is sys.stdin and sys.stdin.isatty()
    if interactive:
        _setup_readline()
    out(f"{_DIM}amebo · {model} · shell {'on' if registered else 'off'}"
        f"{' · resumed' if resumed else ''}{' · auto' if auto else ''} · /help{_RESET}")

    tctx = {"org_context": ctx, "org_id": org_id, "confirm": _auto_confirm if auto else _terminal_confirm}
    status = _Status()
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
        user = line.strip()
        if user in ("exit", "quit", "/exit", "/quit"):
            break
        if not user:
            continue
        if user in ("/help", "?"):
            out("  /tools    full output of the last turn's tool calls\n"
                "  /session  this session's name (resume: amebo -c, or "
                "AMEBO_CLI_SESSION=<name> amebo)\n"
                "  Ctrl-C    stop the current turn\n"
                "  amebo -y  auto mode: commands run without asking "
                "(sudo, rm -rf, force-push, service stop still ask)\n"
                "  exit      quit")
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
        last_trace = []
        try:
            answer = _run_turn(client, model, system_prompt, messages, tools, tctx,
                               principal, out, status, last_trace)
        except KeyboardInterrupt:
            status.stop()
            out(f"\n  {_DIM}interrupted{_RESET}")
            continue
        except Exception as exc:  # keep the session alive; show the cause
            status.stop()
            out(f"\n  error: {exc}")
            continue
        out(f"\n{_BOLD}amebo ›{_RESET} {answer}")
        # Persist only the clean question/answer pair (not tool scaffolding) and
        # compact if over threshold.
        mgr.add_exchange(user, answer)
    return 0


def _indent(s: str, n: int = 4) -> str:
    pad = " " * n
    return "\n".join(pad + ln for ln in str(s).splitlines())


if __name__ == "__main__":
    sys.exit(run_repl())
