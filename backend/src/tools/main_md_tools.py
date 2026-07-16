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
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


ACTIVE_PROJECTS_ROOT = Path("/opt/shared/projects/Active").resolve()
MAIN_MD_FILENAME = "MAIN.md"
MAX_READ_BYTES = 64 * 1024     # plenty for a MAIN.md
MAX_OLD_NEW_LEN = 4096          # cap edit string sizes


def _projects_root(context: Any = None, area: Optional[str] = None) -> Path:
    """The acting org's active-projects root (arch §5), from the org's org.yaml
    `projects` connection config ({path, active_dir}).

    Fallback to the shared ACTIVE_PROJECTS_ROOT is allowed ONLY for the
    designated legacy org (env LEGACY_ENV_ORG_ID, = linkedtrust until the WP17
    cutover seeds its manifest) — same rule as cli_read_tools._conn. For every
    other org a missing/broken manifest RAISES: the shared root belongs to the
    legacy org, and these tools WRITE (create/edit MAIN.md), so a silent
    fallback would land org B's files in org A's repo. The path-traversal guard
    below is applied relative to whatever root this returns, so it stays
    exactly as strict per-org.

    `area` selects a named directory from the org's projects config
    (`named_dirs: {campaigns: campaigns, ...}` in org.yaml) instead of the
    active-projects dir. Area names are org data (I3) — core never knows what
    they mean. An area the org hasn't declared is refused, never guessed."""
    from src.tools.cli_read_tools import _org_id_from_context
    org_id = _org_id_from_context(context)
    if org_id is None:
        # No org in context at all: legacy direct paths (pre-OrgContext) only.
        if area:
            raise ValueError(
                f"named area '{area}' requires an org context (org.yaml named_dirs)"
            )
        return ACTIVE_PROJECTS_ROOT
    from src.credentials.connections import env_credentials_shared
    legacy = os.getenv("LEGACY_ENV_ORG_ID", "")
    # Shared-env deployments (cohort VMs): every org may use the shared root.
    is_legacy_org = env_credentials_shared() or (legacy != "" and str(org_id) == legacy)
    from src.credentials.connections import (
        resolve, ToolNotConfigured, ManifestInvalid,
    )
    try:
        cfg = resolve(org_id, "projects").config or {}
    except (ToolNotConfigured, ManifestInvalid):
        if is_legacy_org and not area:
            return ACTIVE_PROJECTS_ROOT
        raise
    except Exception:
        logger.exception("projects connection resolve failed org=%s", org_id)
        if is_legacy_org and not area:
            return ACTIVE_PROJECTS_ROOT
        raise
    base = cfg.get("path")
    if not base:
        if is_legacy_org and not area:
            return ACTIVE_PROJECTS_ROOT
        raise ToolNotConfigured(org_id, "projects", "no 'path' in projects config")
    root = Path(base)
    if area:
        named = cfg.get("named_dirs") or {}
        sub = named.get(area)
        if not sub:
            raise ToolNotConfigured(
                org_id, "projects",
                f"no named dir '{area}' in projects config (has: {sorted(named) or 'none'})",
            )
        return (root / str(sub)).resolve()
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


def _tool_area(tool_input: Dict[str, Any]) -> Optional[str]:
    """The optional named-area input, normalized ('' → None)."""
    raw = tool_input.get("area")
    if not isinstance(raw, str):
        return None
    return raw.strip() or None


def _project_dir(slug: str, context: Any = None, area: Optional[str] = None) -> Path:
    """
    Resolve the project's directory and assert it sits under the acting org's
    projects root (or the named area's root). Any path that tries to escape
    the root via symlinks or '..' is rejected. The guard is relative to the
    per-org root (arch §5).
    """
    slug = _validate_slug(slug)
    root = _projects_root(context, area)
    candidate = (root / slug).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PermissionError(
            f"project_slug {slug!r} resolves outside the active-projects root."
        ) from exc
    return candidate


def _project_main_md(slug: str, context: Any = None, area: Optional[str] = None) -> Path:
    return _project_dir(slug, context, area) / MAIN_MD_FILENAME


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------


def list_projects_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    entries: List[str] = []
    root = _projects_root(context, _tool_area(tool_input))
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
    "properties": {
        "area": {
            "type": "string",
            "description": (
                "Optional named area from the org's projects config "
                "(org.yaml named_dirs, e.g. 'campaigns'). Default: the "
                "active projects directory."
            ),
        },
    },
    "required": [],
}


