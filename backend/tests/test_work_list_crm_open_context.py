"""The CRM's open context: engaged opportunities nobody scheduled anything on.

The follow-up source only sees records where someone already chose a date. This
CRM has three of those and over a thousand open opportunities, so the rows that
matter — a conversation that was engaged and then went quiet — reached nobody's
list. These tests pin what earns a row, whose row it is, and where it ranks.
"""

from datetime import date

from src.services.work_list import (
    CLOCK_FLOOR, JUDGED_CEILING, OPEN_CONTEXT_FLOOR,
    assemble_crm_open_context, build_open_context_item, clock_rank, kind_of,
)

TODAY = date(2026, 7, 25)

# The CRM's real shape: 'Identified' is the first stage and is not here, because
# the ungroomed pipeline never earns a row.
STAGES = {6: "Reached Out", 7: "Connected"}
STAGE_RANK = {6: 0, 7: 1}


def lead(**kw):
    base = {
        "id": 46, "name": "share our contractor and cred capabilities",
        "user_id": [11, "Gitonga"], "stage_id": [6, "Reached Out"],
        "partner_id": [354, "Foundation for Talent Transformation"],
        "activity_ids": [], "date_last_stage_update": "2026-02-15 09:00:00",
        "expected_revenue": 0.0,
    }
    base.update(kw)
    return base


class FakeCrm:
    def __init__(self, messages=None):
        self._messages = messages or {}   # {(model, res_id): message}
        self.asked = []

    def last_messages(self, model, res_ids):
        self.asked.append((model, list(res_ids)))
        return {rid: self._messages[(model, rid)]
                for rid in res_ids if (model, rid) in self._messages}


# ------------------------------------------------------------------ the card

def test_an_engaged_opportunity_is_a_contact_card():
    item = build_open_context_item(lead(), today=TODAY, stage_rank=STAGE_RANK)
    assert kind_of(item.subject) == "contact"
    assert item.subject == "crm:lead/46"
    assert item.kind == "contact"


def test_the_card_says_why_in_plain_words():
    """A judged rank has to justify itself: how far along, and how long quiet."""
    item = build_open_context_item(lead(), today=TODAY, stage_rank=STAGE_RANK)
    assert item.reason.kind == "judgement"
    assert "reached out" in item.reason.label
    assert "nothing scheduled" in item.reason.label
    assert "160 days" in item.reason.label   # 2026-02-15 -> 2026-07-25


def test_the_card_links_to_the_record_by_the_contacts_name():
    item = build_open_context_item(lead(), today=TODAY, stage_rank=STAGE_RANK)
    assert item.links[0].label == "Foundation for Talent Transformation"
    assert "id=46" in item.links[0].url
    assert "model=crm.lead" in item.links[0].url


def test_an_undated_record_is_never_past():
    """Nothing here has a deadline, so nothing here can have missed one."""
    item = build_open_context_item(lead(), today=TODAY, stage_rank=STAGE_RANK)
    assert item.due is None
    assert item.past is False


def test_the_owner_is_named():
    item = build_open_context_item(lead(), today=TODAY, stage_rank=STAGE_RANK)
    assert item.assignee == "Gitonga"


# ------------------------------------------------------------------ ranking

def test_never_outranks_a_dated_row():
    """The whole point of the two bands: a real deadline always wins."""
    item = build_open_context_item(
        lead(date_last_stage_update="2020-01-01 00:00:00",
             stage_id=[7, "Connected"]),
        today=TODAY, stage_rank=STAGE_RANK)
    assert item.rank < JUDGED_CEILING
    assert item.rank < CLOCK_FLOOR
    # Even a year-out deadline beats the quietest, furthest-along record.
    assert item.rank < clock_rank("2027-07-25", TODAY)


def test_further_along_outranks_earlier():
    reached = build_open_context_item(lead(stage_id=[6, "Reached Out"]),
                                      today=TODAY, stage_rank=STAGE_RANK)
    connected = build_open_context_item(lead(stage_id=[7, "Connected"]),
                                        today=TODAY, stage_rank=STAGE_RANK)
    assert connected.rank > reached.rank


