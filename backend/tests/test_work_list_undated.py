"""Undated tasks on the list.

Golda: it goes in the list even if it has no date. The board holds 869 open
stories and 17 of them are dated, so a list sourced from deadlines alone was
showing two percent of the work. These tests pin which undated ones earn a row,
whose row it is, and that none of them can outrank a real deadline.
"""

from datetime import date

from src.services.work_list import (
    CLOCK_FLOOR, JUDGED_CEILING, UNDATED_FLOOR,
    assemble_stories, build_item, clock_rank, judged_rank, judged_reason,
)

TODAY = date(2026, 8, 5)
HOST = "https://marten.example"


def story(**kw):
    base = {
        "id": 1, "ref": 34, "subject": "wire the badge embed",
        "description": "the details", "due_date": None,
        "assigned_to": 7, "assigned_to_extra_info": {"username": "goldavelez_org"},
        "created_date": "2026-01-10T09:00:00.000Z",
        "modified_date": "2026-06-10T09:00:00.000Z",
        "status_extra_info": {"is_closed": False},
    }
    base.update(kw)
    return base


class FakeStore:
    def __init__(self, comments=None):
        self._comments = comments or {}      # {story id -> comment}

    def project_slug_of(self, story):
        return "some-board"

    def project_blocked(self, slug):
        return False

    def last_comments(self, story_ids):
        return {i: self._comments[i] for i in story_ids if i in self._comments}

    def last_comment(self, story_id):
        return self._comments.get(story_id)


def assemble(stories, viewer="goldavelez_org", comments=None):
    return assemble_stories(stories, FakeStore(comments), taiga_host=HOST,
                            today=TODAY, viewer_username=viewer)


# ------------------------------------------------------------------ whose

def test_my_undated_task_is_on_my_list():
    out = assemble([story()])
    assert [i.subject for i in out.live] == ["taiga:some-board#34"]


def test_someone_elses_undated_task_is_not():
    out = assemble([story(assigned_to_extra_info={"username": "sahdasamier"})])
    assert out.live == []


def test_an_unowned_undated_task_is_backlog_and_goes_last():
    """367 unowned undated stories against 17 dated ones. On a full page they
    stop it being a list, so they only get in while there is room — and on a
    board holding one story there is nothing but room."""
    out = assemble([story(assigned_to=None, assigned_to_extra_info=None)])
    assert [i.subject for i in out.live] == ["taiga:some-board#34"]


def test_the_backlog_is_dropped_once_the_page_is_full():
    """The mature board: owned work already fills the twenty, so none of the
    unowned undated pile reaches anybody."""
    from src.services.work_list import LIST_MAX
    mine = [story(id=i, ref=i) for i in range(LIST_MAX)]
    unowned = [story(id=100 + i, ref=100 + i, assigned_to=None,
                     assigned_to_extra_info=None) for i in range(30)]
    out = assemble(mine + unowned)
    assert len(out.live) == LIST_MAX
    assert all(int(i.subject.rsplit("#", 1)[1]) < LIST_MAX for i in out.live)


def test_the_backlog_fills_only_the_room_that_is_left():
    from src.services.work_list import LIST_MAX
    mine = [story(id=i, ref=i) for i in range(LIST_MAX - 3)]
    unowned = [story(id=100 + i, ref=100 + i, assigned_to=None,
                     assigned_to_extra_info=None) for i in range(10)]
    out = assemble(mine + unowned)
    assert len(out.live) == LIST_MAX


def test_an_unowned_dated_task_still_reaches_everyone():
    """Opposite rule on purpose: a date is coming whether or not anyone picked
    it up."""
    out = assemble([story(due_date="2026-08-06", assigned_to=None,
                          assigned_to_extra_info=None)])
    assert [i.subject for i in out.live] == ["taiga:some-board#34"]


