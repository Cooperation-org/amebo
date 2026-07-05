"""
Tools for reading and editing project MAIN.md files.

These let the claw inspect and update the team's project metadata in the
acting org's projects directory (from its org.yaml `projects` connection;
the shared legacy root only for LEGACY_ENV_ORG_ID until the WP17 cutover).
Every project has a MAIN.md describing
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


def _projects_root(context: Any = None) -> Path:
    """The acting org's active-projects root (arch §5), from the org's org.yaml
    `projects` connection config ({path, active_dir}).

    Fallback to the shared ACTIVE_PROJECTS_ROOT is allowed ONLY for the
    designated legacy org (env LEGACY_ENV_ORG_ID, = linkedtrust until the WP17
    cutover seeds its manifest) — same rule as cli_read_tools._conn. For every
    other org a missing/broken manifest RAISES: the shared root belongs to the
    legacy org, and these tools WRITE (create/edit MAIN.md), so a silent
    fallback would land org B's files in org A's repo. The path-traversal guard
    below is applied relative to whatever root this returns, so it stays
    exactly as strict per-org."""
    from src.tools.cli_read_tools import _org_id_from_context
    org_id = _org_id_from_context(context)
    if org_id is None:
        # No org in context at all: legacy direct paths (pre-OrgContext) only.
        return ACTIVE_PROJECTS_ROOT
    legacy = os.getenv("LEGACY_ENV_ORG_ID", "")
    is_legacy_org = legacy != "" and str(org_id) == legacy
    from src.credentials.connections import (
        resolve, ToolNotConfigured, ManifestInvalid,
    )
    try:
        cfg = resolve(org_id, "projects").config or {}
    except (ToolNotConfigured, ManifestInvalid):
        if is_legacy_org:
            return ACTIVE_PROJECTS_ROOT
        raise
    except Exception:
        logger.exception("projects connection resolve failed org=%s", org_id)
        if is_legacy_org:
            return ACTIVE_PROJECTS_ROOT
        raise
    base = cfg.get("path")
    if not base:
        if is_legacy_org:
            return ACTIVE_PROJECTS_ROOT
        raise ToolNotConfigured(org_id, "projects", "no 'path' in projects config")
    root = Path(base)
    if cfg.get("active_dir"):
        root = root / cfg["active_dir"]
    return root.resolve()


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


def _project_dir(slug: str, context: Any = None) -> Path:
    """
    Resolve the project's directory and assert it sits under the acting org's
    projects root. Any path that tries to escape the root via symlinks or '..'
    is rejected. The guard is relative to the per-org root (arch §5).
    """
    slug = _validate_slug(slug)
    root = _projects_root(context)
    candidate = (root / slug).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PermissionError(
            f"project_slug {slug!r} resolves outside the active-projects root."
        ) from exc
    return candidate


def _project_main_md(slug: str, context: Any = None) -> Path:
    return _project_dir(slug, context) / MAIN_MD_FILENAME


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------


def list_projects_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    entries: List[str] = []
    root = _projects_root(context)
    try:
        for name in sorted(os.listdir(root)):
            entry_path = root / name
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
        path = _project_main_md(slug_raw or "", context)
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
            "description": "Slug of the project (directory name in the org's projects directory).",
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
        path = _project_main_md(slug_raw or "", context)
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


# ---------------------------------------------------------------------------
# create_main_md
# ---------------------------------------------------------------------------

MAX_CREATE_BYTES = 32 * 1024   # a MAIN.md should be well under this
MIN_CREATE_BYTES = 40          # refuse near-empty stubs


def create_main_md_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    Create a NEW MAIN.md for a project under the active-projects root.

    Refuses to overwrite an existing MAIN.md (use edit_main_md for changes to
    one that already exists). Creates the project directory if it does not yet
    exist. Same path guard as read/edit: the slug must resolve inside
    ACTIVE_PROJECTS_ROOT. The file lands on disk uncommitted; a human reviews
    via git diff before committing.
    """
    slug_raw = tool_input.get("project_slug")
    content = tool_input.get("content")

    if not isinstance(content, str):
        return "Error: content is required and must be a string."
    content = content.strip("\n") + "\n"
    body_len = len(content.encode("utf-8"))
    if body_len < MIN_CREATE_BYTES:
        return (
            f"Error: content is too short ({body_len} bytes). Write a real "
            "MAIN.md following the pattern of an existing project (read one "
            "first with read_main_md)."
        )
    if body_len > MAX_CREATE_BYTES:
        return f"Error: content must be <= {MAX_CREATE_BYTES} bytes; got {body_len}."

    try:
        directory = _project_dir(slug_raw or "", context)
    except (ValueError, PermissionError) as exc:
        return f"Error: {exc}"

    path = directory / MAIN_MD_FILENAME
    if path.exists():
        return (
            f"Error: {path} already exists — refusing to overwrite. Use "
            "edit_main_md to change an existing MAIN.md."
        )

    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return f"Error creating {path}: {exc}"

    logger.info("create_main_md wrote %s (%d bytes)", path, body_len)
    return (
        f"Created {path} ({body_len} bytes). The file is on disk (uncommitted "
        "in git) — a human reviews via git diff before it is committed."
    )


CREATE_MAIN_MD_SCHEMA = {
    "type": "object",
    "properties": {
        "project_slug": {
            "type": "string",
            "description": (
                "Slug for the project — the directory name in the org's "
                "projects directory. Lowercase, no spaces. The "
                "directory is created if it does not exist."
            ),
        },
        "content": {
            "type": "string",
            "description": (
                "Full Markdown body of the new MAIN.md. Follow the exact "
                "pattern of an existing project's MAIN.md (read one first with "
                "read_main_md): title, one-line description, Team Lead / Slack "
                "Channel, key links, and background. Use the team's own words; "
                "do not invent facts."
            ),
        },
    },
    "required": ["project_slug", "content"],
}
