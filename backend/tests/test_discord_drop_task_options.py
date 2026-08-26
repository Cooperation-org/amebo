"""
/drop-task option forwarding — verifies that `_create_drop_task` passes
`--due` and `--status` to mcp-taiga correctly. Pure argv inspection:
no subprocess, no DB, no Discord client. Mocking run_cli and
PendingEquityTaskRepo keeps the test surface small.

The Discord-side wiring (slash command declaration, `_slash_drop_task`
deadline validation, `_status_autocomplete`) is exercised by reading
the module and via the existing guard tests; a Discord client unit
test would need a full gateway. The argv contract is what the Taiga
side actually consumes, so we lock that down here.
"""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from src.services.discord_bot import _create_drop_task
from src.tools.gated_actuators import _valid_due_date


def _argv_for_create(monkeypatch, **kwargs):
    """Run `_create_drop_task` and return the argv it would have sent
    to mcp-taiga. Patches run_cli to capture argv and stub PendingEquityTaskRepo.
    """
    captured = {}

    def fake_run_cli(argv, timeout=10, env=None):
        captured["argv"] = argv
        return "Created #42: stub"

    monkeypatch.setattr("src.tools.cli_read_tools.run_cli", fake_run_cli)
    monkeypatch.setattr(
        "src.db.repositories.pending_equity_task_repo.PendingEquityTaskRepo.create",
        lambda self, **kw: 1,
    )

    _create_drop_task(
        project="vc",
        subject="hello",
        equity=0,
        cash=0,
        assignee=None,
        description=None,
        discord_user_id="111",
        discord_username="alice",
        org_id=1,
        govkit_org_slug="vc",
        **kwargs,
    )
    return captured["argv"]


def test_default_status_is_in_progress(monkeypatch):
    argv = _argv_for_create(monkeypatch, status=None)
    # The hardcoded default that preserves today's behavior.
    assert "--status" in argv
    idx = argv.index("--status")
    assert argv[idx + 1] == "In Progress"
    assert "--due" not in argv


def test_explicit_status_forwarded(monkeypatch):
    argv = _argv_for_create(monkeypatch, status="Ready for Test")
    idx = argv.index("--status")
    assert argv[idx + 1] == "Ready for Test"


def test_deadline_forwarded_as_due(monkeypatch):
    future = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
    argv = _argv_for_create(monkeypatch, deadline=future)
    assert "--due" in argv
    idx = argv.index("--due")
    assert argv[idx + 1] == future


def test_no_deadline_omits_due_flag(monkeypatch):
    argv = _argv_for_create(monkeypatch, deadline=None)
    assert "--due" not in argv


def test_past_deadline_rejected_by_guard():
    """`_valid_due_date` rejects past dates; this is the same gate that
    `_slash_drop_task` uses to refuse the slash command before subprocess."""
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert _valid_due_date(yesterday) is False


def test_malformed_deadline_rejected_by_guard():
    assert _valid_due_date("not-a-date") is False
    assert _valid_due_date("2026/09/15") is False
    assert _valid_due_date("") is False


def test_today_is_valid_deadline():
    """Today is the earliest legal deadline — never 'in the past'."""
    today = date.today().strftime("%Y-%m-%d")
    assert _valid_due_date(today) is True


def test_argv_argv_order_is_status_then_optional():
    """The mcp-taiga create subcommand requires `project SUBJECT` before any
    flags. Lock that order in so a refactor can't silently break it."""
    future = (date.today() + timedelta(days=2)).strftime("%Y-%m-%d")
    argv = _argv_for_create(
        monkeypatch=__import__("pytest").MonkeyPatch(),
        deadline=future,
        status="In Progress",
    )
    # mcp-taiga create <project> <subject> [--status S] [--due D] ...
    assert argv[:5] == ["mcp-taiga", "create", "vc", "hello", "--status"]
    assert argv[5] == "In Progress"
    # --due appears somewhere after --status.
    assert "--due" in argv and argv[argv.index("--due") + 1] == future