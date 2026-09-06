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


def test_drafts_fade_with_age_on_the_orgs_quiet_rule():
    from src.services.work_list import items_from_drafts
    fresh = {"id": "a", "preview": "send this", "payload": {},
             "requested_at": "2026-09-05T10:00:00+00:00"}
    july = {"id": "b", "preview": "deadline ping", "payload": {},
            "requested_at": "2026-07-20T10:00:00+00:00"}
    items = items_from_drafts([fresh, july], today=TODAY, rubric=Rubric())
    by = {i.subject: i for i in items}
    assert by["draft:a"].rank > by["draft:b"].rank
    assert by["draft:a"].rank == 300 + 100 - 2          # one day old
    assert by["draft:b"].rank == 300 + 100 - 96         # 48 days * 2, under the cap
    assert "48 days" in by["draft:b"].reason.label
    # no timestamp: unchanged from before
    assert items_from_drafts([{"id": "c", "preview": "x", "payload": {}}])[0].rank == 400
    # a person waiting on a task beats amebo's own ask
    asked = judged_rank(story(), today=TODAY, comment={"who": "kene", "text": "?"},
                        viewer="goldavelez_org", rubric=Rubric(someone_waiting=300))
    assert asked > by["draft:a"].rank


def test_a_parked_unowned_task_is_waiting_on_a_person_not_backlog():
    """A doer session parks with 'NEEDS: ...' (prompts/skills/doer.md). That
    task has no owner and no date, which used to make it backlog nobody saw."""
    from src.services.work_list import assemble_stories

    class Store:
        def project_slug_of(self, story): return "core"
        def project_blocked(self, slug): return False
        def last_comment(self, sid):
            return {"who": "amebo", "text": "NEEDS: the SNAP contact's email. Because: nothing on the record."} if sid == 2 else None
        def statuses(self, slug): return []

    parked = story(id=2, ref=15, subject="SNAP outreach brief", assigned_to=None,
                   assigned_to_extra_info=None, created_date="2026-06-01T00:00:00Z",
                   tags=[["agent", None]])
    plain = story(id=3, ref=16, subject="something unowned", assigned_to=None,
                  assigned_to_extra_info=None, created_date="2026-06-01T00:00:00Z")
    # fill the page so there is no room for backlog
    owned = [story(id=100 + i, ref=100 + i, subject=f"mine {i}") for i in range(20)]
    wl = assemble_stories([parked, plain, *owned], Store(), taiga_host="h",
                          today=TODAY, viewer_username="goldavelez_org")
    subjects = [i.subject for i in wl.live]
    assert "taiga:core#15" in subjects
    assert "taiga:core#16" not in subjects
    row = next(i for i in wl.live if i.subject == "taiga:core#15")
    assert "amebo asked" in row.reason.label


def test_judgement_moves_rows_inside_the_band_and_never_a_dated_one():
    from src.services import rubric_judge
    from src.services.work_list import Item, Reason, CLOCK_FLOOR
    rubric_judge._cache.clear()
    dated = Item(subject="taiga:core#1", title="due soon", reason=Reason("tomorrow", "clock"),
                 rank=CLOCK_FLOOR + 300, links=[], quote=None, due="2026-09-07", assignee=None)
    a = Item(subject="taiga:core#2", title="level up flyer", reason=Reason("open", "judgement"),
             rank=400, links=[], quote=None, due=None, assignee=None)
    b = Item(subject="crm:lead/3", title="cold lead", reason=Reason("reached out", "judgement"),
             rank=450, links=[], quote=None, due=None, assignee=None)

    class Resp:
        content = [type("T", (), {"text": '[{"subject":"taiga:core#2","nudge":120,"why":"Level Up first this month"},'
                                          '{"subject":"taiga:core#1","nudge":-150,"why":"ignore"}]'})()]

    class Client:
        calls = 0
        class messages:
            @staticmethod
            def create(**kw):
                Client.calls += 1
                return Resp()

    r = Rubric(judgement="Level Up workshop comes first this month")
    out = rubric_judge.judge([dated, b, a], rubric=r, org_id=1, viewer="golda", client=Client())
    assert [i.subject for i in out] == ["taiga:core#1", "taiga:core#2", "crm:lead/3"]
    assert out[0].rank == CLOCK_FLOOR + 300            # the clock never moves
    assert out[1].rank == 520 and out[1].reason.label == "Level Up first this month"
    # second read of the same candidates: cached, no second call
    rubric_judge.judge([dated, b, a], rubric=r, org_id=1, viewer="golda", client=Client())
    assert Client.calls == 1
    # no judgement text: untouched, no call
    assert rubric_judge.judge([b, a], rubric=Rubric(), org_id=1, viewer="golda", client=Client())[0].subject == "crm:lead/3"



