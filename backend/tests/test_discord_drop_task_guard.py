"""
/drop-task speaker guard — refuses when the Discord user is not enrolled in
GovKit, or is enrolled but has no Taiga username on file; defaults the Taiga
assignee from the membership when the caller did not pass one.

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
    """No Membership keyed on this discord_user_id AND no assignee given → refuse with the 'link Discord' message."""
    refusal, assignee = _drop_task_guard(_speaker(member=None), "")
    assert "Discord" in refusal
    assert "steward" in refusal.lower()
    assert assignee == ""


def test_guard_refuses_when_mapped_but_taiga_username_empty():
    """Enrolled in GovKit but Membership.taiga_username is empty AND no assignee given → refuse with the 'set Taiga username' message."""
    refusal, assignee = _drop_task_guard(_speaker(member=_member(taiga_username="")), "")
    assert "Taiga username" in refusal
    assert assignee == ""


def test_guard_defaults_assignee_from_membership():
    refusal, assignee = _drop_task_guard(_speaker(member=_member()), "")
    assert refusal == ""
    assert assignee == "x-taiga"


def test_guard_respects_explicit_assignee():
    refusal, assignee = _drop_task_guard(_speaker(member=_member()), "other-taiga")
    assert refusal == ""
    assert assignee == "other-taiga"


def test_guard_allows_explicit_assignee_for_unmapped_speaker():
    """Anyone in the Discord server can drop a task for someone else by naming
    them. Unmapped runner + explicit assignee → allow, use the caller's value.
    The Done webhook resolves equity by the assignee's Taiga username, not by
    the runner's discord_user_id, so no GovKit membership is required."""
    refusal, assignee = _drop_task_guard(_speaker(member=None), "other-taiga")
    assert refusal == ""
    assert assignee == "other-taiga"


def test_guard_allows_explicit_assignee_when_mapped_without_taiga_username():
    """Explicit assignee wins even when the runner is mapped but has no Taiga
    username on file — the named assignee is who the work is for."""
    refusal, assignee = _drop_task_guard(
        _speaker(member=_member(taiga_username="")), "other-taiga"
    )
    assert refusal == ""
    assert assignee == "other-taiga"
