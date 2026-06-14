"""
Tests for the shared TaskReader adapter over the mcp-taiga CLI.

The CLI runner is injected so the parse/mapping is exercised without touching
the live Taiga. Covers: ref/subject/status mapping, the unassigned signal
(assigned_to null -> assignee None), no-project-mapped -> empty, and graceful
degradation when the CLI returns an error string instead of JSON.
"""

from src.services.taiga_task_reader import TaigaCliTaskReader


# Real-shape sample, trimmed from `mcp-taiga list amebo --json` (2026-06-14).
SAMPLE_JSON = """[
  {"ref": 3, "subject": "Implement Auto-Backfill", "status": "In progress", "assigned_to": 352, "tags": []},
  {"ref": 9, "subject": "Sensitive Channel Filtering", "status": "New", "assigned_to": null, "tags": []}
]"""


def _reader(runner, project="amebo"):
    return TaigaCliTaskReader(resolve=lambda org_id: project, runner=runner)


def test_maps_fields_and_unassigned_signal():
    captured = {}

    def fake_runner(argv):
        captured["argv"] = argv
        return SAMPLE_JSON

    tasks = list(_reader(fake_runner).list_tasks(org_id=1))

    # called the right CLI with --json
    assert captured["argv"] == ["mcp-taiga", "list", "amebo", "--json"]
    assert [t.id for t in tasks] == ["3", "9"]
    assert tasks[0].title == "Implement Auto-Backfill"
    assert tasks[0].status == "In progress"
    assert tasks[0].assignee == "352"        # owned
    assert tasks[1].assignee is None         # null -> unassigned (the opportunity)
    assert all(t.due_date is None for t in tasks)


def test_unassigned_tasks_flow_into_opportunity_selection():
    # The adapter's output must feed select_candidates cleanly: only the
    # unassigned, open story survives.
    from src.services.opportunity_claw import OpportunityClawConfig, select_candidates

    tasks = list(_reader(lambda argv: SAMPLE_JSON).list_tasks(org_id=1))
    opps = select_candidates(tasks, OpportunityClawConfig())
    assert [t.id for t in opps] == ["9"]


def test_no_project_mapped_returns_empty_without_calling_cli():
    calls = []

    def fake_runner(argv):
        calls.append(argv)
        return SAMPLE_JSON

    reader = TaigaCliTaskReader(resolve=lambda org_id: None, runner=fake_runner)
    assert list(reader.list_tasks(org_id=1)) == []
    assert calls == []                       # never shelled out


def test_cli_error_string_degrades_to_empty():
    # run_cli returns a human-readable error (not JSON) on failure.
    reader = _reader(lambda argv: "Error: mcp-taiga exited 1: not authenticated")
    assert list(reader.list_tasks(org_id=1)) == []


def test_malformed_json_degrades_to_empty():
    reader = _reader(lambda argv: "[ {ref: 1, ")  # looks like JSON, isn't
    assert list(reader.list_tasks(org_id=1)) == []