def test_an_agents_done_is_a_review_not_a_person_waiting():
    agent = {"who": "admin", "text": "Done: /opt/shared/projects/Internal/x.md"}
    human = {"who": "kene", "text": "can you look?"}
    r = Rubric(someone_waiting=300, agent_asks=80)
    a = judged_rank(story(), today=TODAY, comment=agent, viewer="goldavelez_org",
                    rubric=r, agents=["amebo", "admin"])
    h = judged_rank(story(), today=TODAY, comment=human, viewer="goldavelez_org",
                    rubric=r, agents=["amebo", "admin"])
    assert h - a == 220
    from src.services.work_list import judged_reason
    s = story(status_extra_info={"is_closed": False, "name": "Ready for test"})
    assert judged_reason(s, today=TODAY, comment=agent, viewer="goldavelez_org",
                         agents=["admin"]).label == "admin asks: ready for test"


def test_waiting_status_counts_only_under_the_agent_contract():
    from src.services.work_list import _waiting_status
    old = story(status_extra_info={"is_closed": False, "name": "Ready for test"}, tags=[])
    new = story(status_extra_info={"is_closed": False, "name": "Needs human"}, tags=[["agent", None]])
    assert not _waiting_status(old)
    assert _waiting_status(new)


def test_twelve_dones_fold_into_one_row_and_needs_human_stays():
    from src.services.work_list import Item, Reason, Link, collapse_reviews
    def t(n, label, rank):
        return Item(subject=f"taiga:core#{n}", title=f"thing {n}", reason=Reason(label, "judgement"),
                    rank=rank, links=[Link("open", f"https://marten.linkedtrust.us/board?story={n}")],
                    quote=None, due=None, assignee=None)
    items = [t(1, "admin asks: ready for test", 380), t(2, "admin asks: ready for test", 376),
             t(3, "admin asks: needs human", 379), t(4, "reached out", 392)]
    out = collapse_reviews(items)
    subjects = [i.subject for i in out]
    assert subjects == ["taiga:core#4", "review:ready-for-test", "taiga:core#3"]
    row = out[1]
    assert row.title.startswith("2 things amebo finished")
    assert [l.url for l in row.links] == ["https://marten.linkedtrust.us/board?story=1",
                                          "https://marten.linkedtrust.us/board?story=2"]
    assert row.kind == "review"
    # one review is not a pile: left alone
    assert [i.subject for i in collapse_reviews(items[1:])] == ["taiga:core#2", "taiga:core#3", "taiga:core#4"]


def test_an_agents_new_story_is_not_news():
    fresh = story(created_date="2026-09-05T09:00:00.000Z",
                  owner_extra_info={"username": "admin"})
    a = judged_rank(fresh, today=TODAY, agents=["admin"])
    b = judged_rank(fresh, today=TODAY, agents=[])
    assert b - a == Rubric().new


def test_an_agents_done_in_a_decision_status_is_still_a_review():
    from src.services.work_list import Item, Reason, Link, Quote, collapse_reviews
    def t(n, label, text):
        return Item(subject=f"taiga:core#{n}", title=f"thing {n}", reason=Reason(label, "judgement"),
                    rank=456, links=[Link("open", f"https://marten.linkedtrust.us/board?story={n}")],
                    quote=Quote("admin", text), due=None, assignee=None)
    items = [t(1, "admin asks: needs human", "Done: /opt/x.md"),
             t(2, "admin asks: needs human", "No CIVICUS grant document exists anywhere."),
             t(3, "admin asks: new", "Shipped 2026-08-05 (govkit main)"),
             t(4, "admin asks: needs human", "NEEDS: the SNAP contact's email")]
    out = collapse_reviews(items)
    assert [i.subject for i in out] == ["review:ready-for-test", "taiga:core#2", "taiga:core#4"]
    assert out[0].title.startswith("2 things")


def test_forty_same_day_followups_are_one_row():
    from src.services.work_list import Item, Reason, Link, collapse_followups, CLOCK_FLOOR
    def c(n):
        return Item(subject=f"crm:activity/{n}", title="Level Up partner-code invite",
                    reason=Reason("in 2 days", "clock"), rank=CLOCK_FLOOR + 363,
                    links=[Link("Org", f"https://elm.linkedtrust.us/c/37?lead={n}")],
                    quote=None, due="2026-09-08", assignee="Golda Velez")
    other = Item(subject="taiga:core#1", title="x", reason=Reason("open", "judgement"), rank=400,
                 links=[], quote=None, due=None, assignee=None)
    out = collapse_followups([c(1), c(2), c(3), c(4), other])
    assert len(out) == 2
    row = out[0]
    assert row.title == "4 × Level Up partner-code invite" and row.due == "2026-09-08"
    assert row.links[0].url == "https://elm.linkedtrust.us/c/37" and row.kind == "review"
    assert [i.subject for i in collapse_followups([c(1), c(2), other])][0] == "crm:activity/1"
