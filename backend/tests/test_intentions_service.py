"""Unit tests for intentions_service. No DB, no Anthropic — exercises
the prompt/parse/proposal machinery in isolation.

The commit() path requires a real abra connection and is exercised via
the live route end-to-end, not here.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.intentions_service import (
    IntentionsService,
    Proposal,
    _build_user_message,
)


def _service_no_llm():
    """Service without an Anthropic client (mock-fallback path)."""
    s = IntentionsService.__new__(IntentionsService)
    s.client = None
    return s


# ── prompt builder ────────────────────────────────────────────────────────

def test_build_user_message_includes_scope_and_text():
    msg = _build_user_message("write the spec", "golda", [], None)
    assert "Scope: golda" in msg
    assert "write the spec" in msg
    assert "name_is_new" not in msg  # name_is_new is part of model output, not input


def test_build_user_message_includes_name_hint_in_extend_mode():
    msg = _build_user_message("add the PR url", "golda", [], "untp-2026")
    assert "Extending existing name: untp-2026" in msg
    assert "name_is_new must be false" in msg


def test_build_user_message_lists_existing_names_when_provided():
    existing = ["leanne-ussher", "untp-2026", "peter"]
    msg = _build_user_message("note about peter", "golda", existing, None)
    for n in existing:
        assert n in msg


def test_build_user_message_caps_existing_names_at_60():
    huge = [f"name-{i}" for i in range(120)]
    msg = _build_user_message("any text", "golda", huge, None)
    # the first 60 are present, beyond is not guaranteed
    assert "name-0" in msg
    assert "name-59" in msg
    assert "name-60" not in msg


# ── mock proposal (no Anthropic key) ──────────────────────────────────────

def test_mock_proposal_fresh_uses_slug_from_text():
    s = _service_no_llm()
    p = s.propose("Set up a UN transparency tracker for our PR", scope="golda")
    assert p.name == "set-up-a"
    assert p.name_is_new is True
    assert p.scope == "golda"
    assert p.content_summary.startswith("Set up a UN")
    assert p.make_clawable is False  # mock never auto-marks clawable
    assert p.cron is None


def test_mock_proposal_extend_mode_uses_hint():
    s = _service_no_llm()
    p = s.propose("here's the spec URL", scope="golda", name="untp-2026")
    assert p.name == "untp-2026"
    assert p.name_is_new is False


def test_propose_empty_text_raises():
    s = _service_no_llm()
    with pytest.raises(ValueError):
        s.propose("", scope="golda")
    with pytest.raises(ValueError):
        s.propose("   ", scope="golda")


# ── proposal JSON parsing ─────────────────────────────────────────────────

def test_parse_proposal_clean_json():
    s = _service_no_llm()
    raw = json.dumps({
        "name": "untp-2026",
        "name_is_new": True,
        "content_summary": "Get comments on UN transparency spec.",
        "labels": ["goal", "hot"],
        "make_clawable": True,
        "cron": "0 9 * * 1",
        "title": "UN transparency advocacy",
        "description": "Drive comments to the PR.",
        "reasoning": "User wants amebo to watch the PR weekly.",
    })
    p = s._parse_proposal(raw, "Get comments on UN transparency spec.", "golda", None)
    assert p.name == "untp-2026"
    assert p.name_is_new is True
    assert p.labels == ["goal", "hot"]
    assert p.make_clawable is True
    assert p.cron == "0 9 * * 1"
    assert p.title == "UN transparency advocacy"


def test_parse_proposal_tolerates_markdown_fences():
    s = _service_no_llm()
    raw = "Sure, here you go:\n```json\n" + json.dumps({
        "name": "x",
        "name_is_new": True,
        "content_summary": "hi",
        "labels": [],
        "make_clawable": False,
    }) + "\n```\n\nLet me know if you want changes."
    p = s._parse_proposal(raw, "hi", "golda", None)
    assert p.name == "x"
    assert p.labels == []
    assert p.make_clawable is False


def test_parse_proposal_falls_back_to_mock_on_garbage():
    s = _service_no_llm()
    p = s._parse_proposal("not json at all", "the original text", "golda", None)
    assert p.scope == "golda"
    assert p.content_summary == "the original text"
    # mock leaves clawable false
    assert p.make_clawable is False


def test_parse_proposal_filters_empty_labels():
    s = _service_no_llm()
    raw = json.dumps({
        "name": "x",
        "name_is_new": True,
        "content_summary": "y",
        "labels": ["goal", "", "  ", "hot"],
        "make_clawable": False,
    })
    p = s._parse_proposal(raw, "y", "golda", None)
    assert p.labels == ["goal", "hot"]


def test_parse_proposal_clawable_with_empty_cron_is_manual():
    s = _service_no_llm()
    raw = json.dumps({
        "name": "x",
        "name_is_new": True,
        "content_summary": "y",
        "labels": [],
        "make_clawable": True,
        "cron": "",
        "title": "t",
        "description": "d",
    })
    p = s._parse_proposal(raw, "y", "golda", None)
    assert p.make_clawable is True
    assert p.cron is None


# ── Proposal dataclass shape ──────────────────────────────────────────────

def test_proposal_to_dict_roundtrip():
    p = Proposal(
        scope="golda", name="x", name_is_new=True,
        content_summary="hi", labels=["goal"],
        make_clawable=True, cron="0 9 * * 1",
        title="T", description="D", reasoning="R",
    )
    d = p.to_dict()
    assert d["scope"] == "golda"
    assert d["name"] == "x"
    assert d["make_clawable"] is True
    assert d["labels"] == ["goal"]
    assert set(d.keys()) == {
        "scope", "name", "name_is_new", "content_summary", "labels",
        "make_clawable", "cron", "title", "description", "reasoning",
    }
