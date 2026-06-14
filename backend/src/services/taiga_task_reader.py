"""
Concrete TaskReader over the mcp-taiga CLI.

Shared by ``pm_claw`` and ``opportunity_claw`` — both depend on the ``TaskReader``
Protocol (defined in pm_claw) and the ``Task`` projection; this is the single
real adapter that binds that seam to Taiga. Building it once lights up both
claws.

It reads a Taiga project's user stories via ``mcp-taiga list <project> --json``
and maps each row to a ``Task``. Confirmed JSON shape (2026-06-14)::

    {"ref": 9, "subject": "...", "status": "New", "assigned_to": null, "tags": []}

  - ref          -> Task.id (string)
  - subject      -> Task.title
  - status       -> Task.status
  - assigned_to  -> Task.assignee  (null  => unassigned, the opportunity signal)
  - due_date     -> not present in the list view, left None

Boundaries (docs/BOUNDARIES.md): amebo owns no task list. This adapter only
READS, through the same CLI the tool layer already uses (``run_cli``), with no
shell and no injection surface.

The org -> Taiga-project mapping is INJECTED (``resolve``), never hardcoded: the
integration decides which project belongs to an org (per the repo's "never
invent a stand-in" rule). The CLI runner is injected too so tests exercise the
parse/mapping without touching the live CLI.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, List, Optional, Sequence

from src.services.pm_claw import Task
from src.tools.cli_read_tools import run_cli

logger = logging.getLogger(__name__)

# resolve(org_id) -> Taiga project slug, or None when no project is mapped.
ProjectResolver = Callable[[int], Optional[str]]
# runner(argv) -> stdout (or an error string). Matches tools.cli_read_tools.run_cli.
CliRunner = Callable[[List[str]], str]


class TaigaCliTaskReader:
    """Reads an org's Taiga stories and projects them onto ``Task``."""

    def __init__(self, resolve: ProjectResolver, runner: CliRunner = run_cli):
        self._resolve = resolve
        self._runner = runner

    def list_tasks(self, *, org_id: int) -> Sequence[Task]:
        project = self._resolve(org_id)
        if not project:
            logger.info("[taiga-reader] no Taiga project mapped for org=%s", org_id)
            return []
        raw = self._runner(["mcp-taiga", "list", project, "--json"])
        return self._parse(raw)

    @staticmethod
    def _parse(raw: str) -> List[Task]:
        raw = (raw or "").strip()
        # run_cli returns a human error string (not JSON) on failure / no output.
        # A valid list response always starts with '['; anything else is a
        # surfaced error, not data — degrade to empty rather than crash a tick.
        if not raw.startswith("["):
            logger.warning("[taiga-reader] non-JSON output from mcp-taiga: %s",
                           raw[:200])
            return []
        try:
            rows = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("[taiga-reader] could not parse mcp-taiga JSON: %s", e)
            return []

        out: List[Task] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            ref = r.get("ref")
            if ref is None:
                continue
            assigned_to = r.get("assigned_to")
            out.append(
                Task(
                    id=str(ref),
                    title=(r.get("subject") or "").strip(),
                    status=r.get("status"),
                    # null assignee is the opportunity signal; a numeric id means
                    # owned. Kept as a string presence marker (id->name mapping
                    # can come later via `mcp-taiga users` if a name is needed).
                    assignee=str(assigned_to) if assigned_to is not None else None,
                    due_date=None,  # not exposed by the list view
                )
            )
        return out
