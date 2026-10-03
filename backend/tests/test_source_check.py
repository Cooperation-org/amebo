from src.services.source_check import unopened_domains, mark_unopened


def test_lists_sites_no_tool_returned():
    answer = "Boast charges $99 (boast.io). See https://www.trustpilot.com/x and linkedtrust.us"
    assert unopened_domains(answer, ["URL: https://linkedtrust.us/"]) == ["boast.io", "trustpilot.com"]


def test_files_and_emails_are_not_sites():
    assert unopened_domains("edit MAIN.md and app.py, mail a@b.com", []) == []


def test_answer_unchanged_when_everything_was_opened():
    assert mark_unopened("see example.com", ["URL: https://example.com/"]) == "see example.com"


def test_adds_one_line_naming_unopened_sites():
    assert mark_unopened("see boast.io", []).endswith("\n\nNot opened for this answer: boast.io")


def test_any_site_ending_counts():
    assert unopened_domains("Testimonial.to and senja.io; built on Node.js", []) == ["testimonial.to", "senja.io"]
