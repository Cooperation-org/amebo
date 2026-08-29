"""
General `shell` tool — Claude-Code-style, for a PERSONAL amebo session only.

This is the powerful primitive Golda wanted: one tool that runs any command, not
a menu of hand-written per-command tools. Safety is by IDENTITY + LOCATION +
CONFIRM, not by command-string classification:

  - It is registered in CODE, never via config.allowed_tools, and ONLY when the
    process is a verified personal session — AMEBO_PERSONAL_MODE=1, running as
    the declared owner's uid, and NOT the amebo service uid. The hosted service
    never calls the register function, so it never has this tool (I10, Fable B).
  - Permission = Claude Code's, NOT the draft-approval queue (that gate is for
    acting-as-amebo in shared spaces). A small read-only allowlist auto-runs;
    everything else needs a synchronous human confirm supplied by the session
    (context["confirm"]). No confirm available → refuse (Fable C).
  - Timeouts + output truncation like Claude Code's Bash.

Structured outbound tools (slack_post, CRM, Taiga) stay gated exactly as today —
this changes nothing there.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from typing import Any, Dict

logger = logging.getLogger(__name__)

SHELL_TIMEOUT_S = 60
MAX_OUTPUT = 20_000

# First-token commands safe to auto-run (read-only). Everything else confirms.
_READONLY_CMDS = {
    "ls", "cat", "rg", "grep", "egrep", "fgrep", "pwd", "head", "tail", "wc",
    "find", "tree", "which", "type", "echo", "printf", "date", "df", "du",
    "stat", "file", "env", "printenv", "whoami", "id", "hostname", "uname",
    "uptime", "free", "ps", "cut", "sort", "uniq", "diff", "tr", "nl",
    "column", "jq", "awk", "basename", "dirname", "realpath", "readlink",
    "md5sum", "sha256sum", "true", "test", "[", "cd", "less", "more",
    "ss", "journalctl", "abra", "systemctl", "sed", "curl",
}
# Commands from the list that are read-only ONLY with these first arguments.
_SUBCMD_READONLY = {
    "systemctl": {"status", "is-active", "is-enabled", "list-units", "show", "cat"},
    "abra": {"search", "about", "read", "who", "names", "related", "refs", "when"},
}
# sed/curl: read-only unless they write.
_WRITE_FLAGS = {
    "sed": ("-i",),
    "curl": ("-o", "-O", "--output", "-T", "--upload-file", "-d", "--data",
             "-F", "--form", "-X"),
}
# git subcommands that only read.
_GIT_READONLY = {
    "status", "log", "diff", "show", "branch", "remote", "ls-files", "grep",
    "rev-parse", "describe", "blame", "shortlog", "config", "ls-tree",
    "cat-file", "reflog", "rev-list", "name-rev", "ls-remote", "fetch",
}
# Metacharacters that can hide a write inside a "read" command line.
# Pipes and && / || / ; are allowed: each segment is classified on its own.
_UNSAFE_CHARS = set("><`$")


def _segments(command: str):
    """Split a command line on | || && ; into simple commands (quote-aware).
    Returns a list of token lists, or None if the line cannot be parsed."""
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return None
    segs, cur = [], []
    for t in toks:
        if t in ("|", "||", "&&", ";"):
            if cur:
                segs.append(cur)
            cur = []
        elif t in ("&", ">", ">>", "<", "<<", "(", ")"):
            return None
        else:
            cur.append(t)
    if cur:
        segs.append(cur)
    return segs


def _simple_is_readonly(toks) -> bool:
    if not toks:
        return False
    cmd = os.path.basename(toks[0])
    if cmd == "git":
        # Find the git subcommand, skipping global options (e.g. -C <path>,
        # -c <k=v>) so `git -C /repo log` is recognized as the read `log`.
        _takes_value = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
        i = 1
        while i < len(toks):
            t = toks[i]
            if t in _takes_value:
                i += 2
            elif t.startswith("-"):
                i += 1
            else:
                return t in _GIT_READONLY
        return False
    if cmd not in _READONLY_CMDS:
        return False
    if cmd in _SUBCMD_READONLY:
        return len(toks) > 1 and toks[1] in _SUBCMD_READONLY[cmd]
    if cmd in _WRITE_FLAGS:
        flags = _WRITE_FLAGS[cmd]
        return not any(t == f or t.startswith(f + "=") or
                       (f.startswith("-") and not f.startswith("--") and t.startswith(f) and len(t) > 2 and cmd == "sed")
                       for t in toks[1:] for f in flags)
    return True


def _is_readonly(command: str) -> bool:
    """True only if every simple command on the line is unambiguously a read."""
    if any(c in _UNSAFE_CHARS for c in command):
        return False  # redirect / subshell / backtick could hide a write
    segs = _segments(command)
    if not segs:
        return False
    return all(_simple_is_readonly(toks) for toks in segs)


def shell_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    command = (tool_input.get("command") or "").strip()
    if not command:
        return "Error: command is required."

    if not _is_readonly(command):
        # Not obviously read-only → need a human confirm from the session.
        confirm = (context or {}).get("confirm")
        if not callable(confirm):
            return ("Refused: that is not a read-only command and this session "
                    "has no way to confirm it. Only a personal session with a "
                    "human at the keyboard can run non-read commands.")
        if not confirm(command):
            return "Declined by the user — command not run."

    try:
        result = subprocess.run(
            ["bash", "-lc", command],
            capture_output=True, text=True, timeout=SHELL_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {SHELL_TIMEOUT_S}s."
    except Exception as exc:  # never let a shell error crash the loop
        logger.exception("shell run failed")
        return f"Error running command: {exc}"

    out = (result.stdout or "").rstrip()
    if result.stderr and result.stderr.strip():
        out = (out + "\n[stderr] " + result.stderr.strip()).strip()
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + f"\n…[truncated, {len(out)} chars total]"
    if result.returncode != 0:
        return f"[exit {result.returncode}]\n{out or '(no output)'}"
    return out or "(no output)"


SHELL_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": ("A shell command to run in this personal session (bash -lc). "
                            "Read-only commands run immediately; anything else asks the "
                            "human to confirm first."),
        },
    },
    "required": ["command"],
}


def register_shell_tool_if_personal() -> bool:
    """Register `shell` — ONLY in a verified personal session. Returns True if it
    was registered. Guards (I10, Fable B): AMEBO_PERSONAL_MODE=1, the process is
    running as the declared owner uid (AMEBO_PERSONAL_UID), and NOT the amebo
    service uid (AMEBO_SERVICE_UID). Call this at personal-process startup only —
    the hosted service never calls it, so it never has shell.
    """
    if os.getenv("AMEBO_PERSONAL_MODE") != "1":
        return False
    owner = os.getenv("AMEBO_PERSONAL_UID", "")
    if not owner.isdigit():
        logger.error("personal shell: AMEBO_PERSONAL_UID unset/invalid; not registering")
        return False
    if os.getuid() != int(owner):
        logger.error("personal shell: process uid %s != owner uid %s; not registering",
                     os.getuid(), owner)
        return False
    svc = os.getenv("AMEBO_SERVICE_UID", "")
    if svc.isdigit() and os.getuid() == int(svc):
        logger.error("personal shell: running as the service uid; hard refuse")
        return False

    from src.tools.registry import register_tool, Tool
    register_tool(Tool(
        name="shell",
        description=("Run a shell command in THIS personal session (as the owner). "
                     "Read-only commands run immediately; other commands ask the "
                     "human to confirm first. Use for git, builds, file ops, etc."),
        input_schema=SHELL_SCHEMA,
        execute=shell_impl,
        is_read_only=False,
        access_class="admin",   # trust gate: only a T2/admin principal may call it
        category="personal",
    ))
    logger.info("personal shell tool registered (uid=%s)", os.getuid())
    return True
