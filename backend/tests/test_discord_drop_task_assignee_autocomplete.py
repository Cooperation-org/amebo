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
async def test_assignee_autocomplete_empty_project_defaults_to_vc():
    """Discord does not send the slash command's default for an optional
    `project` in autocomplete interactions. Mirror the slash default ('vc')
    so the dropdown keeps working when the user skips project."""
    bot = DiscordBot(instance_slug="test")
    members_json = json.dumps([{"id": 1, "username": "alice"}])
    with patch("src.tools.cli_read_tools.run_cli", return_value=members_json) as fake_cli:
        choices = await _run(bot, project="")
    assert [c.name for c in choices] == ["alice"]
    # Verify the CLI was called with the default project, not an empty arg.
    fake_cli.assert_called_once()
    argv = fake_cli.call_args[0][0]
    assert argv == ["mcp-taiga", "members", "vc", "--json"]


@pytest.mark.asyncio
async def test_status_autocomplete_empty_project_defaults_to_vc():
    """Same fix for status autocomplete — Discord omits the default value, so
    the handler must default it itself or it falls back to the hardcoded
    Taiga defaults even when the user really meant `vc`."""
    bot = DiscordBot(instance_slug="test")
    statuses = json.dumps([
        {"id": 1, "name": "New"},
        {"id": 2, "name": "In Progress"},
        {"id": 3, "name": "Ready for Test"},
        {"id": 4, "name": "Done"},
    ])
    with patch("src.tools.cli_read_tools.run_cli", return_value=statuses) as fake_cli:
        choices = await bot._status_autocomplete(_interaction(project=""), current="")
    # Real vc project statuses (whatever mcp-taiga returns), not the hardcoded
    # fallback list. Assert the CLI was called with the default project.
    fake_cli.assert_called_once()
    argv = fake_cli.call_args[0][0]
    assert argv == ["mcp-taiga", "statuses", "vc", "--json"]
    # The result is the four statuses we stubbed (whatever a real vc project has).
    assert {c.name for c in choices} == {"New", "In Progress", "Ready for Test", "Done"}


@pytest.mark.asyncio
async def test_assignee_autocomplete_unknown_project_returns_sentinel():
    """`mcp-taiga members <bad>` fails; we return a single sentinel Choice
    rather than `[]`. Discord renders an empty autocomplete list as "Loading
    options failed", so the dropdown must always have at least one entry.
    """
    bot = DiscordBot(instance_slug="test")
    with patch("src.tools.cli_read_tools.run_cli", return_value="Error: project not found"):
        choices = await _run(bot, project="does-not-exist")
    assert len(choices) == 1
    assert choices[0].value == ""
    assert "no members" in choices[0].name.lower()


@pytest.mark.asyncio
async def test_assignee_autocomplete_malformed_json_returns_sentinel():
    bot = DiscordBot(instance_slug="test")
    with patch("src.tools.cli_read_tools.run_cli", return_value="not json at all"):
        choices = await _run(bot, project="vc")
    assert len(choices) == 1
    assert choices[0].value == ""


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

# ---------------------------------------------------------------------------
# project autocomplete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_autocomplete_lists_slugs():
    """`mcp-taiga projects --json` rows become Choices whose value is the slug
    and whose label carries the human name."""
    bot = DiscordBot(instance_slug="test")
    projects = json.dumps([
        {"id": 1, "slug": "vc", "name": "vc"},
        {"id": 2, "slug": "amebo", "name": "Amebo"},
    ])
    with patch("src.tools.cli_read_tools.run_cli", return_value=projects) as fake_cli:
        choices = await bot._project_autocomplete(_interaction(), current="")
    assert [c.value for c in choices] == ["vc", "amebo"]
    assert [c.name for c in choices] == ["vc (vc)", "Amebo (amebo)"]
    assert fake_cli.call_args[0][0] == ["mcp-taiga", "projects", "--json"]


@pytest.mark.asyncio
async def test_project_autocomplete_narrows_on_typed_text():
    """Discord does not filter the Choices we return, so the handler must."""
    bot = DiscordBot(instance_slug="test")
    projects = json.dumps([
        {"id": 1, "slug": "vc", "name": "vc"},
        {"id": 2, "slug": "amebo", "name": "Amebo"},
        {"id": 3, "slug": "govkit", "name": "GovKit"},
    ])
    with patch("src.tools.cli_read_tools.run_cli", return_value=projects):
        choices = await bot._project_autocomplete(_interaction(), current="kit")
    assert [c.value for c in choices] == ["govkit"]


@pytest.mark.asyncio
async def test_project_autocomplete_caps_at_25():
    bot = DiscordBot(instance_slug="test")
    projects = [{"id": i, "slug": f"p{i}", "name": f"P{i}"} for i in range(40)]
    with patch("src.tools.cli_read_tools.run_cli", return_value=json.dumps(projects)):
        choices = await bot._project_autocomplete(_interaction(), current="")
    assert len(choices) == 25


@pytest.mark.asyncio
async def test_project_autocomplete_failure_returns_default_sentinel():
    """Never an empty list — Discord shows that as "Loading options failed"."""
    bot = DiscordBot(instance_slug="test")
    for out in ("Error: no such command", "not json at all", "[]"):
        with patch("src.tools.cli_read_tools.run_cli", return_value=out):
            choices = await bot._project_autocomplete(_interaction(), current="")
        assert len(choices) == 1, out
        assert choices[0].value == "vc"


@pytest.mark.asyncio
async def test_project_autocomplete_no_match_returns_sentinel():
    bot = DiscordBot(instance_slug="test")
    projects = json.dumps([{"id": 1, "slug": "vc", "name": "vc"}])
    with patch("src.tools.cli_read_tools.run_cli", return_value=projects):
        choices = await bot._project_autocomplete(_interaction(), current="zzz")
    assert len(choices) == 1
    assert choices[0].value == "vc"


@pytest.mark.asyncio
async def test_assignee_autocomplete_narrows_on_typed_text():
    """A project with more than 25 members needs the typed text applied
    BEFORE the cap, or the tail of the member list is unreachable."""
    bot = DiscordBot(instance_slug="test")
    members = [{"id": i, "username": f"user{i}"} for i in range(40)]
    with patch("src.tools.cli_read_tools.run_cli", return_value=json.dumps(members)):
        choices = await bot._assignee_autocomplete(
            _interaction(project="vc"), current="user39"
        )
    assert [c.value for c in choices] == ["user39"]
