"""TaigaStoryStore: resolution through the project slug, and what counts as
'a person said something'."""

import pytest

from src.services.work_list_taiga import TaigaStoryStore


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def _get(self, path):
        self.calls.append(path)
        for prefix, value in self.responses.items():
            if path.startswith(prefix):
                return value
        return None


def store(responses, **kw):
    return TaigaStoryStore(client=FakeClient(responses),
                           host="https://taiga.example.org", **kw)


def test_ref_is_resolved_within_its_project_not_globally():
    """A ref is only unique per project, so the slug has to be part of the lookup."""
    s = store({"/api/v1/resolve": {"us": 501},
               "/api/v1/userstories/501": {"id": 501, "ref": 34}})
    assert s.story("business-dev", 34)["id"] == 501
    assert "project=business-dev" in s._client.calls[0]
    assert "us=34" in s._client.calls[0]


def test_unresolvable_ref_returns_none_rather_than_raising():
    assert store({"/api/v1/resolve": {}}).story("biz", 999) is None


def test_field_edits_are_not_speech():
    """Taiga's history mixes edits and comments; only comments are words."""
    s = store({"/api/v1/history": [
        {"comment": "", "user": {"name": "Peter"}},
        {"comment": "dns is ready, say go", "user": {"name": "Peter"}},
    ]})
    assert s.last_comment(501) == {"who": "Peter", "text": "dns is ready, say go"}


def test_deleted_comments_are_skipped():
    s = store({"/api/v1/history": [
        {"comment": "oops", "delete_comment_date": "2026-07-20",
         "user": {"name": "Peter"}},
        {"comment": "the real one", "user": {"name": "Peter"}},
    ]})
    assert s.last_comment(501)["text"] == "the real one"


def test_the_agents_own_comments_never_lead(monkeypatch):
    """The list leads with a person's words, never with amebo's."""
    monkeypatch.setenv("TAIGA_USERNAME", "amebo")
    s = store({"/api/v1/history": [
        {"comment": "found the link", "user": {"name": "amebo"}},
        {"comment": "worth doing, deadline is the 25th", "user": {"name": "Brian"}},
    ]})
    assert s.last_comment(501)["who"] == "Brian"


def test_no_comments_means_none_not_an_empty_quote():
    assert store({"/api/v1/history": []}).last_comment(501) is None
