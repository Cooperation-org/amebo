"""Reading skill files.

Skills are markdown with frontmatter, in two places: the core catalog packaged
with amebo (``backend/prompts/skills``) and an org's own overlay in its context
repo (``<context repo>/skills``). Three callers read them — the system-prompt
catalog, the ``list_skills`` / ``load_skill`` tools, and the dashboard API — so
the file shape is known in one place here.

Frontmatter is parsed as YAML when YAML can read it, and as plain
``key: value`` lines when it cannot. Skills are text people edit, and an
unquoted colon in a description is the mistake they actually make; it used to
drop the whole skill out of the catalog with nothing on screen to say so.
Values are strings; ``order`` is coerced to int, and list values (``triggers``)
survive the YAML path only.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def core_skills_dir() -> Path:
    """The core catalog packaged with amebo."""
    return Path(__file__).resolve().parent.parent.parent / "prompts" / "skills"


def org_skills_dir(org_id: Optional[int]) -> Optional[Path]:
    """An org's own skills overlay: `<its context repo>/skills` (arch §7, durable
    text in repos). None when there is no org or the org has no context repo."""
    if org_id is None:
        return None
    try:
        from src.credentials.connections import _org_context_repo
        repo = _org_context_repo(org_id)
    except Exception:
        logger.exception("org skills dir resolve failed")
        return None
    return Path(repo) / "skills" if repo else None


def _fallback_meta(block: str) -> Dict[str, Any]:
    """Line-wise ``key: value`` read, for frontmatter YAML rejects."""
    meta: Dict[str, Any] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("- "):
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or not key or " " in key:
            continue
        meta[key] = value.strip().strip("'\"")
    return meta


def split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """(metadata, body). Both empty-safe: a file with no frontmatter is all body."""
    if not text.startswith("---"):
        return {}, text.strip()
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text.strip()
    block, body = parts[1], parts[2].strip()

    import yaml

    try:
        meta = yaml.safe_load(block) or {}
        if not isinstance(meta, dict):
            meta = {}
    except yaml.YAMLError:
        meta = _fallback_meta(block)

    if "order" in meta:
        try:
            meta["order"] = int(meta["order"])
        except (TypeError, ValueError):
            meta.pop("order")
    return meta, body


def read_skill(path: Path) -> Optional[Dict[str, Any]]:
    """One skill file as a dict, or None if it cannot be read."""
    try:
        meta, body = split_frontmatter(path.read_text())
    except OSError:
        logger.warning("skill unreadable: %s", path)
        return None
    return {
        "slug": path.stem,          # the filename, which is what load_skill resolves
        "name": meta.get("name") or path.stem,
        "description": meta.get("description", ""),
        "triggers": meta.get("triggers", []) or [],
        "audience": meta.get("audience", ""),
        "button": meta.get("button", ""),
        "ask": meta.get("ask", ""),
        "order": meta.get("order", 999),
        "status": meta.get("status", ""),
        "body": body,
        "path": str(path),
    }


def read_skills(dirs: List[Optional[Path]]) -> List[Dict[str, Any]]:
    """Skills from the given dirs, earlier dirs shadowing later ones by filename.
    Files starting with ``_`` are templates, not skills."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for d in dirs:
        if not d or not d.exists():
            continue
        for path in sorted(d.glob("*.md")):
            if path.stem.startswith("_") or path.stem in seen:
                continue
            skill = read_skill(path)
            if skill is None:
                continue
            seen.add(path.stem)
            skill["source"] = "org" if d != core_skills_dir() else "core"
            out.append(skill)
    return out
