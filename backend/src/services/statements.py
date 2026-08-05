"""
Reading an org's statements — mission, vision, values, OKRs — as text.

The statement itself is a name and a pointer (db/repositories/statement_repo.py).
This module is the other half: turning a pointer into the words it points at,
and composing the switched-on ones into the context a goal is pursued under.

Golda 2026-08-05: "this tool is not the center of the universe. People will draw
on whiteboards and take pictures of it and input it ... things live other places
and so you need to be able to easily just sort of import that blob of stuff."

So a pointer is a URI and the schemes are a table, not a chain of ifs. Adding
"a Google Doc" or "an image someone photographed" later is a new entry in
RESOLVERS and nothing else moves.

Nothing here writes, summarises or rephrases. The words that come out are the
words that went in.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# A statement's text is capped where it is read, not where it is stored: a
# 200-page strategy deck pointed at by mistake should cost one truncated blob,
# not a blown context window.
MAX_CHARS = 8000


def _from_url(pointer: str, org_id: int) -> Optional[str]:
    """A public http(s) document. Goes through the existing fetch tool, so the
    SSRF rules (no internal IPs, bounded redirects, text only) are the ones
    already reviewed rather than a second set written here."""
    from src.tools.http_fetch import http_fetch

    text = http_fetch({"url": pointer, "max_kb": 64}, {})
    if not text or text.startswith("Error:"):
        logger.warning("statement pointer %s unreadable: %s", pointer, text)
        return None
    return text


def _from_repo(pointer: str, org_id: int) -> Optional[str]:
    """A file in this org's own context repo — `repo:docs/mission.md`.

    Confined to the repo root by resolving both sides and checking containment,
    so a pointer cannot be used to read the VM's filesystem.
    """
    from src.db.repositories.org_repo import OrgRepo

    org = OrgRepo().get(org_id) or {}
    root = (org.get("context_repo") or "").strip()
    if not root or "://" in root:
        # No repo provisioned, or it is a clone URL rather than a local path.
        return None

    rel = pointer.split(":", 1)[1].lstrip("/")
    root_abs = os.path.realpath(os.path.expanduser(root))
    target = os.path.realpath(os.path.join(root_abs, rel))
    if not (target == root_abs or target.startswith(root_abs + os.sep)):
        logger.warning("statement pointer %s escapes the context repo", pointer)
        return None
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        logger.warning("statement pointer %s unreadable: %s", pointer, exc)
        return None


def _from_abra(pointer: str, org_id: int) -> Optional[str]:
    """A name in abra — `abra:linkedtrust-mission`. Knowledge about the org
    already lives there; this points at it rather than copying it across."""
    from src.db.repositories.binding_repo import BindingRepo

    name = pointer.split(":", 1)[1].strip()
    if not name:
        return None
    try:
        hits = BindingRepo(org_id=org_id).search_content(name, limit=1) or []
    except Exception as exc:
        logger.warning("abra unreachable for statement %s: %s", pointer, exc)
        return None
    for hit in hits:
        content = (hit.get("content") or "").strip()
        if content:
            return content
    return None


# Scheme -> reader. The extension point: a new place words can live is one
# entry here. Keys are matched as `<scheme>:` prefixes on the pointer.
RESOLVERS: Dict[str, Callable[[str, int], Optional[str]]] = {
    "http": _from_url,
    "https": _from_url,
    "repo": _from_repo,
    "abra": _from_abra,
}


def resolve(statement: Dict[str, Any], org_id: int) -> Optional[str]:
    """The words a statement stands for, or None when they cannot be read.

    A body is already the words. A pointer is fetched. An unknown scheme is not
    an error — it returns None and the statement simply contributes nothing,
    because a pointer nobody can follow yet is still worth writing down.
    """
    body = (statement.get("body") or "").strip()
    if body:
        return body[:MAX_CHARS]

    pointer = (statement.get("pointer") or "").strip()
    if not pointer:
        return None
    scheme = pointer.split(":", 1)[0].lower() if ":" in pointer else ""
    reader = RESOLVERS.get(scheme)
    if reader is None:
        logger.info("statement pointer %s has no reader yet", pointer)
        return None
    text = reader(pointer, org_id)
    return text[:MAX_CHARS].strip() if text else None


def live_context(org_id: int, holder: str = "org") -> List[Tuple[str, str, int]]:
    """The switched-on statements as (name, words, id), in the order shown.

    An empty list is the normal state for an org that has not said anything
    yet, and every caller has to work unchanged when it is empty — nothing here
    is load-bearing.
    """
    from src.db.repositories.statement_repo import StatementRepo

    try:
        rows = StatementRepo().live_for_org(org_id, holder=holder)
    except Exception as exc:
        # The store being down must not stop a goal running; it runs less
        # aligned, which is the same failure mode the old vector search had.
        logger.warning("statements unreadable for org %s: %s", org_id, exc)
        return []

    out: List[Tuple[str, str, int]] = []
    for row in rows:
        text = resolve(row, org_id)
        if text:
            out.append((row["name"], text, row["id"]))
    return out


def as_prompt_sections(context: List[Tuple[str, str, int]]) -> str:
    """The statements as prompt text, headed by the team's own relation names.

    The heading is the name they wrote, so a team that keeps "operating
    principles" sees "## operating principles" and not a heading amebo invented
    for it.
    """
    return "\n\n".join(f"## {name}\n{text}" for name, text, _ in context)
