"""Compaction: counts only what is sent, folds the old summary in, and keeps
turns starting with a user turn."""

from src.services import conversation_manager as cm


class FakeRepo:
    def __init__(self, turns, summary=None, through=None):
        self.turns = turns
        self.thread = {"id": 1, "summary": summary, "summary_through_turn_id": through}
        self.updates = []

    def get_thread(self, _):
        return self.thread

    def get_turns(self, _, after_turn_id=None):
        return [t for t in self.turns if not after_turn_id or t["id"] > after_turn_id]

    def update_summary(self, _, summary, through):
        self.updates.append((summary, through))
        self.thread.update(summary=summary, summary_through_turn_id=through)


def _mgr(repo, seen):
    m = cm.ConversationManager.__new__(cm.ConversationManager)
    m._thread = {"id": 1}
    m._thread_repo = repo
    m._generate_summary = lambda text: seen.append(text) or "S"
    return m


def _turns(sizes):
    return [{"id": i + 1, "role": "user" if i % 2 == 0 else "assistant",
             "content": "x" * (n * cm.CHARS_PER_TOKEN), "token_estimate": n}
            for i, n in enumerate(sizes)]


def test_no_recompaction_once_under_threshold():
    turns = _turns([30_000, 1_000, 30_000, 1_000, 30_000, 1_000])
    repo, seen = FakeRepo(turns), []
    m = _mgr(repo, seen)
    m._maybe_compact()
    assert len(repo.updates) == 1
    m._maybe_compact()  # nothing new: what is sent is under threshold
    assert len(repo.updates) == 1


def test_kept_turns_start_with_user():
    # The token split alone would keep from the last assistant turn.
    turns = _turns([30_000, 30_000, 30_000, 25_000])
    repo, seen = FakeRepo(turns), []
    _mgr(repo, seen)._maybe_compact()
    through = repo.updates[0][1]
    kept = [t for t in turns if t["id"] > through]
    assert kept and kept[0]["role"] == "user"


def test_previous_summary_is_folded_in():
    turns = _turns([100, 100] + [30_000, 1_000] * 3)
    repo, seen = FakeRepo(turns, summary="P1 put in 1400 hours", through=2), []
    _mgr(repo, seen)._maybe_compact()
    assert "P1 put in 1400 hours" in seen[0]


def test_long_turn_keeps_head_and_tail():
    text = "HEAD" + "x" * 100_000 + "TAIL"
    clipped = cm._clip(text)
    assert clipped.startswith("HEAD") and clipped.endswith("TAIL")
    assert len(clipped) < 30_000
