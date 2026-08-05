"""The CRM source: card kinds, the shared clock, and whose follow-up it is."""

from datetime import date

from src.services.work_list import (
    CLOCK_FLOOR, assemble_crm, build_crm_item, build_item, kind_of,
)

TODAY = date(2026, 7, 25)


def activity(**kw):
    base = {
        "id": 19, "res_model": "res.partner", "res_id": 8799,
        "res_name": "You.com / AIX Ventures, Richard Socher",
        "summary": "Share the paper with Richard Socher",
        "date_deadline": "2026-07-26",
        "user_id": [16, "Golda Velez"],
    }
    base.update(kw)
    return base


class FakeCrm:
    def __init__(self, messages=None):
        self._messages = messages or {}   # {(model, res_id): message}

    def last_messages(self, model, res_ids):
        return {rid: self._messages[(model, rid)]
                for rid in res_ids if (model, rid) in self._messages}


# ------------------------------------------------------------------ kinds

def test_kind_comes_off_the_subject():
    assert kind_of("taiga:some-board#34") == "task"
    assert kind_of("goal:abc-123") == "goal"
    assert kind_of("draft:9f2c") == "draft"
    assert kind_of("crm:activity/19") == "contact"


def test_unknown_scheme_reads_as_a_task():
    """A new source must show up as an ordinary row, never break the page."""
    assert kind_of("something-new:1") == "task"
    assert kind_of("no-scheme-at-all") == "task"


def test_item_reports_its_own_kind():
    story = {"id": 1, "ref": 34, "subject": "x", "description": "",
             "due_date": None}
    task = build_item(story, project_slug="b", taiga_host="https://m.example",
                      today=TODAY)
    assert task.kind == "task"
    assert build_crm_item(activity(), today=TODAY, record_url="u").kind == "contact"


# ------------------------------------------------------------------ one ladder

def test_crm_follow_up_ranks_on_the_same_clock_as_a_story():
    """The point of one list: a call due tomorrow sits beside a task due
    tomorrow, not in a section of its own."""
    story = {"id": 1, "ref": 34, "subject": "a task", "description": "",
             "due_date": "2026-07-26"}
    task = build_item(story, project_slug="b", taiga_host="https://m.example",
                      today=TODAY)
    call = build_crm_item(activity(date_deadline="2026-07-26"), today=TODAY,
                          record_url="u")
    assert call.rank == task.rank
    assert call.reason.label == task.reason.label == "tomorrow"
    assert call.reason.kind == "clock"


def test_undated_follow_up_cannot_outrank_a_dated_one():
    dated = build_crm_item(activity(), today=TODAY, record_url="u")
    undated = build_crm_item(activity(id=20, date_deadline=False), today=TODAY,
                             record_url="u")
    assert dated.rank >= CLOCK_FLOOR > undated.rank
    assert undated.reason.label == "no date"


def test_past_deadline_drops_out_of_live():
    result = assemble_crm([activity(date_deadline="2026-02-18")], FakeCrm(),
                          today=TODAY)
    assert result.live == []
    assert [i.title for i in result.past] == ["Share the paper with Richard Socher"]


# ------------------------------------------------------------------ whose

def test_filtered_to_the_viewer_by_id_not_name():
    """Two accounts in this CRM read 'Golda Velez'. Matching on the name would
    hand one person the other's follow-ups."""
    mine = activity(id=19, user_id=[16, "Golda Velez"])
    theirs = activity(id=15, user_id=[2, "Golda Velez"],
                      summary="someone else's follow-up")
    result = assemble_crm([mine, theirs], FakeCrm(), today=TODAY, viewer_uids=[16])
    assert [i.subject for i in result.live] == ["crm:activity/19"]


def test_unassigned_follow_up_is_on_everyones_list():
    """Nobody owns it, so it is waiting on whoever picks it up — same rule the
    board source uses."""
    loose = activity(id=21, user_id=False, summary="nobody owns this")
    result = assemble_crm([loose], FakeCrm(), today=TODAY, viewer_uids=[16])
    assert [i.title for i in result.live] == ["nobody owns this"]


