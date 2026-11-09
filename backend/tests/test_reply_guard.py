from src.services.reply_guard import problem


def test_short_result_passes():
    assert problem("ClearDD removed from the partner list.\nhttps://elm.linkedtrust.us/partners?partner=642") is None


def test_too_long_fails():
    assert "characters" in problem("x" * 401)


def test_self_narration_fails():
    msg = "I removed the pitch. I added a correction. Done.\nhttps://example.org"
    assert "narrates" in problem(msg)


def test_apology_fails():
    assert "apologizes" in problem("My mistake: the doc says so.")


def test_what_i_did_fails():
    assert "process" in problem("*What I did:* read the board")


def test_link_counts_as_its_label():
    assert problem("Doc: <https://example.org/" + "a" * 500 + "|Brainstorm>") is None
