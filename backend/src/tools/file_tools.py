"""
File tools for the personal CLI's code mode: read_file, edit_file, write_file.

Registered only in a verified personal session (same guard as `shell`), never
via config.allowed_tools, so the hosted service never has them. Offered to the
model only in `--mode=code`.

Relative paths resolve against context["cwd"] (the directory amebo was started
in). Changes go through context["confirm_edit"](path, diff) — the session's
permission mode decides whether that asks the human. No confirm available →
refuse, like `shell`.
"""

from __future__ import annotations

import difflib
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

MAX_READ_LINES = 2000
MAX_DIFF_LINES = 60


def _resolve(path: str, context: Dict[str, Any]) -> str:
    path = os.path.expanduser(path or "")
    if not os.path.isabs(path):
        path = os.path.join((context or {}).get("cwd") or os.getcwd(), path)
    return os.path.normpath(path)


def _diff(path: str, before: str, after: str) -> str:
    lines = list(difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile=path, tofile=path, lineterm="", n=2))
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES] + [f"…[{len(lines) - MAX_DIFF_LINES} more diff lines]"]
    return "\n".join(lines)


def _approve(path: str, before: str, after: str, context: Dict[str, Any]):
    """Ask confirm_edit with the diff; None if approved, else the refusal string.
    Paths under the working directory are shown relative to it."""
    confirm = (context or {}).get("confirm_edit")
    if not callable(confirm):
        return ("Refused: this session has no way to confirm a file change. "
                "Only a personal session with a human at the keyboard can edit files.")
    cwd = (context or {}).get("cwd")
    shown = os.path.relpath(path, cwd) if cwd and path.startswith(cwd.rstrip("/") + "/") else path
    if not confirm(shown, _diff(shown, before, after)):
        return "Declined by the user — file not changed."
    return None


def read_file_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    path = _resolve(tool_input.get("path"), context)
    offset = max(int(tool_input.get("offset") or 1), 1)
    limit = min(int(tool_input.get("limit") or MAX_READ_LINES), MAX_READ_LINES)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError as exc:
        return f"Error: {exc}"
    chunk = lines[offset - 1: offset - 1 + limit]
    out = "\n".join(f"{i:>6}\t{ln}" for i, ln in enumerate(chunk, start=offset))
    rest = len(lines) - (offset - 1 + len(chunk))
    if rest > 0:
        out += f"\n…[{rest} more lines; read again with offset={offset + len(chunk)}]"
    return out or "(empty file)"


def edit_file_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    path = _resolve(tool_input.get("path"), context)
    old = tool_input.get("old_string")
    new = tool_input.get("new_string")
    replace_all = bool(tool_input.get("replace_all"))
    if not old or new is None:
        return "Error: old_string and new_string are required."
    try:
        with open(path, encoding="utf-8") as f:
            before = f.read()
    except OSError as exc:
        return f"Error: {exc}"
    n = before.count(old)
    if n == 0:
        return "Error: old_string not found in the file."
    if n > 1 and not replace_all:
        return (f"Error: old_string appears {n} times. Include more context to "
                "make it unique, or set replace_all.")
    after = before.replace(old, new) if replace_all else before.replace(old, new, 1)
    refusal = _approve(path, before, after, context)
    if refusal:
        return refusal
    with open(path, "w", encoding="utf-8") as f:
        f.write(after)
    return f"Edited {path} ({n if replace_all else 1} replacement{'s' if replace_all and n > 1 else ''})."


def write_file_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    path = _resolve(tool_input.get("path"), context)
    content = tool_input.get("content")
    if content is None:
        return "Error: content is required."
    before = ""
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                before = f.read()
        except OSError as exc:
            return f"Error: {exc}"
    refusal = _approve(path, before, content, context)
    if refusal:
        return refusal
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        return f"Error: directory does not exist: {parent}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Wrote {path} ({content.count(chr(10)) + 1} lines)."


FILE_TOOL_NAMES = ["read_file", "edit_file", "write_file"]


def register_file_tools_if_personal() -> bool:
    """Register read_file / edit_file / write_file — ONLY in a verified personal
    session. Returns True if registered."""
    from src.tools.shell_tool import is_verified_personal
    if not is_verified_personal():
        return False

    from src.tools.registry import register_tool, Tool
    register_tool(Tool(
        name="read_file",
        description="Read a text file with line numbers. Relative paths are from the working directory.",
        input_schema={"type": "object", "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "description": "First line to read (1-based)."},
            "limit": {"type": "integer", "description": f"Lines to read (max {MAX_READ_LINES})."},
        }, "required": ["path"]},
        execute=read_file_impl,
        is_read_only=True,
        access_class="admin",
        category="personal",
    ))
    register_tool(Tool(
        name="edit_file",
        description=("Change a file by replacing an exact string. old_string must "
                     "match exactly once unless replace_all is set. Read the file first."),
        input_schema={"type": "object", "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean"},
        }, "required": ["path", "old_string", "new_string"]},
        execute=edit_file_impl,
        is_read_only=False,
        access_class="admin",
        category="personal",
    ))
    register_tool(Tool(
        name="write_file",
        description="Create a file, or replace a whole file's content.",
        input_schema={"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        }, "required": ["path", "content"]},
        execute=write_file_impl,
        is_read_only=False,
        access_class="admin",
        category="personal",
    ))
    logger.info("personal file tools registered (uid=%s)", os.getuid())
    return True
