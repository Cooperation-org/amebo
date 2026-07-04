"""WP11: goal context carryover — a dispatch is briefed with progress from prior
dispatches' goal_events, framed as notes to RE-VERIFY (I1), and each dispatch
writes a closing dispatch_summary."""

from __future__ import annotations

from src.services.goal_dispatcher import GoalDispatcher


class _FakeRepo:
    def __init__(self, events):
        self._events = events
        self.appended = []

    def list_events(self, goal_id, limit=500):
        return self._events

    def append_event(self, **kw):
        self.appended.append(kw)


def _dispatcher(events):
    return GoalDispatcher(goal_repo=_FakeRepo(events))


class TestCarryover:
    def test_brief_empty_without_events(self):
        assert _dispatcher([])._carryover_brief("g1") == ""
        assert _dispatcher([])._carryover_brief(None) == ""

    def test_brief_has_recent_and_reverify_warning(self):
        events = [
            {"action": "created", "result_summary": ""},
            {"action": "tool_call:taiga_list", "result_summary": "found 3 open tasks"},
            {"action": "dispatch_summary", "result_summary": "drafted a follow-up to Alice"},
        ]
        brief = _dispatcher(events)._carryover_brief("g1")
        assert "drafted a follow-up to Alice" in brief
        assert "stale" in brief.lower() or "re-check" in brief.lower()
        # 'created'/'activated' are filtered out of the brief
        assert "created" not in brief

    def test_older_events_compressed_recent_verbatim(self):
        events = [{"action": f"tool_call:t{i}", "result_summary": f"summary-{i}"}
                  for i in range(15)]
        brief = _dispatcher(events)._carryover_brief("g1", recent=3, max_older=20)
        assert "Recent:" in brief and "Earlier (compressed):" in brief
        assert "summary-14" in brief          # most recent, verbatim

    def test_build_user_prompt_appends_brief(self):
        events = [{"action": "dispatch_summary", "result_summary": "prior progress note"}]
        prompt = _dispatcher(events)._build_user_prompt(
            {"id": "g1", "title": "Do X", "description": "the desc"})
        assert "Do X" in prompt and "prior progress note" in prompt

    def test_carryover_survives_repo_error(self):
        class Boom:
            def list_events(self, *a, **k):
                raise RuntimeError("db down")
        d = GoalDispatcher(goal_repo=Boom())
        assert d._carryover_brief("g1") == ""   # degrades, never raises