def test_an_unmapped_viewer_gets_dated_work_and_only_what_fits_of_the_rest():
    """Everywhere else an unmapped viewer sees too much rather than too little.
    Here 'too much' is 839 rows, which is an unusable page, not a nuisance — so
    the undated ones are still last and still cut off at the cap."""
    from src.services.work_list import LIST_MAX
    stories = ([story(id=i, ref=i, due_date="2026-08-06") for i in range(LIST_MAX)]
               + [story(id=100 + i, ref=100 + i) for i in range(30)])
    out = assemble(stories, viewer=None)
    assert len(out.live) == LIST_MAX
    assert all(i.due == "2026-08-06" for i in out.live)


# ------------------------------------------------------------------ order

def test_no_undated_task_can_outrank_a_deadline():
    newest = judged_rank(story(created_date="2026-08-05T09:00:00.000Z"),
                         today=TODAY, comment={"who": "Sami"},
                         viewer="goldavelez_org")
    assert newest < JUDGED_CEILING < CLOCK_FLOOR
    assert newest < clock_rank("2027-08-05", TODAY)


def test_a_new_task_ranks_above_a_stale_one():
    """Nobody has triaged it yet, which is its own kind of waiting."""
    fresh = judged_rank(story(created_date="2026-08-03T09:00:00.000Z"),
                        today=TODAY)
    stale = judged_rank(story(), today=TODAY)
    assert fresh > stale


def test_recently_touched_ranks_above_longer_untouched():
    """Golda 2026-08-11: fresh on top, and "I don't know why that old stuff is
    showing up". Time since anything happened counts against a task, not for
    it — the list is a worker's, not a nag's."""
    cold = judged_rank(story(modified_date="2026-01-20T09:00:00.000Z"),
                       today=TODAY)
    warm = judged_rank(story(modified_date="2026-08-01T09:00:00.000Z"),
                       today=TODAY)
    assert warm > cold


def test_the_fade_stops_so_old_work_sinks_rather_than_disappears():
    old = judged_rank(story(modified_date="2026-02-06T09:00:00.000Z"),
                      today=TODAY)
    ancient = judged_rank(story(modified_date="2019-02-06T09:00:00.000Z"),
                          today=TODAY)
    assert ancient == old > 0


def test_moved_off_the_first_column_ranks_up():
    """Somebody dragged it into to-do or in progress: that is a person saying
    they mean to do it (golda 2026-08-11)."""
    parked = judged_rank(story(), today=TODAY, column=0)
    started = judged_rank(story(), today=TODAY, column=3)
    assert started > parked


def test_an_unreadable_board_costs_a_story_nothing():
    """No board, no column, and position simply does not count."""
    assert judged_rank(story(), today=TODAY, column=None) == judged_rank(
        story(), today=TODAY, column=0)


def test_somebody_asking_you_something_ranks_it_up():
    asked = judged_rank(story(), today=TODAY, comment={"who": "Sami"},
                        viewer="goldavelez_org")
    quiet = judged_rank(story(), today=TODAY)
    assert asked > quiet


def test_your_own_last_comment_is_not_a_question_to_you():
    mine = judged_rank(story(), today=TODAY, comment={"who": "goldavelez_org"},
                       viewer="goldavelez_org")
    assert mine == judged_rank(story(), today=TODAY)


def test_an_owned_task_ranks_above_an_unowned_one():
    owned = judged_rank(story(), today=TODAY)
    unowned = judged_rank(story(assigned_to=None), today=TODAY)
    assert owned > unowned


def test_a_story_with_no_timestamps_still_ranks():
    """Read through a path that carries no dates, it must not fall off."""
    bare = judged_rank({"assigned_to": 7, "description": "x"})
    assert UNDATED_FLOOR <= bare < JUDGED_CEILING


# ------------------------------------------------------------------ why

