"""Personal code-mode file tools: relative to cwd, changes go through confirm_edit."""
from __future__ import annotations
from src.tools.file_tools import read_file_impl, edit_file_impl, write_file_impl


def test_read_relative_to_cwd(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    out = read_file_impl({"path": "a.txt"}, {"cwd": str(tmp_path)})
    assert "1\tone" in out and "2\ttwo" in out


def test_edit_refused_without_confirm(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello")
    out = edit_file_impl({"path": str(f), "old_string": "hello", "new_string": "bye"}, {})
    assert "Refused" in out and f.read_text() == "hello"


def test_edit_declined(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello")
    out = edit_file_impl({"path": str(f), "old_string": "hello", "new_string": "bye"},
                         {"confirm_edit": lambda p, d: False})
    assert "Declined" in out and f.read_text() == "hello"


def test_edit_applies_and_shows_diff(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello\n")
    seen = {}
    out = edit_file_impl({"path": "a.txt", "old_string": "hello", "new_string": "bye"},
                         {"cwd": str(tmp_path), "confirm_edit": lambda p, d: seen.setdefault("d", d) or True})
    assert out.startswith("Edited") and f.read_text() == "bye\n"
    assert "-hello" in seen["d"] and "+bye" in seen["d"]


def test_edit_ambiguous(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x x")
    out = edit_file_impl({"path": str(f), "old_string": "x", "new_string": "y"},
                         {"confirm_edit": lambda p, d: True})
    assert "2 times" in out and f.read_text() == "x x"


def test_write_new_file(tmp_path):
    out = write_file_impl({"path": "n.txt", "content": "hi"},
                          {"cwd": str(tmp_path), "confirm_edit": lambda p, d: True})
    assert out.startswith("Wrote") and (tmp_path / "n.txt").read_text() == "hi"
