"""
Concrete TaskReader over the mcp-taiga CLI.

Shared by ``pm_claw`` and ``opportunity_claw`` — both depend on the ``TaskReader``
Protocol (defined in pm_claw) and the ``Task`` projection; this is the single
real adapter that binds that seam to Taiga. Building it once lights up both
claws.

Taiga has no "organization" object: a Taiga **user is a member of projects**, so
an org IS the set of projects a given Taiga login belongs to. This adapter
therefore reads *as the org's Taiga login*: it runs ``mcp-taiga projects`` to get
the projects that login can see, then ``mcp-taiga list <slug> --json`` for each,
and aggregates. ``TAIGA_TOKEN`` selects the login per call (the CLI honours it
over the stored ~/.mcp-taiga.conf), so one process can serve many orgs without a
shared god-token (BOUNDARIES.md: "the org's team-scoped service credential").

Confirmed list JSON shape (2026-06-14)::

    {"ref": 9, "subject": "...", "status": "New", "assigned_to": null, "tags": []}

  - ref          -> Task.id (string)
  - subject      -> Task.title
  - status       -> Task.status
  - assigned_to  -> Task.assignee  (null  => unassigned, the opportunity signal)
  - due_date     -> not present in the list view, left None

The org -> Taiga-login TOKEN mapping is INJECTED (``resolve``), never hardcoded:
the integration decides which login serves an org (per the repo's "never invent
a stand-in" rule). NOTE: amebo's org_credentials has no ``taiga`` kind yet, so
that store must gain one before ``resolve`` can read a real per-org token. The
CLI runner is injected too so tests exercise the parse/mapping without the live
CLI.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Callable, List, Optional, Sequence

from src.services.pm_claw import Task

logger = logging.getLogger(__name__)

# resolve(org_id) -> the org's Taiga login token, or None when none is mapped.
TokenResolver = Callable[[int], Optional[str]]
# runner(argv, token) -> stdout (or a human error string). token may be None.
CliRunner = Callable[[List[str], Optional[str]], str]

_CLI_TIMEOUT_S = 30


def run_taiga_cli(argv: List[str], token: Optional[str]) -> str:
    """
    Run an mcp-taiga subcommand AS a specific login by injecting TAIGA_TOKEN.

    No shell, no injection surface (argv is pre-split). On failure returns a
    human-readable error string (never raises) so a claw tick degrades to "no
    tasks" rather than crashing.
    """
    if not argv or not argv[0]:
        return "Error: no command to run."
    env = dict(os.environ)
    if token:
        env["TAIGA_TOKEN"] = token
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True,
            timeout=_CLI_TIMEOUT_S, shell=False, env=env,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {_CLI_TIMEOUT_S}s: {argv[0]}"
    except FileNotFoundError:
        return f"Error: tool {argv[0]!r} not found in PATH."
    out = (result.stdout or "").strip()
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[:300]
        return out or f"Error: {argv[0]} exited {result.returncode}: {stderr or '(no stderr)'}"
    return out


class TaigaCliTaskReader:
    """Reads an org's Taiga stories (across the login's projects) as ``Task``s."""

    def __init__(self, resolve: TokenResolver, runner: CliRunner = run_taiga_cli):
        self._resolve = resolve
        self._runner = runner

    def list_tasks(self, *, org_id: int) -> Sequence[Task]:
        token = self._resolve(org_id)
        if not token:
            logger.info("[taiga-reader] no Taiga login token mapped for org=%s", org_id)
            return []

        slugs = self._project_slugs(token)
        if not slugs:
            logger.info("[taiga-reader] login for org=%s sees no projects", org_id)
            return []

        tasks: List[Task] = []
        for slug in slugs:
            tasks.extend(self._parse_stories(self._runner(
                ["mcp-taiga", "list", slug, "--json"], token)))
        return tasks

    # -- helpers -------------------------------------------------------------

    def _project_slugs(self, token: Optional[str]) -> List[str]:
        raw = self._runner(["mcp-taiga", "projects", "--json"], token)
        rows = self._load_array(raw, "projects")
        return [s for s in (str(r.get("slug", "")).strip()
                            for r in rows if isinstance(r, dict)) if s]

    @classmethod
    def _parse_stories(cls, raw: str) -> List[Task]:
        out: List[Task] = []
        for r in cls._load_array(raw, "list"):
            if not isinstance(r, dict):
                continue
            ref = r.get("ref")
            if ref is None:
                continue
            assigned_to = r.get("assigned_to")
            out.append(Task(
                id=str(ref),
                title=(r.get("subject") or "").strip(),
                status=r.get("status"),
                # null assignee is the opportunity signal; a numeric id means
                # owned. Kept as a string presence marker (id->name mapping can
                # come later via `mcp-taiga users` if a display name is needed).
                assignee=str(assigned_to) if assigned_to is not None else None,
                due_date=None,  # not exposed by the list view
            ))
        return out

    @staticmethod
    def _load_array(raw: str, what: str) -> list:
        """Parse a JSON array from CLI output; [] on any error (run_taiga_cli
        returns a human error string, not JSON, on failure)."""
        raw = (raw or "").strip()
        if not raw.startswith("["):
            logger.warning("[taiga-reader] non-JSON %s output: %s", what, raw[:200])
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("[taiga-reader] could not parse %s JSON: %s", what, e)
            return []
        return data if isinstance(data, list) else []