def test_longer_quiet_outranks_recent_within_a_stage():
    recent = build_open_context_item(
        lead(date_last_stage_update="2026-07-20 09:00:00"),
        today=TODAY, stage_rank=STAGE_RANK)
    cold = build_open_context_item(
        lead(date_last_stage_update="2026-03-03 09:00:00"),
        today=TODAY, stage_rank=STAGE_RANK)
    assert cold.rank > recent.rank


def test_quiet_stops_counting_after_six_months():
    """Past the cap, older is not more urgent — otherwise the oldest dead record
    in the CRM sits at the top of the list forever."""
    six = build_open_context_item(
        lead(date_last_stage_update="2026-01-26 09:00:00"),
        today=TODAY, stage_rank=STAGE_RANK)
    ancient = build_open_context_item(
        lead(date_last_stage_update="2019-01-01 09:00:00"),
        today=TODAY, stage_rank=STAGE_RANK)
    assert ancient.rank == six.rank


def test_a_record_with_no_stamp_still_ranks():
    item = build_open_context_item(lead(date_last_stage_update=False),
                                   today=TODAY, stage_rank=STAGE_RANK)
    assert item.rank >= OPEN_CONTEXT_FLOOR
    assert "nothing scheduled" in item.reason.label


# ------------------------------------------------------------------ whose

def test_filters_to_the_viewer_by_id():
    rows = [lead(id=46, user_id=[11, "Gitonga"]),
            lead(id=47, user_id=[16, "Golda Velez"])]
    mine = assemble_crm_open_context(rows, FakeCrm(), today=TODAY,
                                     viewer_uids=[16], stage_names=STAGES)
    assert [i.subject for i in mine] == ["crm:lead/47"]


def test_an_unowned_record_stays_on_every_list():
    """Nobody has picked it up, so it is waiting on whoever does — same rule the
    board source uses."""
    rows = [lead(id=48, user_id=False)]
    mine = assemble_crm_open_context(rows, FakeCrm(), today=TODAY,
                                     viewer_uids=[16], stage_names=STAGES)
    assert [i.subject for i in mine] == ["crm:lead/48"]


def test_no_mapped_viewer_filters_nothing():
    """Too much beats an empty page: a list that silently hid everything looks
    broken rather than tidy."""
    rows = [lead(id=46, user_id=[11, "Gitonga"]),
            lead(id=47, user_id=[16, "Golda Velez"])]
    mine = assemble_crm_open_context(rows, FakeCrm(), today=TODAY,
                                     viewer_uids=[], stage_names=STAGES)
    assert len(mine) == 2


# ------------------------------------------------------------------ the quote

def test_the_card_carries_the_persons_own_words():
    """A lead holds no chatter; what was said lives on the contact it hangs on."""
    crm = FakeCrm({("res.partner", 354): {
        "who": "Eric Shepherd", "text": "Happy to look at this next month.",
        "url": "https://crm.example/354"}})
    mine = assemble_crm_open_context([lead()], crm, today=TODAY,
                                     viewer_uids=[11], stage_names=STAGES)
    assert mine[0].quote.who == "Eric Shepherd"
    assert mine[0].quote.text == "Happy to look at this next month."
    assert crm.asked == [("res.partner", [354])]


def test_contacts_are_read_in_one_query_not_one_per_row():
    """A call per row is what makes a list feel slow."""
    crm = FakeCrm()
    rows = [lead(id=46, partner_id=[354, "A"]), lead(id=47, partner_id=[8943, "B"])]
    assemble_crm_open_context(rows, crm, today=TODAY, viewer_uids=[11],
                              stage_names=STAGES)
    assert crm.asked == [("res.partner", [354, 8943])]


def test_a_missing_quote_is_not_a_missing_row():
    mine = assemble_crm_open_context([lead()], FakeCrm(), today=TODAY,
                                     viewer_uids=[11], stage_names=STAGES)
    assert len(mine) == 1
    assert mine[0].quote is None


def test_a_crm_that_cannot_answer_still_yields_rows():
    class Broken:
        def last_messages(self, model, res_ids):
            raise RuntimeError("odoo down")

    mine = assemble_crm_open_context([lead()], Broken(), today=TODAY,
                                     viewer_uids=[11], stage_names=STAGES)
    assert [i.subject for i in mine] == ["crm:lead/46"]


def test_nothing_engaged_is_an_empty_list_not_an_error():
    assert assemble_crm_open_context([], FakeCrm(), today=TODAY,
                                     viewer_uids=[16], stage_names=STAGES) == []
