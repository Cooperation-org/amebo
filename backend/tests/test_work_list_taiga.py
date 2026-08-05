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
    """A ref is only unique per project, so the project is part of the lookup."""
    s = store({"/api/v1/projects/by_slug": {"id": 110},
               "/api/v1/userstories/by_ref": {"id": 501, "ref": 34}})
    assert s.story("business-dev", 34)["id"] == 501
    assert "slug=business-dev" in s._client.calls[0]
    assert "project=110" in s._client.calls[1] and "ref=34" in s._client.calls[1]


def test_by_ref_not_a_ref_filter():
    """The list endpoint ignores ?ref= and hands back the project's FIRST story,
    which silently shows the wrong task. by_ref is the only correct lookup."""
    s = store({"/api/v1/projects/by_slug": {"id": 110},
               "/api/v1/userstories/by_ref": {"id": 501, "ref": 34}})
    s.story("business-dev", 34)
    assert not any("userstories?project" in c for c in s._client.calls)


def test_project_id_is_looked_up_once_per_slug():
    s = store({"/api/v1/projects/by_slug": {"id": 110},
               "/api/v1/userstories/by_ref": {"id": 501, "ref": 34}})
    s.story("biz", 34)
    s.story("biz", 35)
    assert sum("by_slug" in c for c in s._client.calls) == 1


def test_unknown_project_returns_none_rather_than_raising():
    assert store({"/api/v1/projects/by_slug": {}}).story("nope", 999) is None


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


# ---------------------------------------------------- learning the boards once

class ProjectsClient:
    """Counts what the store actually asks Taiga for."""

    def __init__(self, projects=None, by_slug=None):
        self.projects = projects if projects is not None else []
        self.by_slug = by_slug or {}
        self.calls = []

    def _get(self, path):
        self.calls.append(path)
        if path == "/api/v1/projects":
            return self.projects
        if path.startswith("/api/v1/projects/by_slug"):
            return self.by_slug.get(path.split("slug=")[1])
        if path.startswith("/api/v1/projects/"):
            pid = int(path.rsplit("/", 1)[1])
            return next((p for p in self.projects if p["id"] == pid), {})
        return None


def store_with(projects, by_slug=None):
    from src.services.work_list_taiga import TaigaStoryStore
    client = ProjectsClient(projects, by_slug)
    return TaigaStoryStore(client=client), client


def test_every_board_is_named_from_one_listing():
    """Naming each story's board used to cost a request per board, in a row,
    while the page waited."""
    store, client = store_with([{"id": 1, "slug": "alpha"}, {"id": 2, "slug": "beta"}])
    store.prime_slugs()
    assert store.project_slug_of({"project": 1}) == "alpha"
    assert store.project_slug_of({"project": 2}) == "beta"
    assert client.calls == ["/api/v1/projects"]


def test_priming_answers_which_boards_are_blocked():
    store, client = store_with([
        {"id": 1, "slug": "alpha", "blocked_code": "blocked-by-owner-plan"},
        {"id": 2, "slug": "beta"},
    ])
    store.prime_slugs()
    before = len(client.calls)
    assert store.project_blocked("alpha") is True
    assert store.project_blocked("beta") is False
    assert len(client.calls) == before      # answered without asking again


def test_priming_does_not_stand_in_for_the_full_record():
    """The listing leaves out us_statuses. Caching it as the whole record would
    leave the sheet with no statuses and archive reporting nowhere to archive."""
    store, _client = store_with(
        [{"id": 1, "slug": "alpha"}],
        by_slug={"alpha": {"id": 1, "slug": "alpha",
                           "us_statuses": [{"name": "Archived", "is_archived": True}]}})
    store.prime_slugs()
    assert store.archived_status("alpha") == "Archived"


def test_a_listing_that_fails_still_leaves_a_working_store():
    from src.services.work_list_taiga import TaigaStoryStore

    class Broken(ProjectsClient):
        def _get(self, path):
            if path == "/api/v1/projects":
                raise RuntimeError("taiga down")
            return super()._get(path)

    client = Broken([{"id": 1, "slug": "alpha"}])
    store = TaigaStoryStore(client=client)
    store.prime_slugs()                       # must not raise
    assert store.project_slug_of({"project": 1}) == "alpha"


def test_comments_are_fetched_together_and_one_bad_history_is_not_fatal():
    from src.services.work_list_taiga import TaigaStoryStore

    class Histories(ProjectsClient):
        def _get(self, path):
            if path == "/api/v1/history/userstory/7":
                raise RuntimeError("unreadable")
            if path == "/api/v1/history/userstory/8":
                return [{"comment": "ready to go", "user": {"name": "Kene"}}]
            return super()._get(path)

    store = TaigaStoryStore(client=Histories([]))
    got = store.last_comments([7, 8])
    assert got == {8: {"who": "Kene", "text": "ready to go"}}