def test_unmapped_viewer_sees_everything_not_nothing():
    result = assemble_crm([activity(id=19, user_id=[16, "G"]),
                           activity(id=15, user_id=[2, "G"])],
                          FakeCrm(), today=TODAY, viewer_uids=None)
    assert len(result.live) == 2


# ------------------------------------------------------------------ their words

def test_the_headline_is_what_a_person_said_on_the_record():
    crm = FakeCrm({("res.partner", 8799): {
        "who": "Richard Socher", "text": "send it over next week",
        "url": "https://crm.example/x"}})
    item = assemble_crm([activity()], crm, today=TODAY).live[0]
    assert item.quote.who == "Richard Socher"
    assert item.quote.text == "send it over next week"


def test_no_quote_when_nobody_said_anything():
    item = assemble_crm([activity()], FakeCrm(), today=TODAY).live[0]
    assert item.quote is None


def test_the_record_is_the_link():
    item = build_crm_item(activity(), today=TODAY,
                          record_url="https://crm.example/rec")
    assert [(l.label, l.url) for l in item.links] == [
        ("You.com / AIX Ventures, Richard Socher", "https://crm.example/rec")]
    assert not item.links[0].found


def test_a_broken_message_lookup_still_yields_rows():
    """A quote is a nicety. Losing it must not lose the follow-up."""
    class Broken:
        def last_messages(self, model, ids):
            raise RuntimeError("odoo down")

    result = assemble_crm([activity()], Broken(), today=TODAY)
    assert len(result.live) == 1
    assert result.live[0].quote is None


# ------------------------------------------------------------------ their words, cleaned

from src.services.work_list_crm import _clean, human_words  # noqa: E402

# The two shapes real chatter arrives in, from the CRM: what the mail poller
# stamps on a record, and the header block a forwarded mail carries with it.
FORWARDED = (
    "via email-poller · forwarded by gvelez17@gmail.com · original from "
    "jkitchens@credentialengine.org\n\n"
    "---------- Forwarded message ---------\n"
    "From: Jeanne Kitchens &lt;jkitchens@credentialengine.org&gt;\n"
    "Date: Thu, Jul 9, 2026, 11:07 AM\n"
    "Subject: Re: Semantic search follow-up?\n"
    "To: Golda Velez &lt;gvelez17@gmail.com&gt;\n\n"
    "Golda, our RFP is out"
)

WRAPPED_CC = (
    "via email-poller · forwarded by gvelez17@gmail.com · original from "
    "jkitchens@credentialengine.org\n\n"
    "---------- Forwarded message ---------\n"
    "From: Jeanne Kitchens\n"
    "Date: Thu, Jun 4, 2026 at 8:41 PM\n"
    "Subject: Re: Semantic search follow-up?\n"
    "To: Golda Velez\n"
    "Cc: Amos Mwangi\n,\nMuhammad Hany\n,\ngitonga miriam\n\n"
    "Golda, thank you for following up."
)


def test_amebos_own_stamp_never_becomes_the_headline():
    _who, text = human_words(_clean(FORWARDED))
    assert not text.startswith("via email-poller")
    assert "forwarded by" not in text


def test_the_words_are_attributed_to_who_wrote_them():
    """Not to whoever forwarded the mail into the CRM."""
    who, _text = human_words(_clean(FORWARDED))
    assert who == "Jeanne Kitchens"


def test_the_mail_header_block_is_not_the_message():
    _who, text = human_words(_clean(FORWARDED))
    assert text == "Golda, our RFP is out"


def test_a_wrapped_cc_list_is_still_header_not_message():
    """A long Cc: runs onto lines carrying no key. Those used to read as the
    start of the message, so the card opened with ', Muhammad Hany'."""
    who, text = human_words(_clean(WRAPPED_CC))
    assert who == "Jeanne Kitchens"
    assert text == "Golda, thank you for following up."


def test_plain_chatter_is_left_alone():
    who, text = human_words(_clean("<p>Spoke to her today, she's in.</p>"))
    assert who is None
    assert text == "Spoke to her today, she's in."


def test_line_structure_survives_and_entities_are_decoded():
    assert _clean("<p>one</p><p>two &amp; three</p>") == "one\ntwo & three"
