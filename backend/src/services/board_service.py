"""
Read-only 'board' assembly for the dashboard.

GENERIC and vocabulary-agnostic (I3): this reads a per-instance board config
``{"kind": ..., "dir": ...}``, walks the org's context repo ``<dir>/*/MAIN.md``,
parses each doc's header fields + its "Docs & links" table deterministically, and
returns items. It knows NOTHING about "campaigns" — that noun lives in the config
data and the frontend template, never in this logic. Another org could bind the
same machinery to ``cases`` or ``clients``.

Read-only: no LLM, no DB writes, no new tables. Every returned link points OUT to
the tool that owns the thing. The only URL built here is the MAIN.md link on the
git host, derived from the repo's own remote (never hardcoded). Vendor-specific
link-outs (CRM, Taiga) are left to the frontend template — the parsed field
values are passed through for it to render.

Tolerant by design: a malformed file yields whatever fields parsed; it never
fails the whole board.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.credentials.connections import _org_context_repo

logger = logging.getLogger(__name__)

BOARD_TTL_S = 60  # same freshness discipline as the manifest cache
_MAIN_MD = "MAIN.md"
_MAX_MD_BYTES = 64 * 1024

# When the working tree is clean we best-effort ff-only pull at most once per
# TTL so edits pushed from elsewhere show up; a dirty tree or any git failure
# just reads local (never clobber concurrent human edits, never block the board).
_pull_attempted: Dict[str, float] = {}  # repo_root -> last monotonic attempt


# ---------------------------------------------------------------------------
# freshness (TTL-gated, clean-tree, ff-only, fail-soft)
# ---------------------------------------------------------------------------

def _git_argv(repo_root: str, *args: str) -> List[str]:
    # -c safe.directory trusts THIS repo only (the service user differs from the
    # shared repo's owner); no global git config is mutated.
    return ["git", "-C", repo_root, "-c", f"safe.directory={repo_root}", *args]


def _maybe_pull(repo_root: str) -> None:
    now = time.monotonic()
    last = _pull_attempted.get(repo_root)
    if last is not None and (now - last) < BOARD_TTL_S:
        return
    _pull_attempted[repo_root] = now
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
    }
    try:
        status = subprocess.run(
            _git_argv(repo_root, "status", "--porcelain"),
            capture_output=True, text=True, timeout=8, env=env,
        )
        if status.returncode != 0 or status.stdout.strip():
            return  # not a clean checkout — read local as-is
        subprocess.run(
            _git_argv(repo_root, "pull", "--ff-only"),
            capture_output=True, text=True, timeout=12, env=env,
        )
    except Exception as exc:  # timeout, network, not-a-repo — all fail-soft
        logger.info("board: git refresh skipped for %s (%s)", repo_root, exc)


# ---------------------------------------------------------------------------
# git host URL for the MAIN.md link (derived from the remote, never hardcoded)
# ---------------------------------------------------------------------------

def _git(repo_root: str, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            _git_argv(repo_root, *args),
            capture_output=True, text=True, timeout=8,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def _remote_web_base(repo_root: str) -> Optional[str]:
    """https web base for the origin remote, e.g. github.com/Org/repo.
    Supports git@host:org/repo(.git) and https://host/org/repo(.git)."""
    url = _git(repo_root, "remote", "get-url", "origin")
    if not url:
        return None
    url = url.strip()
    m = re.match(r"^git@([^:]+):(.+?)(?:\.git)?$", url)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    m = re.match(r"^https?://(?:[^@]+@)?([^/]+)/(.+?)(?:\.git)?$", url)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    return None


def _main_md_url(repo_root: str, rel_path: str) -> Optional[str]:
    base = _remote_web_base(repo_root)
    if not base:
        return None
    branch = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD") or "main"
    if branch == "HEAD":
        branch = "main"
    return f"{base}/blob/{branch}/{rel_path}"


# ---------------------------------------------------------------------------
# deterministic MAIN.md header/table parsing
# ---------------------------------------------------------------------------

# One bold "**Label:** value" field. Values are ` · `-separated on a line.
_FIELD_RE = re.compile(r"\*\*\s*([^*:]+?)\s*:\s*\*\*\s*(.*?)\s*$")
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")


def _norm_key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")


