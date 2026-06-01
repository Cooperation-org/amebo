"""
Tools for reading and editing project MAIN.md files.

These let the claw inspect and update the team's project metadata in
`/opt/shared/projects/Active/`. Every project has a MAIN.md describing
team lead, slack channel, repos, links, etc. The claw's job is to keep
those in sync with what's actually happening (mostly inferred from
recent Slack activity).

Security boundary: the edit tool refuses to touch ANY path outside the
active-projects directory. The path is resolved with `Path.resolve()`
so symlinks don't slip past.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


ACTIVE_PROJECTS_ROOT = Path("/opt/shared/projects/Active").resolve()
MAIN_MD_FILENAME = "MAIN.md"
MAX_READ_BYTES = 64 * 1024     # plenty for a MAIN.md
MAX_OLD_NEW_LEN = 4096          # cap edit string sizes


_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _validate_slug(slug: str) -> str:
    if not isinstance(slug, str):
        raise ValueError("project_slug must be a string.")
    slug = slug.strip()
    if not slug:
        raise ValueError("project_slug is required.")
    if not _SLUG_RE.match(slug):
        raise ValueError(
            f"project_slug must match {_SLUG_RE.pattern!r}; got {slug!r}."
        )
    return slug


def _project_dir(slug: str) -> Path:
    """
    Resolve the project's directory and assert it sits under
    ACTIVE_PROJECTS_ROOT. Any path that tries to escape the root via
    symlinks or '..' is rejected.
    """
    slug = _validate_slug(slug)
    candidate = (ACTIVE_PROJECTS_ROOT / slug).resolve()
    try:
        candidate.relative_to(ACTIVE_PROJECTS_ROOT)
    except ValueError as exc:
        raise PermissionError(
            f"project_slug {slug!r} resolves outside the active-projects root."
        ) from exc
    return candidate


def _project_main_md(slug: str) -> Path:
    return _project_dir(slug) / MAIN_MD_FILENAME


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------


def list_projects_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    entries: List[str] = []
    try:
        for name in sorted(os.listdir(ACTIVE_PROJECTS_ROOT)):
            entry_path = ACTIVE_PROJECTS_ROOT / name
            if not entry_path.is_dir():
                continue
            if (entry_path / MAIN_MD_FILENAME).is_file():
                entries.append(name)
    except OSError as exc:
        return f"Error: could not list active projects: {exc}"

    if not entries:
        return "No active projects with MAIN.md found."
    return "Active projects (slugs):\n" + "\n".join(f"  - {e}" for e in entries)


LIST_PROJECTS_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
}


# ---------------------------------------------------------------------------
# read_main_md
# ---------------------------------------------------------------------------


def read_main_md_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    slug_raw = tool_input.get("project_slug")
    try:
        path = _project_main_md(slug_raw or "")
    except (ValueError, PermissionError) as exc:
        return f"Error: {exc}"

    if not path.is_file():
        return f"Error: no MAIN.md found for project {slug_raw!r}."

    try:
        with path.open("rb") as fh:
            raw = fh.read(MAX_READ_BYTES + 1)
    except OSError as exc:
        return f"Error reading {path}: {exc}"

    truncated = len(raw) > MAX_READ_BYTES
    text = raw[:MAX_READ_BYTES].decode("utf-8", errors="replace")
    header = f"Project: {slug_raw}\nPath: {path}\n"
    if truncated:
        header += f"[truncated to {MAX_READ_BYTES} bytes]\n"
    return header + "\n" + text


READ_MAIN_MD_SCHEMA = {
    "type": "object",
    "properties": {
        "project_slug": {
            "type": "string",
            "description": "Slug of the project (directory name under /opt/shared/projects/Active/).",
        },
    },
    "required": ["project_slug"],
}


# ---------------------------------------------------------------------------
# edit_main_md
# ---------------------------------------------------------------------------


def _diff_lines(before: str, after: str, context_lines: int = 1) -> str:
    """
    Tiny unified-diff-style summary so the model and the human can see what
    changed without pulling in the difflib dep noise. Lossy but readable.
    """
    import difflib
    diff = difflib.unified_diff(
        before.splitlines(keepends=False),
        after.splitlines(keepends=False),
        fromfile="before",
        tofile="after",
        n=context_lines,
        lineterm="",
    )
    return "\n".join(diff)


def edit_main_md_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    slug_raw = tool_input.get("project_slug")
    old_string = tool_input.get("old_string")
    new_string = tool_input.get("new_string")

    if not isinstance(old_string, str) or not isinstance(new_string, str):
        return "Error: old_string and new_string are both required strings."
    if len(old_string) == 0:
        return "Error: old_string cannot be empty."
    if len(old_string) > MAX_OLD_NEW_LEN or len(new_string) > MAX_OLD_NEW_LEN:
        return f"Error: edit strings must be <= {MAX_OLD_NEW_LEN} chars each."
    if old_string == new_string:
        return "Error: old_string and new_string are identical — no edit to make."

    try:
        path = _project_main_md(slug_raw or "")
    except (ValueError, PermissionError) as exc:
        return f"Error: {exc}"

    if not path.is_file():
        return f"Error: no MAIN.md found for project {slug_raw!r}."

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"Error reading {path}: {exc}"

    occurrences = content.count(old_string)
    if occurrences == 0:
        return (
            "Error: old_string not found in file. Read the file first and use "
            "an exact substring."
        )
    if occurrences > 1:
        return (
            f"Error: old_string occurs {occurrences} times; must be unique. "
            "Include more surrounding context."
        )

    new_content = content.replace(old_string, new_string, 1)
    try:
        path.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        return f"Error writing {path}: {exc}"

    logger.info("edit_main_md applied to %s", path)

    diff = _diff_lines(content, new_content, context_lines=1)
    return (
        f"Edited {path}. The change is on disk (uncommitted in git).\n\n"
        f"Diff:\n{diff}"
    )


EDIT_MAIN_MD_SCHEMA = {
    "type": "object",
    "properties": {
        "project_slug": {
            "type": "string",
            "description": "Slug of the project to edit.",
        },
        "old_string": {
            "type": "string",
            "description": "Exact substring currently in MAIN.md. Must be unique.",
        },
        "new_string": {
            "type": "string",
            "description": "Replacement text. May be empty to delete the old_string.",
        },
    },
    "required": ["project_slug", "old_string", "new_string"],
}
