"""
/drop-task speaker guard — refuses when the Discord user is not enrolled in
GovKit; defaults the Taiga assignee from the membership when the caller
did not pass one.

The map lives in GovKit; this guard is the only thing amebo runs before the
Taiga call. It does no I/O of its own — the Speaker arrives already
identified by policy.identify() — so these tests are pure.
"""

from src.channels.discord_policy import Speaker
from src.integrations.govkit_directory import Member
from src.services.discord_bot import _drop_task_guard


def _speaker(member=None):
    return Speaker(
        discord_user_id="111",
        display_name="Test User",
        member=member,
    )


def _member(taiga_username="x-taiga", role="member"):
    return Member(
        display_name="Test User",
        role=role,
        email="",
        org_slug="vc",
        taiga_username=taiga_username,
    )


def test_guard_refuses_unknown_speaker():
    ok, assignee = _drop_task_guard(_speaker(member=None), "")
    assert ok is False
    assert assignee == ""


def test_guard_defaults_assignee_from_membership():
    ok, assignee = _drop_task_guard(_speaker(member=_member()), "")
    assert ok is True
    assert assignee == "x-taiga"


def test_guard_respects_explicit_assignee():
    ok, assignee = _drop_task_guard(_speaker(member=_member()), "other-taiga")
    assert ok is True
    assert assignee == "other-taiga"


def test_guard_leaves_assignee_empty_when_mapping_has_no_taiga_username():
    ok, assignee = _drop_task_guard(_speaker(member=_member(taiga_username="")), "")
    assert ok is True
    assert assignee == ""


def test_guard_proceeds_for_mapped_speaker_with_empty_string_assignee():
    # Speaker.member exists but taiga_username is empty AND caller passed "" —
    # we do NOT default to "" (that would still resolve to no-assign in Taiga
    # and fail at Done time); we just pass through "" and let the existing
    # webhook path handle it.
    ok, assignee = _drop_task_guard(
        _speaker(member=_member(taiga_username="")),
        "",
    )
    assert ok is True
    assert assignee == ""
