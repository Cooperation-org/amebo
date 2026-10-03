from src.personal.repl import _render


def test_bold_markers_removed():
    assert _render("**Trust.** sells *recognition*; x") == "Trust. sells recognition; x"


def test_non_bold_asterisks_kept():
    for t in ("2 * 3 * 4", "a*b*c", "* list item"):
        assert _render(t) == t
