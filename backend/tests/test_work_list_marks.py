"""Pin and bury: the person overruling the ranking.

The list caps at twenty rows, so ranking can drop something the reader decided
matters. Golda 2026-08-05: "either it should always be in the top twenty list,
or right now it shouldn't be, but maybe in the future it might again." These
tests pin what each gesture means and, most of all, that neither one can lose a
row.
"""

from datetime import date

from src.services.work_list import (
    Item, LIST_MAX, MarkedList, Reason, apply_marks, top, wakes_from_burial,
)

TODAY = date(2026, 8, 5)


def item(subject, rank=500.0, due=None):
    return Item(subject=subject, title=subject, rank=rank, due=due,
                reason=Reason("because", "judgement"))


# ------------------------------------------------------------------ pinning

def test_a_pin_lifts_the_row_out_of_the_ranked_list():
    out = apply_marks([item("a"), item("b")], {"b": "pinned"}, today=TODAY)
    assert [i.subject for i in out.pinned] == ["b"]
    assert [i.subject for i in out.live] == ["a"]


def test_a_pin_survives_being_ranked_last():
    """The whole point: a pin the ranking can outvote is not a pin."""
    rows = [item(f"n{i}", rank=900.0 - i) for i in range(40)]
    rows.append(item("mine", rank=1.0))
    out = apply_marks(rows, {"mine": "pinned"}, today=TODAY)
    assert [i.subject for i in out.pinned] == ["mine"]
    assert "mine" not in [i.subject for i in top(out.live)]


def test_pinning_does_not_spend_the_twenty():
    """Pinning three things must not cost three of the twenty."""
    rows = [item(f"n{i}", rank=900.0 - i) for i in range(40)]
    out = apply_marks(rows, {"n0": "pinned", "n1": "pinned", "n2": "pinned"},
                      today=TODAY)
    assert len(out.pinned) == 3
    assert len(top(out.live)) == LIST_MAX


def test_pins_keep_the_order_they_were_pinned_in():
    """Their choice, not ours: oldest pin first, whatever the ranks say."""
    rows = [item("a", rank=10.0), item("b", rank=900.0)]
    out = apply_marks(rows, {"b": "pinned", "a": "pinned"}, today=TODAY)
    assert [i.subject for i in out.pinned] == ["b", "a"]


# ------------------------------------------------------------------ burying

def test_burying_takes_a_row_out_of_the_list():
    out = apply_marks([item("a"), item("b")], {"b": "buried"}, today=TODAY)
    assert [i.subject for i in out.live] == ["a"]
    assert [i.subject for i in out.buried] == ["b"]


def test_a_buried_row_is_not_deleted():
    """Not forever, and not hidden. A row the person can never find again is a
    row they lost."""
    out = apply_marks([item("a")], {"a": "buried"}, today=TODAY)
    assert out.live == []
    assert [i.subject for i in out.buried] == ["a"]


def test_a_deadline_coming_due_digs_it_back_up():
    """Burying is 'not now', not 'never'. The future arriving is the one thing a
    person cannot be assumed to have meant to hide from."""
    out = apply_marks([item("a", due="2026-08-06")], {"a": "buried"}, today=TODAY)
    assert [i.subject for i in out.live] == ["a"]
    assert out.buried == []


def test_a_far_off_deadline_stays_buried():
    out = apply_marks([item("a", due="2026-12-01")], {"a": "buried"}, today=TODAY)
    assert [i.subject for i in out.buried] == ["a"]


def test_an_overdue_buried_row_comes_back():
    out = apply_marks([item("a", due="2026-07-01")], {"a": "buried"}, today=TODAY)
    assert [i.subject for i in out.live] == ["a"]


def test_wakes_only_on_a_real_date():
    assert wakes_from_burial(item("a"), TODAY) is False
    assert wakes_from_burial(item("a", due="not-a-date"), TODAY) is False
    assert wakes_from_burial(item("a", due="2026-08-05"), TODAY) is True


# ------------------------------------------------------------------ neither

def test_no_marks_changes_nothing():
    rows = [item("a"), item("b")]
    out = apply_marks(rows, {}, today=TODAY)
    assert [i.subject for i in out.live] == ["a", "b"]
    assert out.pinned == [] and out.buried == []


def test_a_mark_on_something_not_on_the_list_is_harmless():
    """Marks outlive rows: a task can close, or move to somebody else."""
    out = apply_marks([item("a")], {"gone": "pinned"}, today=TODAY)
    assert [i.subject for i in out.live] == ["a"]
    assert out.pinned == []


def test_nothing_is_ever_dropped_by_marking():
    rows = [item("a"), item("b", due="2026-12-01"), item("c")]
    out = apply_marks(rows, {"a": "pinned", "b": "buried"}, today=TODAY)
    seen = {i.subject for i in [*out.pinned, *out.live, *out.buried]}
    assert seen == {"a", "b", "c"}
    assert isinstance(out, MarkedList)
