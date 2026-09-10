"""Slack from amebo: only when a person must act or it matters to a person,
two sentences and a link, never about its own work (golda 2026-09-10)."""
from src.services.human_output_gate import two_sentences_and_a_link, HumanOutputGate, Disposition
from src.services.goal_dispatcher import _human_need
from src.tools.slack_tools import _more_than_two_sentences


def test_a_finished_run_is_silent_unless_it_names_a_need():
    assert _human_need("Found 11 channels, recorded in CRM. [loop stats]") is None
    assert _human_need("Summary.\n**Blocker:** x\nNEEDS: a human to fix campaign_link.\nmore") \
        == "NEEDS: a human to fix campaign_link."
    assert _human_need("- needs: your ok on the code, story 20") == "NEEDS: your ok on the code, story 20"


def test_cold_message_is_two_sentences_and_a_link():
    long = ("<@U1> *Level Up — channels found this run*\n\n"
            "- NC Center — https://a.org — free\n- NJ Center — https://b.org\n- Eventbrite https://c.org")
    assert two_sentences_and_a_link(long) == "<@U1> Level Up — channels found this run (3 items, on the record) https://a.org"
    prose = "First thing happened. Second thing too. Third is dropped. https://x.org/1 https://x.org/2"
    assert two_sentences_and_a_link(prose) == "First thing happened. Second thing too. https://x.org/1"
    assert two_sentences_and_a_link("NEEDS: your ok. https://m/board?story=20") == "NEEDS: your ok. https://m/board?story=20"


def test_gate_applies_it_to_cold_posts():
    g = HumanOutputGate()
    d = g.gate("One. Two. Three. Four.", channel="slack:#x")
    assert d.disposition is Disposition.SEND
    assert d.text == "One. Two."


def test_slack_tool_refuses_lists_and_essays():
    assert _more_than_two_sentences("<@U1> Story 20 needs your ok on the code. https://m/board?story=20") == ""
    assert _more_than_two_sentences("Found 11 channels.\n- a\n- b\n- c") == "a list of 3 items"
    assert _more_than_two_sentences("A. B. C.") == "3 sentences"
    assert _more_than_two_sentences("See https://a.org and https://b.org") == "2 links"
