"""Work list: ranking rules, provenance, and the past-due split."""

from datetime import date

from src.services.work_list import (
    Link, assemble, build_item, clock_rank, clock_reason, goal_task_refs,
    items_from_drafts, items_from_goals, judged_rank, links_from_story,
    parse_subject, JUDGED_CEILING, CLOCK_FLOOR,
)

HOST = "https://marten.example.org"  # the person-facing interface, never Taiga
TODAY = date(2026, 7, 25)


def story(**kw):
    base = {
        "id": 1, "ref": 34, "subject": "Apply: NCBA IMPACT 2026",
        "description": "", "due_date": None,
        "assigned_to": None, "assigned_to_extra_info": None,
    }
    base.update(kw)
    return base


class FakeStore:
    def __init__(self, stories, comments=None):
        self._stories = stories          # {(slug, ref): story}
        self._comments = comments or {}  # {story_id: comment}

    def story(self, slug, ref):
        return self._stories.get((slug, ref))

    def last_comment(self, story_id):
        return self._comments.get(story_id)


# --------------------------------------------------------------- ranking

def test_dated_always_outranks_judged():
    """The invariant: judgement can never bury a dated item."""
    dated = clock_rank("2027-12-31", TODAY)     # a year out, still dated
    judged = judged_rank(story(assigned_to=7, description="lots"))
    assert judged <= JUDGED_CEILING < CLOCK_FLOOR <= dated


def test_sooner_ranks_higher():
    assert clock_rank("2026-07-25", TODAY) > clock_rank("2026-07-28", TODAY)


def test_clock_reason_speaks_plainly():
    assert clock_reason("2026-07-25", TODAY).label == "today"
    assert clock_reason("2026-07-26", TODAY).label == "tomorrow"
    assert clock_reason("2026-07-28", TODAY).label == "in 3 days"
    assert clock_reason(None, TODAY) is None


def test_clock_reason_is_a_rule_judged_is_a_call():
    assert clock_reason("2026-07-25", TODAY).kind == "clock"
    item = build_item(story(), project_slug="p", taiga_host=HOST, today=TODAY)
    assert item.reason.kind == "judgement"


def test_undated_item_falls_back_to_judgement():
    owned = build_item(story(assigned_to=7, description="do the thing"),
                       project_slug="p", taiga_host=HOST, today=TODAY)
    orphan = build_item(story(), project_slug="p", taiga_host=HOST, today=TODAY)
    assert owned.rank > orphan.rank
    assert orphan.reason.label == "no owner"


# --------------------------------------------------------------- links

def test_story_link_is_always_first_and_unflagged():
    links = links_from_story(story(), HOST, "biz")
    assert links[0].url == f"{HOST}/p/biz/board?story=34"
    assert links[0].found is False


def test_urls_in_the_description_come_through_readable():
    links = links_from_story(
        story(description="apply at https://ncba.coop/impact/cfp before friday"),
        HOST, "biz")
    assert links[1].url == "https://ncba.coop/impact/cfp"
    assert links[1].label == "ncba.coop/impact"


def test_found_defaults_off_so_only_looked_up_links_are_flagged():
    assert all(not l.found for l in links_from_story(
        story(description="see https://example.org/x"), HOST, "biz"))
    assert Link("x", "https://x", found=True).found is True


# --------------------------------------------------------------- their words

def test_a_human_comment_becomes_the_headline_with_a_way_back():
    item = build_item(story(), project_slug="biz", taiga_host=HOST, today=TODAY,
                      comment={"who": "Peter", "text": "dns is ready, say go"})
    assert item.quote.who == "Peter"
    assert item.quote.text == "dns is ready, say go"
    assert item.quote.url == f"{HOST}/p/biz/board?story=34"


def test_no_comment_means_no_headline_not_invented_prose():
    item = build_item(story(), project_slug="biz", taiga_host=HOST, today=TODAY)
    assert item.quote is None


# --------------------------------------------------------------- assembly

def test_past_due_leaves_the_live_list():
    store = FakeStore({
        ("biz", 34): story(ref=34, due_date="2026-07-17"),
        ("biz", 40): story(id=2, ref=40, due_date="2026-07-25"),
    })
    out = assemble(["biz#34", "biz#40"], store, taiga_host=HOST, today=TODAY)
    assert [i.subject for i in out.live] == ["taiga:biz#40"]
    assert [i.subject for i in out.past] == ["taiga:biz#34"]


