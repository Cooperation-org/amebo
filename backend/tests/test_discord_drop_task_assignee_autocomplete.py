"""
`/drop-task` assignee autocomplete — verifies that `_assignee_autocomplete`
correctly parses `mcp-taiga members <project> --json` into Discord Choices
and degrades gracefully when the project is empty or unknown. Pure test:
no subprocess, no DB, no live Discord client.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.services.discord_bot import DiscordBot


def _interaction(project=None):
    """Build a minimal stub Interaction carrying the project option value.
    Only the autocomplete handler touches `interaction.data.options`, so we
    don't need a full discord.Interaction here."""
    opts = []
    if project is not None:
        opts.append(type("Opt", (), {"name": "project", "value": project})())
    return type("Ixn", (), {"data": type("Data", (), {"options": opts})()})()


async def _run(bot, project):
    return await bot._assignee_autocomplete(_interaction(project=project), current="")


@pytest.mark.asyncio
async def test_assignee_autocomplete_returns_project_usernames():
    """Happy path: a known project's members surface as Choices."""
    bot = DiscordBot(instance_slug="test")
    members_json = json.dumps([
        {"id": 1, "username": "alice", "full_name": "Alice"},
        {"id": 2, "username": "bob", "full_name": "Bob"},
    ])
    with patch("src.tools.cli_read_tools.run_cli", return_value=members_json):
        choices = await _run(bot, project="vc")
    assert [c.name for c in choices] == ["alice", "bob"]
    assert [c.value for c in choices] == ["alice", "bob"]


@pytest.mark.asyncio
async def test_assignee_autocomplete_empty_project_returns_empty_list():
    """No project → no sensible global assignee list; nudge the user to pick one."""
    bot = DiscordBot(instance_slug="test")
    choices = await _run(bot, project="")
    assert choices == []
    # CLI should not have been invoked at all.
    with patch("src.tools.cli_read_tools.run_cli") as fake_cli:
        await _run(bot, project="")
        fake_cli.assert_not_called()


@pytest.mark.asyncio
async def test_assignee_autocomplete_unknown_project_returns_empty_list():
    """`mcp-taiga members <bad>` fails; we return an empty dropdown rather
    than surface an error to the user."""
    bot = DiscordBot(instance_slug="test")
    with patch("src.tools.cli_read_tools.run_cli", return_value="Error: project not found"):
        choices = await _run(bot, project="does-not-exist")
    assert choices == []


@pytest.mark.asyncio
async def test_assignee_autocomplete_malformed_json_returns_empty_list():
    bot = DiscordBot(instance_slug="test")
    with patch("src.tools.cli_read_tools.run_cli", return_value="not json at all"):
        choices = await _run(bot, project="vc")
    assert choices == []


@pytest.mark.asyncio
async def test_assignee_autocomplete_skips_rows_without_username():
    """mcp-taiga memberships occasionally have `username: null`. Drop those."""
    bot = DiscordBot(instance_slug="test")
    members_json = json.dumps([
        {"id": 1, "username": "alice"},
        {"id": 2, "username": None},
        {"id": 3},  # no username key at all
        {"id": 4, "username": "bob"},
    ])
    with patch("src.tools.cli_read_tools.run_cli", return_value=members_json):
        choices = await _run(bot, project="vc")
    assert [c.name for c in choices] == ["alice", "bob"]


@pytest.mark.asyncio
async def test_assignee_autocomplete_caps_at_25():
    """Discord's autocomplete hard cap is 25; we truncate, not error."""
    bot = DiscordBot(instance_slug="test")
    members = [{"id": i, "username": f"user{i}"} for i in range(40)]
    with patch("src.tools.cli_read_tools.run_cli", return_value=json.dumps(members)):
        choices = await _run(bot, project="vc")
    assert len(choices) == 25
    assert choices[0].name == "user0"
    assert choices[24].name == "user24"


@pytest.mark.asyncio
async def test_status_autocomplete_still_works():
    """Sanity: adding assignee autocomplete didn't break status autocomplete."""
    bot = DiscordBot(instance_slug="test")
    statuses = json.dumps([{"id": 1, "name": "New"}, {"id": 2, "name": "Done"}])
    with patch("src.tools.cli_read_tools.run_cli", return_value=statuses):
        choices = await bot._status_autocomplete(_interaction(project="vc"), current="")
    assert [c.name for c in choices] == ["New", "Done"]