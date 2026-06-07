"""Tests for the /task slash-command parser (the deterministic front door)."""

from src.services.slack_commands import parse_task_command


def test_full_command():
    payload, err = parse_task_command(
        "amebo Ship the badge embed due:2026-06-20 assign:golda cash:50"
    )
    assert err is None
    assert payload == {
        "project": "amebo",
        "subject": "Ship the badge embed",
        "due_date": "2026-06-20",
        "assignee": "golda",
        "cash": 50,
    }


def test_minimal_project_subject_due():
    payload, err = parse_task_command("amebo Fix the thing due:2026-07-01")
    assert err is None
    assert payload == {
        "project": "amebo", "subject": "Fix the thing", "due_date": "2026-07-01",
    }


def test_keys_can_precede_rest_of_subject():
    # key:value tokens may appear anywhere after the project.
    payload, err = parse_task_command("bd due:2026-06-30 Call the prospect back assign:peter")
    assert err is None
    assert payload["subject"] == "Call the prospect back"
    assert payload["due_date"] == "2026-06-30"
    assert payload["assignee"] == "peter"


def test_due_required():
    payload, err = parse_task_command("amebo Do something")
    assert payload is None
    assert "deadline is required" in err


def test_bad_due_date():
    payload, err = parse_task_command("amebo Do something due:June-20")
    assert payload is None
    assert "not a valid date" in err


def test_missing_subject():
    payload, err = parse_task_command("amebo due:2026-06-20")
    assert payload is None
    assert "Missing task subject" in err


def test_cash_must_be_number():
    payload, err = parse_task_command("amebo Do it due:2026-06-20 cash:lots")
    assert payload is None
    assert "must be a number" in err


def test_too_few_tokens():
    payload, err = parse_task_command("amebo")
    assert payload is None
    assert "Usage" in err