def test_the_card_says_why_in_plain_words():
    assert judged_reason(story(), today=TODAY).label == \
        "no deadline, untouched 56 days"
    assert judged_reason(story(created_date="2026-08-04T09:00:00.000Z"),
                         today=TODAY).label == "new, no deadline"
    assert judged_reason(story(), today=TODAY, comment={"who": "Sami"},
                         viewer="goldavelez_org").label == "Sami asked, no deadline"


def test_an_undated_item_is_never_past():
    item = build_item(story(), project_slug="b", taiga_host=HOST, today=TODAY)
    assert item.due is None
    assert item.past is False
    assert item.reason.kind == "judgement"


def test_a_closed_story_never_appears_dated_or_not():
    out = assemble([story(status_extra_info={"is_closed": True})])
    assert out.live == [] and out.past == []


# ------------------------------------------------------------------ the cap

def test_the_cap_is_twenty():
    """Golda: never more than twenty, because it'll just get stale anyway."""
    from src.services.work_list import LIST_MAX, top
    assert LIST_MAX == 20
    many = [story(id=i, ref=i) for i in range(50)]
    items = assemble(many).live
    assert len(items) == 50            # everything is still scored
    assert len(top(items)) == 20       # only twenty reach the screen


def test_the_cap_keeps_the_top_of_the_order_not_an_arbitrary_slice():
    from src.services.work_list import top
    items = assemble([
        story(id=1, ref=1, modified_date="2026-08-04T09:00:00.000Z"),
        story(id=2, ref=2, modified_date="2026-01-20T09:00:00.000Z"),
    ]).live
    assert [i.subject for i in top(items, 1)] == ["taiga:some-board#1"]


def test_a_short_list_is_left_alone():
    from src.services.work_list import top
    items = assemble([story()]).live
    assert len(top(items)) == 1


# ------------------------------------- a full page of deadlines hides nothing

def _ranked(subject, rank):
    from src.services.work_list import Item, Reason
    kind = "clock" if rank >= 1000.0 else "judgement"
    return Item(subject=subject, title=subject,
                reason=Reason(label=subject, kind=kind), rank=rank)


def _sorted(items):
    return sorted(items, key=lambda i: (-i.rank, i.title))


def test_undated_rows_keep_slots_when_the_deadlines_would_fill_the_page():
    """A draft waiting on approval cannot be invisible because someone has
    twenty deadlines: no judged item may score into the clock band, so the
    plain top-twenty would drop every one of them with nothing on the page
    saying so."""
    from src.services.work_list import CLOCK_FLOOR, LIST_MIN_UNDATED, top
    dated = [_ranked(f"taiga:b#{i}", CLOCK_FLOOR + i) for i in range(30)]
    undated = [_ranked(f"draft:{i}", 900.0 - i) for i in range(8)]
    out = top(_sorted(dated + undated))

    assert len(out) == 20
    assert sum(1 for i in out if i.rank < CLOCK_FLOOR) == LIST_MIN_UNDATED
    # the ones that gave way are the deadlines furthest out, never the soonest
    assert out[0].rank == max(i.rank for i in dated)
    assert "taiga:b#0" not in [i.subject for i in out]


def test_the_reserve_is_not_a_quota_when_there_is_nothing_waiting():
    from src.services.work_list import CLOCK_FLOOR, top
    dated = [_ranked(f"taiga:b#{i}", CLOCK_FLOOR + i) for i in range(30)]
    out = top(_sorted(dated))
    assert len(out) == 20
    assert all(i.rank >= CLOCK_FLOOR for i in out)


def test_undated_rows_already_on_the_page_are_not_doubled():
    from src.services.work_list import CLOCK_FLOOR, top
    dated = [_ranked(f"taiga:b#{i}", CLOCK_FLOOR + i) for i in range(18)]
    undated = [_ranked(f"draft:{i}", 900.0 - i) for i in range(6)]
    out = top(_sorted(dated + undated))
    assert len(out) == 20
    assert len(set(i.subject for i in out)) == 20
    assert sum(1 for i in out if i.rank < CLOCK_FLOOR) == 5
