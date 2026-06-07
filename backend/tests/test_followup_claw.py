"""Tests for the deadline-day follow-up claw (drive-to-done v1)."""

from src.services.followup_claw import build_ping, followup_key, run_deadline_followups


def _story(ref, due, subject="Do the thing", assignee="golda", creator="kene", slug="amebo"):
    s = {"ref": ref, "due_date": due, "subject": subject,
         "project_extra_info": {"slug": slug}}
    if assignee:
        s["assigned_to_extra_info"] = {"username": assignee}
    if creator:
        s["owner_extra_info"] = {"username": creator}
    return s


class FakeTaiga:
    def __init__(self, stories_by_project):
        self.stories_by_project = stories_by_project

    def open_stories(self, pid):
        return self.stories_by_project.get(pid, [])


def test_build_ping_names_assignee_and_creator():
    msg = build_ping(_story(7, "2026-06-20", assignee="golda", creator="kene"))
    assert "#7" in msg and "due today" in msg
    assert "golda" in msg and "kene" in msg


def test_pings_only_tasks_due_today():
    taiga = FakeTaiga({1: [
        _story(1, "2026-06-20"),          # due today
        _story(2, "2026-06-25"),          # later
        _story(3, "2026-06-10"),          # past (not today — v1 only deadline day)
    ]})
    drafts = []
    res = run_deadline_followups(
        org_id=1, channel="#bd",
        taiga=taiga, project_ids=[1],
        gate=lambda ch, text, key: drafts.append(key),
        already_pinged=lambda key: False,
        today="2026-06-20",
    )
    assert res["drafted"] == 1
    assert drafts == ["amebo#1"]


def test_dedup_skips_already_pinged():
    taiga = FakeTaiga({1: [_story(1, "2026-06-20")]})
    drafts = []
    res = run_deadline_followups(
        org_id=1, channel="#bd",
        taiga=taiga, project_ids=[1],
        gate=lambda ch, text, key: drafts.append(key),
        already_pinged=lambda key: True,   # already pinged today
        today="2026-06-20",
    )
    assert res["drafted"] == 0
    assert res["skipped"] == 1
    assert drafts == []


def test_no_channel_is_a_noop():
    res = run_deadline_followups(org_id=1, channel="", taiga=FakeTaiga({}), project_ids=[1])
    assert res["drafted"] == 0
    assert res["reason"] == "no_channel"


def test_followup_key_format():
    assert followup_key("amebo", 7) == "amebo#7"


def test_multiple_projects_and_mixed_dates():
    taiga = FakeTaiga({
        1: [_story(1, "2026-06-20", slug="amebo"), _story(2, "2026-06-21", slug="amebo")],
        2: [_story(5, "2026-06-20", slug="bd")],
    })
    drafts = []
    res = run_deadline_followups(
        org_id=1, channel="#bd",
        taiga=taiga, project_ids=[1, 2],
        gate=lambda ch, text, key: drafts.append(key),
        already_pinged=lambda key: False,
        today="2026-06-20",
    )
    assert res["drafted"] == 2
    assert set(drafts) == {"amebo#1", "bd#5"}