# ---------------------------------------------------------------------------
# read_main_md
# ---------------------------------------------------------------------------


def read_main_md_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    slug_raw = tool_input.get("project_slug")
    try:
        path = _project_main_md(slug_raw or "", context, _tool_area(tool_input))
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
        "area": {
            "type": "string",
            "description": (
                "Optional named area from the org's projects config "
                "(org.yaml named_dirs, e.g. 'campaigns'). Default: the "
                "active projects directory."
            ),
        },
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
        path = _project_main_md(slug_raw or "", context, _tool_area(tool_input))
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
        "area": {
            "type": "string",
            "description": (
                "Optional named area from the org's projects config "
                "(org.yaml named_dirs, e.g. 'campaigns'). Default: the "
                "active projects directory."
            ),
        },
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
        directory = _project_dir(slug_raw or "", context, _tool_area(tool_input))
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
        "area": {
            "type": "string",
            "description": (
                "Optional named area from the org's projects config "
                "(org.yaml named_dirs, e.g. 'campaigns'). Default: the "
                "active projects directory."
            ),
        },
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


# ---------------------------------------------------------------------------
# read_org_file — read ANY file inside the org's context repo (read-only)
# ---------------------------------------------------------------------------
#
# Research needs more than MAIN.md files: proposals, notes, templates, README
# conventions. This reads (or lists) any path inside the acting org's context
# repo — the repo pointer from amebo's own DB (arch §2.2), no manifest needed
# for reads. Same guard discipline as the MAIN.md tools: resolve() the path,
# assert containment, refuse .git, cap the bytes.


def _org_repo_root(context: Any) -> Path:
    """The acting org's context-repo root, from organizations.context_repo.
    Strict: requires an org in context and a configured pointer — a repo read
    can never fall through to another org's repo."""
    from src.tools.cli_read_tools import _org_id_from_context
    org_id = _org_id_from_context(context)
    if org_id is None:
        raise ValueError("read_org_file requires an org context.")
    from src.credentials.connections import _org_context_repo
    repo = _org_context_repo(org_id)
    if not repo:
        raise ValueError(f"org {org_id} has no context repo configured.")
    root = Path(repo).resolve()
    if not root.is_dir():
        raise ValueError(f"org {org_id} context repo path does not exist on this host.")
    return root


def read_org_file_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    rel = tool_input.get("path")
    if not isinstance(rel, str) or not rel.strip():
        return "Error: path is required (relative to the org's repo root; '.' lists the root)."
    rel = rel.strip().lstrip("/")

    try:
        root = _org_repo_root(context)
    except ValueError as exc:
        return f"Error: {exc}"

    candidate = (root / rel).resolve() if rel not in (".", "") else root
    try:
        candidate.relative_to(root)
    except ValueError:
        return f"Error: path {rel!r} resolves outside the org's repo."
    if ".git" in candidate.relative_to(root).parts:
        return "Error: .git is not readable."

    if candidate.is_dir():
        try:
            names = sorted(os.listdir(candidate))
        except OSError as exc:
            return f"Error listing {rel!r}: {exc}"
        shown = [n + ("/" if (candidate / n).is_dir() else "")
                 for n in names if n != ".git"][:200]
        rel_disp = str(candidate.relative_to(root)) or "."
        return f"Directory {rel_disp!r} ({len(shown)} entries):\n" + "\n".join(
            f"  {n}" for n in shown)

    if not candidate.is_file():
        return f"Error: no such file in the org repo: {rel!r}."

    try:
        with candidate.open("rb") as fh:
            raw = fh.read(MAX_READ_BYTES + 1)
    except OSError as exc:
        return f"Error reading {rel!r}: {exc}"

    truncated = len(raw) > MAX_READ_BYTES
    text = raw[:MAX_READ_BYTES].decode("utf-8", errors="replace")
    header = f"File: {rel}\n"
    if truncated:
        header += f"[truncated at {MAX_READ_BYTES} bytes]\n"
    return header + "---\n" + text


READ_ORG_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Path relative to the org's context-repo root (e.g. "
                "'proposals/6-22-andy-contractor.md', 'campaigns', '.'). "
                "A directory path returns a listing; a file path returns "
                "its content."
            ),
        },
    },
    "required": ["path"],
}
