"""
Real, read-only resolvers for reference_integrity.

These adapters back the ``ReferenceResolver`` protocol with amebo's existing
read-only access to external systems. They wrap the *read* surface only and
never write, update, delete, or notify.

Wiring status (read this before trusting the prod path):

  CRM (Odoo) — amebo reaches the CRM through the ``odoo-cli`` subprocess
    wrapper (``src.tools.registry._exec_cli_tool("odoo-cli", ...)``). That
    wrapper is generic and the exact *read* subcommand + output shape for
    "does contact <id> exist" is not pinned down in this repo. So the CRM
    resolver here is wired to call ``odoo-cli`` read-only and parse its
    output defensively, but the precise subcommand/flags are marked TODO and
    default to UNRESOLVABLE (None) rather than guessing existence. Confirm
    the read subcommand against odoo-cli before relying on DANGLING/OK from
    the CRM. See linkedtrust-crm-setup.md for odoo-cli.

  Taiga — same shape via the ``mcp-taiga`` subprocess wrapper. The read
    subcommand to fetch a task by ref is likewise TODO; defaults to None
    (UNRESOLVABLE) until confirmed.

Until the read subcommands are confirmed, the prod path classifies these
references UNRESOLVABLE — which is the safe direction (we never flag a
reference as dangling on a guess). Tests do NOT use these adapters; they
inject fakes.
"""

from __future__ import annotations

import logging
import shlex
from typing import Callable, Optional

from src.services.reference_integrity import ResolveOutcome

logger = logging.getLogger(__name__)


# Type of the low-level CLI runner. Matches the signature of
# src.tools.registry._exec_cli_tool(command, args, timeout) -> str.
CliRunner = Callable[..., str]


def _default_cli_runner() -> CliRunner:
    """
    Return the repo's existing read-only CLI runner. Imported lazily so this
    module stays importable (and unit-testable with fakes) in environments
    where the tools package or its deps are not installed.
    """
    from src.tools.registry import _exec_cli_tool
    return _exec_cli_tool


def _looks_missing(output: str) -> Optional[bool]:
    """
    Best-effort interpretation of a CLI's textual output for an existence
    probe. Returns False when the output clearly says "not found", True when
    it clearly returned a record, and None when we cannot tell.

    This is intentionally conservative: anything ambiguous returns None
    (UNRESOLVABLE) so a parsing miss never produces a false DANGLING.
    """
    if not output:
        return None
    low = output.lower()
    # The CLI itself being absent is an environment failure, not a missing
    # target — check this before the generic "not found" below (its message
    # also contains "not found").
    if "tool '" in low and "not found in path" in low:
        return None
    if "not found" in low or "no such" in low or "does not exist" in low:
        return False
    if low.startswith("error") or "[stderr:" in low or "timed out" in low:
        return None
    # We got some non-error output — but without a confirmed read subcommand
    # and output schema we will not assert existence. See module TODO.
    return None


class OdooContactResolver:
    """
    Read-only existence check for a CRM (Odoo) contact, via ``odoo-cli``.

    NEVER writes. Calls only a read subcommand. The exact read subcommand is
    a TODO (see module docstring); until confirmed this returns None
    (UNRESOLVABLE) for non-error output rather than guessing.
    """

    def __init__(self, cli_runner: Optional[CliRunner] = None):
        self._run = cli_runner or _default_cli_runner()

    def exists(self, ref: str) -> ResolveOutcome:
        # TODO(reference-integrity): confirm the odoo-cli read subcommand for
        # fetching a contact by id and its output shape, then parse a
        # definitive True/False here. Read-only only — never a write command.
        args = f"show contact {shlex.quote(str(ref))}"
        try:
            out = self._run("odoo-cli", args)
        except Exception as exc:
            logger.warning("OdooContactResolver: odoo-cli failed for %r: %s", ref, exc)
            return None
        return _looks_missing(out)


class TaigaTaskResolver:
    """
    Read-only existence check for a Taiga task, via ``mcp-taiga``.

    NEVER writes. Calls only a read subcommand. The exact read subcommand is
    a TODO (see module docstring); until confirmed this returns None
    (UNRESOLVABLE) for non-error output rather than guessing.
    """

    def __init__(self, cli_runner: Optional[CliRunner] = None):
        self._run = cli_runner or _default_cli_runner()

    def exists(self, ref: str) -> ResolveOutcome:
        # TODO(reference-integrity): confirm the mcp-taiga read subcommand for
        # fetching a task/story by ref and its output shape, then parse a
        # definitive True/False here. Read-only only — never a write command.
        args = f"show task {shlex.quote(str(ref))}"
        try:
            out = self._run("mcp-taiga", args)
        except Exception as exc:
            logger.warning("TaigaTaskResolver: mcp-taiga failed for %r: %s", ref, exc)
            return None
        return _looks_missing(out)


def default_resolvers(cli_runner: Optional[CliRunner] = None) -> dict:
    """
    The production resolver map, keyed by binding ``target_type``.

    All entries are read-only. ``cli_runner`` can be injected for testing,
    but unit tests generally inject fakes at the service layer instead.
    """
    return {
        "crm_contact": OdooContactResolver(cli_runner),
        "taiga_task": TaigaTaskResolver(cli_runner),
    }