def test_live_list_is_one_list_sorted_by_rank():
    store = FakeStore({
        ("biz", 1): story(id=1, ref=1, subject="undated", assigned_to=3),
        ("biz", 2): story(id=2, ref=2, subject="next week", due_date="2026-08-01"),
        ("biz", 3): story(id=3, ref=3, subject="today", due_date="2026-07-25"),
    })
    out = assemble(["biz#1", "biz#2", "biz#3"], store, taiga_host=HOST, today=TODAY)
    assert [i.title for i in out.live] == ["today", "next week", "undated"]


def test_one_unreadable_story_does_not_sink_the_list():
    class Half(FakeStore):
        def story(self, slug, ref):
            if ref == 99:
                raise RuntimeError("taiga said no")
            return super().story(slug, ref)

    store = Half({("biz", 34): story(due_date="2026-07-25")})
    out = assemble(["biz#99", "biz#34"], store, taiga_host=HOST, today=TODAY)
    assert len(out.live) == 1


def test_a_story_closed_elsewhere_leaves_the_list():
    """Archive or close it in Marten, or from the sheet, and it stops being live
    work — whatever the drafted pings still say."""
    store = FakeStore({
        ("biz", 34): story(ref=34, due_date="2026-07-25",
                           status_extra_info={"name": "Archived", "is_closed": True}),
        ("biz", 40): story(id=2, ref=40, due_date="2026-07-25",
                           status_extra_info={"name": "In Progress", "is_closed": False}),
    })
    out = assemble(["biz#34", "biz#40"], store, taiga_host=HOST, today=TODAY)
    assert [i.subject for i in out.live] == ["taiga:biz#40"]
    assert out.past == []


def test_unparseable_subject_is_skipped():
    assert parse_subject("nonsense") is None
    assert parse_subject("biz#notanumber") is None
    assert parse_subject("biz#34") == ("biz", 34)


# --------------------------------------------------------------- many sources

def test_a_draft_about_a_listed_task_is_not_a_second_row():
    """The task is the thing; the message about the task is not another item."""
    drafts = [{"id": "d1", "payload": {"followup_task": "biz#34", "text": "ping"}}]
    assert items_from_drafts(drafts, already=["taiga:biz#34"]) == []


def test_a_standalone_draft_survives_and_keeps_its_links():
    drafts = [{"id": "d2", "payload": {
        "text": "Send to Vineeth: offer stands, see https://linkedtrust.us/bare-metal"}}]
    [item] = items_from_drafts(drafts, already=["taiga:biz#34"])
    assert item.subject == "draft:d2"
    assert item.links[0].url == "https://linkedtrust.us/bare-metal"


def test_questions_and_drafts_rank_above_other_judged_but_under_any_date():
    goal = items_from_goals([{"id": "g1", "title": "RTV Mexico?"}])[0]
    dated = clock_rank("2027-12-31", TODAY)
    owned = judged_rank(story(assigned_to=7, description="x"))
    assert owned < goal.rank <= JUDGED_CEILING < dated


def test_a_goal_with_no_title_still_shows_something():
    [item] = items_from_goals([{"id": "g2", "title": "  "}])
    assert item.title == "(untitled)"


# ------------------------------------------------------- goals holding tasks

def test_a_goal_naming_one_story_holds_exactly_that_task():
    goal = {"title": "Remind Golda", "description":
            "Taiga story #4 in project core-linkedtrust-amebo-abra, due soon."}
    assert goal_task_refs(goal) == [("core-linkedtrust-amebo-abra", 4)]


def test_a_story_url_counts_and_duplicates_collapse():
    goal = {"title": "Follow up", "description":
            "Taiga story #7 in project civic-action — see "
            "https://taiga.linkedtrust.us/project/civic-action/us/7 for context."}
    assert goal_task_refs(goal) == [("civic-action", 7)]


def test_a_goal_holding_several_tasks_reports_all_of_them():
    """Not one-to-one: a goal can hold many tasks, and callers must see that."""
    goal = {"title": "Sweep", "description":
            "Taiga story #1 in project biz and Taiga story #2 in project biz."}
    assert goal_task_refs(goal) == [("biz", 1), ("biz", 2)]


def test_a_goal_about_its_own_work_holds_nothing():
    assert goal_task_refs({"title": "Weekly review sweep",
                           "description": "Find the mess, propose cleanup."}) == []
    assert goal_task_refs({"title": "x", "description": None}) == []