def _parse_header(text: str) -> Dict[str, str]:
    """Fields from the top of the doc (before the first '## ' section). Returns a
    generic {normalized_label: value} map — the parser does not interpret meaning."""
    fields: Dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("## "):
            break
        # a header line may hold several ` · `-separated fields
        for seg in line.split(" · "):
            m = _FIELD_RE.match(seg.strip())
            if m:
                key = _norm_key(m.group(1))
                val = m.group(2).strip()
                if key and key not in fields:
                    fields[key] = val
    return fields


def _parse_docs_links(text: str) -> List[Dict[str, str]]:
    """Rows of the 'Docs & links' table that actually have a link. Deterministic;
    returns [] if the section or table is absent."""
    rows: List[Dict[str, str]] = []
    lines = text.splitlines()
    in_section = False
    for line in lines:
        if line.startswith("## "):
            in_section = "docs & links" in line.lower() or "docs and links" in line.lower()
            continue
        if not in_section:
            continue
        m = _TABLE_ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 2:
            continue
        label, link = cells[0], cells[1]
        # skip header row and the |---|---| separator
        if not label or label.lower() == "item" or set(label) <= {"-", ":", " "}:
            continue
        url = _extract_url(link)
        if url:
            rows.append({"label": label, "url": url})
    return rows


_MD_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
_BARE_URL_RE = re.compile(r"(https?://[^\s)|]+)")


def _extract_url(cell: str) -> Optional[str]:
    m = _MD_LINK_RE.search(cell)
    if m:
        return m.group(1)
    m = _BARE_URL_RE.search(cell)
    if m:
        return m.group(1)
    return None


def _first_heading(text: str) -> Optional[str]:
    for line in text.splitlines():
        m = re.match(r"^#\s+(.+?)\s*$", line)
        if m:
            title = m.group(1).strip()
            # skip a template placeholder like "[Campaign Name]"
            if title.startswith("[") and title.endswith("]"):
                return None
            return title
    return None


def _clean_value(val: str) -> str:
    """Treat template dashes/placeholders as empty."""
    v = (val or "").strip()
    if v in {"", "—", "-", "–", "TBD", "tbd"}:
        return ""
    if v.startswith("[") and v.endswith("]"):  # unfilled template placeholder
        return ""
    return v


def _parse_main_md(path: Path, slug: str, dir_name: str, repo_root: str) -> Dict[str, Any]:
    raw = path.read_bytes()[:_MAX_MD_BYTES]
    text = raw.decode("utf-8", errors="replace")
    fields = _parse_header(text)
    rel = f"{dir_name}/{slug}/{_MAIN_MD}"
    return {
        "slug": slug,
        "name": _first_heading(text) or slug,
        "one_liner": _clean_value(fields.get("one_liner", "")),
        "status": _clean_value(fields.get("status", "")),
        "owner": _clean_value(fields.get("owner", "")),
        # vendor-specific link-outs are rendered by the frontend template from
        # these raw values (kept out of this generic core):
        "crm_ref": _clean_value(fields.get("crm_campaign", "")),
        "taiga": _clean_value(fields.get("taiga", "")),
        "main_md_url": _main_md_url(repo_root, rel),
        "docs_links": _parse_docs_links(text),
    }


# ---------------------------------------------------------------------------
# the entrypoint
# ---------------------------------------------------------------------------

def read_board(org_id: int, board_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the board for an org from its context repo. Returns
    {"kind": <passthrough>, "items": [...]}. Empty items when unconfigured or
    the repo/dir is missing — the frontend then hides the section."""
    if not org_id or not isinstance(board_cfg, dict):
        return {"items": []}
    dir_name = board_cfg.get("dir")
    if not dir_name:
        return {"items": []}

    repo_root = _org_context_repo(org_id)
    if not repo_root:
        return {"items": []}

    board_root = (Path(repo_root) / dir_name).resolve()
    # guard: the board dir must sit inside the context repo
    try:
        board_root.relative_to(Path(repo_root).resolve())
    except ValueError:
        logger.warning("board dir %r escapes context repo %r", dir_name, repo_root)
        return {"items": []}
    if not board_root.is_dir():
        return {"items": [], "kind": board_cfg.get("kind")}

    _maybe_pull(repo_root)

    items: List[Dict[str, Any]] = []
    for entry in sorted(board_root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir() or entry.name == "archived":
            continue
        main_md = entry / _MAIN_MD
        if not main_md.is_file():
            continue
        try:
            items.append(_parse_main_md(main_md, entry.name, dir_name, repo_root))
        except Exception:
            logger.exception("board: failed to parse %s (skipping this one)", main_md)
            continue

    return {"kind": board_cfg.get("kind"), "items": items}
