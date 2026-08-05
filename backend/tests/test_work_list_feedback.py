"""Saying what is wrong with the list: what gets filed, and what is pushed back."""

import pytest
from fastapi import HTTPException

from src.api.routes import work_list as route


@pytest.fixture
def filed(monkeypatch):
    """Capture what would have been created on the board."""
    calls = []
    monkeypatch.setattr(route, "execute_taiga_create", lambda action: calls.append(action))
    monkeypatch.setattr(route, "publish", lambda *a, **k: None)
    return calls


@pytest.fixture(autouse=True)
def board(monkeypatch):
    class Repo:
        def get_by_org(self, org_id):
            return {"config": {"feedback_board": "amebo"}}

    import src.db.repositories.instance_repo as mod
    monkeypatch.setattr(mod, "InstanceRepo", Repo)


CLIENT = {"auth": "user", "org_id": 1, "email": "golda@example.org"}


async def say(text, subject=None, client=CLIENT):
    return await route.feedback(route.FeedbackIn(text=text, subject=subject), client=client)


@pytest.mark.asyncio
async def test_two_words_about_an_open_row_is_enough(filed):
    """The row carries the context, so the words do not have to."""
    out = await say("wrong person", subject="taiga:amebo#20")
    assert out.filed == "amebo"
    payload = filed[0]["payload"]
    assert payload["subject"] == "wrong person"      # their words, not a summary
    assert "taiga:amebo#20" in payload["description"]
    assert "golda@example.org" in payload["description"]


@pytest.mark.asyncio
async def test_a_story_row_carries_a_way_back_to_it(filed):
    await say("opens blank", subject="taiga:amebo#20")
    assert "/p/amebo/board?story=20" in filed[0]["payload"]["description"]


@pytest.mark.asyncio
async def test_two_words_about_nothing_is_pushed_back(filed):
    """Nobody could act on it later, and filing it would only look like it went
    somewhere."""
    with pytest.raises(HTTPException) as exc:
        await say("wrong")
    assert exc.value.status_code == 400
    assert not filed


@pytest.mark.asyncio
async def test_something_about_the_list_itself_needs_no_row(filed):
    await say("the past section is too long")
    assert filed[0]["payload"]["subject"] == "the past section is too long"


@pytest.mark.asyncio
async def test_saying_nothing_is_pushed_back(filed):
    for text in ("", "   "):
        with pytest.raises(HTTPException) as exc:
            await say(text)
        assert exc.value.status_code == 400
    assert not filed


@pytest.mark.asyncio
async def test_a_long_complaint_keeps_all_of_itself(filed):
    """The title is trimmed to fit a board row; the whole thing still has to be
    readable, so it goes in the body too."""
    long = ("the list " + "keeps showing me other people's work " * 5).strip()
    await say(long)
    payload = filed[0]["payload"]
    assert len(payload["subject"]) <= 120
    assert long in payload["description"]


@pytest.mark.asyncio
async def test_no_board_configured_files_nowhere_and_says_so(filed, monkeypatch):
    """Never guess a board. Filing onto the wrong one is worse than saying
    plainly that nobody has said where these go."""
    class Repo:
        def get_by_org(self, org_id):
            return {"config": {}}

    import src.db.repositories.instance_repo as mod
    monkeypatch.setattr(mod, "InstanceRepo", Repo)
    with pytest.raises(HTTPException) as exc:
        await say("wrong person", subject="taiga:amebo#20")
    assert exc.value.status_code == 501
    assert not filed


@pytest.mark.asyncio
async def test_a_board_that_refuses_says_nothing_was_lost(filed, monkeypatch):
    def boom(action):
        raise RuntimeError("taiga_create_task failed")

    monkeypatch.setattr(route, "execute_taiga_create", boom)
    with pytest.raises(HTTPException) as exc:
        await say("wrong person", subject="taiga:amebo#20")
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_a_service_key_has_no_list_to_complain_about(filed):
    with pytest.raises(HTTPException) as exc:
        await say("wrong person", client={"auth": "service"})
    assert exc.value.status_code == 403
