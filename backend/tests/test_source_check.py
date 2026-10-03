from src.services.source_check import Sources, domains, finish, next_tag_number


def test_domains_skip_files_and_emails():
    assert domains("see boast.io, Testimonial.to, MAIN.md, app.py, Node.js, a@b.com") == ["boast.io", "testimonial.to"]


def test_cited_tag_must_exist():
    s = Sources()
    s.add("https://linkedtrust.us", "URL: https://linkedtrust.us/ Deep tech")
    assert s.problems("Deep tech [S1]") == []
    assert s.problems("Deep tech [S2]") == ["[S2] does not exist"]


def test_site_must_be_opened_or_written_by_person():
    s = Sources(known="earlier.com my question about senja.io")
    assert s.problems("senja.io and earlier.com") == []
    assert s.problems("boast.io") == ["boast.io was not opened"]


def test_check_words_with_no_tool_fail():
    assert Sources().problems("Verified against their pricing.") == ['says "Verified" but no tool ran']


def test_failing_answer_is_retried_then_shown_with_sources():
    s = Sources()
    s.add("https://linkedtrust.us", "linkedtrust.us Deep tech")
    out = finish("Boast is $99 (boast.io).", s, lambda fix: "LinkedTrust: deep tech [S1].")
    assert out == "LinkedTrust: deep tech [S1].\n\n[S1] https://linkedtrust.us"


def test_still_failing_sentences_are_removed():
    out = finish("Good line. Boast is $99 on boast.io.", Sources(), lambda fix: "Good line. Boast is $99 on boast.io.")
    assert out == "Good line."


def test_numbering_continues_after_history():
    assert next_tag_number([{"content": "x [S4] y"}, {"content": [{"content": "[S7] z"}]}]) == 8


def test_failed_fetch_is_not_a_source():
    s = Sources()
    s.add("https://trustpilot.com", "URL: https://trustpilot.com/\nStatus: 403\n\nVerifying your connection")
    s.add("x", "Error: request timed out after 10s.")
    assert s.items == []
    assert s.problems("trustpilot.com charges $99") == ["trustpilot.com was not opened"]
