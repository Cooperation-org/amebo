"""The importance rubric: per-org weights over the judged half of ranking.

Golda 2026-09-06: not deadlines; a person waiting is most important; then
whether somebody would be interested, for money or a warm contact; different
per org and per person; configurable, with a skill to change it.
"""
from datetime import date

from src.services.rubric import Rubric
from src.services.work_list import (
    JUDGED_CEILING, build_item, build_open_context_item, judged_rank,
)

TODAY = date(2026, 9, 6)


def story(**kw):
    base = {
        "id": 1, "ref": 34, "subject": "wire the badge embed",
        "description": "the details", "due_date": None, "assigned_to": 7,
        "assigned_to_extra_info": {"username": "goldavelez_org"},
        "created_date": "2026-01-10T09:00:00.000Z",
        "modified_date": "2026-09-01T09:00:00.000Z",
        "status_extra_info": {"is_closed": False},
    }
    base.update(kw)
    return base


def lead(**kw):
    base = {"id": 46, "name": "open supply hub data",
            "user_id": [11, "Gitonga"], "stage_id": [7, "Connected"],
            "partner_id": [354, "Open Supply Hub"], "activity_ids": [],
            "date_last_stage_update": "2026-08-20 09:00:00",
            "expected_revenue": 0.0}
    base.update(kw)
    return base


def test_defaults_rank_exactly_as_before():
    assert judged_rank(story(), today=TODAY) == judged_rank(
        story(), today=TODAY, rubric=Rubric())


def test_from_config_ignores_junk_and_keeps_the_rest():
    r = Rubric.from_config({"rubric": {"someone_waiting": "300", "money": "lots",
                                       "nonsense": 1, "top_n": 3}})
    assert r.someone_waiting == 300.0
    assert r.money == 0.0            # would not coerce -> default
    assert r.top_n == 3
    assert Rubric.from_config(None) == Rubric()
    assert Rubric.from_config({"rubric": "no"}) == Rubric()


def test_someone_waiting_weight_is_the_orgs_call():
    asked = {"who": "kene", "text": "can you look?"}
    low = judged_rank(story(), today=TODAY, comment=asked, viewer="goldavelez_org",
                      rubric=Rubric(someone_waiting=10))
    high = judged_rank(story(), today=TODAY, comment=asked, viewer="goldavelez_org",
                       rubric=Rubric(someone_waiting=400))
    assert high > low
    assert high <= JUDGED_CEILING - 1.0      # judgement never reaches the clock


def test_contact_wrote_last_lifts_an_opportunity_and_says_so():
    msg = {"who": "Open Supply Hub", "text": "here is the data", "url": "u"}
    off = build_open_context_item(lead(), today=TODAY, stage_rank={7: 1},
                                  message=msg, rubric=Rubric(contact_interested=0))
    on = build_open_context_item(lead(), today=TODAY, stage_rank={7: 1},
                                 message=msg, rubric=Rubric(contact_interested=150))
    assert on.rank > off.rank
    assert "Open Supply Hub wrote last" in on.reason.label
    # our own last word is not their interest
    ours = build_open_context_item(
        lead(), today=TODAY, stage_rank={7: 1},
        message={"who": "Gitonga", "text": "sent it"}, rubric=Rubric(contact_interested=150))
    assert ours.rank == off.rank


def test_money_on_the_record_lifts_when_the_org_cares():
    rich = lead(expected_revenue=5000.0)
    rtv = build_open_context_item(rich, today=TODAY, stage_rank={7: 1},
                                  rubric=Rubric(money=0))
    lt = build_open_context_item(rich, today=TODAY, stage_rank={7: 1},
                                 rubric=Rubric(money=100))
    assert lt.rank > rtv.rank
    assert "5,000 expected" in lt.reason.label
    assert "expected" not in rtv.reason.label


def test_build_item_passes_the_rubric_through():
    fast = Rubric(new=0, new_days=1)
    fresh = story(created_date="2026-09-05T09:00:00.000Z")
    a = build_item(fresh, project_slug="b", taiga_host="h", today=TODAY)
    b = build_item(fresh, project_slug="b", taiga_host="h", today=TODAY, rubric=fast)
    assert a.rank > b.rank


def test_describe_reads_top_down():
    lines = Rubric(focus="LinkedTrust: will it generate money",
                   someone_waiting=200, money=100, contact_interested=150,
                   new=50).describe()
    assert lines[0] == "LinkedTrust: will it generate money"
    assert lines[1].startswith("+200 someone is waiting")
    assert lines[2].startswith("+150 the contact wrote last")
    assert lines[-1] == "shows top 5"
