"""
Tests for the shared TaskReader adapter over the mcp-taiga CLI.

Taiga has no org object — an org IS the set of projects its login can see — so
the adapter resolves org -> Taiga login token, enumerates that login's projects,
and aggregates stories across them. The CLI runner is injected (runner(argv,
token)) so the parse/mapping/aggregation is exercised without the live CLI.
"""

from src.services.taiga_task_reader import TaigaCliTaskReader


PROJECTS_JSON = """[
  {"id": 77, "slug": "amebo", "name": "Amebo"},
  {"id": 79, "slug": "alonovo", "name": "Alonovo"}
]"""

AMEBO_STORIES = """[
  {"ref": 3, "subject": "Auto-Backfill", "status": "In progress", "assigned_to": 352, "tags": []},
  {"ref": 9, "subject": "Channel Filtering", "status": "New", "assigned_to": null, "tags": []}
]"""

ALONOVO_STORIES = """[
  {"ref": 1, "subject": "Barcode scan", "status": "New", "assigned_to": null, "tags": []}
]"""


def make_runner(projects=PROJECTS_JSON, by_slug=None, record=None):
    """A fake CLI runner that dispatches on argv and records the token used."""
    by_slug = by_slug or {"amebo": AMEBO_STORIES, "alonovo": ALONOVO_STORIES}

    def runner(argv, token):
        if record is not None:
            record.append((argv, token))
        if argv[1] == "projects":
            return projects
        if argv[1] == "list":
            return by_slug.get(argv[2], "[]")
        return "[]"

    return runner


def test_resolves_token_enumerates_projects_aggregates_stories():
    record = []
    reader = TaigaCliTaskReader(
        resolve=lambda org_id: "TOK-org1", runner=make_runner(record=record))
    tasks = list(reader.list_tasks(org_id=1))

    # aggregated across both of the login's projects
    assert {t.id for t in tasks} == {"3", "9", "1"}
    # every CLI call carried the org's login token (no god-token)
    assert all(token == "TOK-org1" for _argv, token in record)
    # it asked for projects first, then listed each
    assert record[0][0] == ["mcp-taiga", "projects", "--json"]
    assert ["mcp-taiga", "list", "amebo", "--json"] in [a for a, _ in record]


def test_field_mapping_and_unassigned_signal():
    reader = TaigaCliTaskReader(
        resolve=lambda org_id: "TOK",
        runner=make_runner(by_slug={"amebo": AMEBO_STORIES}, projects=
                           '[{"id":77,"slug":"amebo","name":"Amebo"}]'))
    tasks = {t.id: t for t in reader.list_tasks(org_id=1)}
    assert tasks["3"].title == "Auto-Backfill"
    assert tasks["3"].status == "In progress"
    assert tasks["3"].assignee == "352"     # owned
    assert tasks["9"].assignee is None      # null -> unassigned (the opportunity)
    assert all(t.due_date is None for t in tasks.values())


def test_unassigned_tasks_flow_into_opportunity_selection():
    from src.services.opportunity_claw import OpportunityClawConfig, select_candidates

    reader = TaigaCliTaskReader(resolve=lambda org_id: "TOK", runner=make_runner())
    opps = select_candidates(list(reader.list_tasks(org_id=1)),
                             OpportunityClawConfig())
    # both unassigned/open stories across the two projects survive
    assert {t.id for t in opps} == {"9", "1"}


def test_no_token_mapped_returns_empty_without_calling_cli():
    calls = []
    reader = TaigaCliTaskReader(
        resolve=lambda org_id: None, runner=make_runner(record=calls))
    assert list(reader.list_tasks(org_id=1)) == []
    assert calls == []                       # never shelled out


def test_login_with_no_projects_is_empty():
    reader = TaigaCliTaskReader(resolve=lambda org_id: "TOK",
                                runner=make_runner(projects="[]"))
    assert list(reader.list_tasks(org_id=1)) == []


def test_cli_error_string_degrades_to_empty():
    def runner(argv, token):
        return "Error: mcp-taiga exited 1: not authenticated"
    reader = TaigaCliTaskReader(resolve=lambda org_id: "TOK", runner=runner)
    assert list(reader.list_tasks(org_id=1)) == []


def test_malformed_json_degrades_to_empty():
    def runner(argv, token):
        return "[ {ref: 1, " if argv[1] == "projects" else "[]"
    reader = TaigaCliTaskReader(resolve=lambda org_id: "TOK", runner=runner)
    assert list(reader.list_tasks(org_id=1)) == []
