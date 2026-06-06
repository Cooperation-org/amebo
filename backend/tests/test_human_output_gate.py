"""
Unit tests for the human-output gate (the message gate).

Pure Python — no real Slack, no DB. A fake crystallizer is injected so ordering
and batching are asserted without a model, and the module's ``_now`` seam is
monkeypatched so rate-window / dedup-lookback timing is deterministic.

Covered (per spec):
  - rate-limit: past the threshold a non-urgent message DEFERs (not SEND).
  - thread preference: a running thread forces a message into the thread, and a
    thread reply does not count toward the rate limit.
  - duplicate → SUPPRESS.
  - non-urgent deferred items flushed at the daily stand-up = ONE message
    covering MULTIPLE goals.
  - urgent bypasses batching but STILL crystallizes + dedups.
  - config overrides respected.
  - GC: idle channels evicted; a channel with a queued stand-up is never evicted;
    the GcPolicy adapter satisfies the state_decay protocol and runs via run_gc.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.services import human_output_gate as hog
from src.services.human_output_gate import (
    Disposition,
    HumanOutputGate,
    OutputGateConfig,
    OutputGateGcPolicy,
    register_output_gate_gc,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class FakeClock:
    """Monkeypatches hog._now so time advances only when we say so."""

    def __init__(self, start: float = 1_000_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class RecordingCrystallizer:
    """Fake crystallizer: records every call and returns a deterministic,
    inspectable join so tests can assert what got batched and whether the
    thread flag was set. Does NOT trim (so 'multiple goals' is visible)."""

    def __init__(self):
        self.calls: list[dict] = []

    def crystallize(self, items, *, in_thread, receiver=None):
        self.calls.append(
            {"items": list(items), "in_thread": in_thread, "receiver": receiver}
        )
        return " || ".join(i.strip() for i in items if i and i.strip())


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(hog, "_now", c)
    return c


@pytest.fixture
def crystal():
    return RecordingCrystallizer()


# --------------------------------------------------------------------------- #
# Rate limit
# --------------------------------------------------------------------------- #


def test_rate_limit_defers_past_threshold(clock, crystal):
    cfg = OutputGateConfig(
        max_msgs_per_channel=3, rate_window=timedelta(hours=1),
        dedup_lookback=timedelta(0),  # disable dedup so distinct sends count
    )
    gate = HumanOutputGate(config=cfg, crystallizer=crystal)

    # First 3 distinct top-level messages SEND.
    for i in range(3):
        d = gate.gate(f"update {i}", channel="#ops")
        assert d.disposition is Disposition.SEND, f"msg {i} should send"

    # 4th non-urgent in the same window is DEFERRED, not sent.
    d4 = gate.gate("update 3", channel="#ops")
    assert d4.disposition is Disposition.DEFER
    assert gate.pending_digest_count("#ops") == 1

    # After the window passes, top-level sends are allowed again.
    clock.advance(timedelta(hours=1, seconds=1).total_seconds())
    d5 = gate.gate("update later", channel="#ops")
    assert d5.disposition is Disposition.SEND


def test_per_channel_isolation(clock, crystal):
    cfg = OutputGateConfig(max_msgs_per_channel=1, dedup_lookback=timedelta(0))
    gate = HumanOutputGate(config=cfg, crystallizer=crystal)

    assert gate.gate("a", channel="#one").disposition is Disposition.SEND
    # #one is now at limit, but #two is independent.
    assert gate.gate("b", channel="#one").disposition is Disposition.DEFER
    assert gate.gate("c", channel="#two").disposition is Disposition.SEND


# --------------------------------------------------------------------------- #
# Thread preference
# --------------------------------------------------------------------------- #


def test_thread_preference_forces_into_running_thread(clock, crystal):
    cfg = OutputGateConfig(max_msgs_per_channel=1, dedup_lookback=timedelta(0))
    gate = HumanOutputGate(config=cfg, crystallizer=crystal)

    # A reply that supplies a thread_ts adopts it as the channel's running
    # thread, and (being a thread reply) does NOT consume the rate budget.
    d1 = gate.gate("in thread", channel="#c", thread_ts="111.222")
    assert d1.disposition is Disposition.SEND
    assert d1.thread_ts == "111.222"
    assert crystal.calls[-1]["in_thread"] is True

    # A later message with NO thread_ts is forced into the running thread,
    # rather than posting a new top-level message.
    d2 = gate.gate("follow up", channel="#c")
    assert d2.disposition is Disposition.SEND
    assert d2.thread_ts == "111.222"

    # Neither counted toward the (size-1) rate limit, because both were threaded.
    d3 = gate.gate("third", channel="#c")
    assert d3.disposition is Disposition.SEND
    assert d3.thread_ts == "111.222"


def test_top_level_consumes_budget_thread_reply_does_not(clock, crystal):
    cfg = OutputGateConfig(max_msgs_per_channel=1, dedup_lookback=timedelta(0))
    gate = HumanOutputGate(config=cfg, crystallizer=crystal)

    # One top-level send uses the whole budget.
    assert gate.gate("top", channel="#x").disposition is Disposition.SEND
    # Next top-level is over-rate → DEFER.
    assert gate.gate("top2", channel="#x").disposition is Disposition.DEFER
    # But an explicit thread reply still goes (threads are preferred/cheap).
    d = gate.gate("reply", channel="#x", thread_ts="9.9")
    assert d.disposition is Disposition.SEND


# --------------------------------------------------------------------------- #
# Dedup
# --------------------------------------------------------------------------- #


def test_duplicate_is_suppressed(clock, crystal):
    gate = HumanOutputGate(
        config=OutputGateConfig(dedup_lookback=timedelta(hours=24)),
        crystallizer=crystal,
    )
    assert gate.gate("the same thing", channel="#d").disposition is Disposition.SEND
    # Exact repeat, and a whitespace/case variant, both suppressed.
    assert gate.gate("the same thing", channel="#d").disposition is Disposition.SUPPRESS
    assert gate.gate("  THE   Same   Thing ", channel="#d").disposition is Disposition.SUPPRESS

    # After the dedup lookback passes, it may send again.
    clock.advance(timedelta(hours=24, seconds=1).total_seconds())
    assert gate.gate("the same thing", channel="#d").disposition is Disposition.SEND


# --------------------------------------------------------------------------- #
# Daily stand-up: many goals collapse into ONE message
# --------------------------------------------------------------------------- #


def test_daily_standup_collapses_many_goals_into_one_message(clock, crystal):
    # Force everything to defer (rate limit 0) so we accumulate a digest.
    cfg = OutputGateConfig(max_msgs_per_channel=0, dedup_lookback=timedelta(0))
    gate = HumanOutputGate(config=cfg, crystallizer=crystal)

    gate.gate("goal A progressed", channel="#standup", goal_id="A")
    gate.gate("goal B blocked", channel="#standup", goal_id="B")
    gate.gate("goal C done", channel="#standup", goal_id="C")
    assert gate.pending_digest_count("#standup") == 3

    sent: list[tuple] = []

    def sender(channel, text, thread_ts):
        sent.append((channel, text, thread_ts))
        return True

    decision = gate.flush_daily_digest("#standup", sender=sender)

    # Exactly ONE message went out...
    assert len(sent) == 1
    assert decision is not None and decision.disposition is Disposition.SEND
    # ...and it covers all three goals.
    one_text = sent[0][1]
    assert "goal A progressed" in one_text
    assert "goal B blocked" in one_text
    assert "goal C done" in one_text
    assert "3 goals" in decision.reason
    # Queue is cleared after the flush.
    assert gate.pending_digest_count("#standup") == 0
    # Flushing an empty queue is a no-op.
    assert gate.flush_daily_digest("#standup", sender=sender) is None
    assert len(sent) == 1


def test_is_standup_hour_respects_config():
    gate = HumanOutputGate(config=OutputGateConfig(daily_standup_hour=14))
    assert gate.is_standup_hour(14) is True
    assert gate.is_standup_hour(9) is False


# --------------------------------------------------------------------------- #
# Urgent: bypass batching, still crystallize + dedup
# --------------------------------------------------------------------------- #


def test_urgent_bypasses_batching_but_still_dedups_and_crystallizes(clock, crystal):
    # Rate limit 0 → every non-urgent message defers.
    cfg = OutputGateConfig(max_msgs_per_channel=0, dedup_lookback=timedelta(hours=1))
    gate = HumanOutputGate(config=cfg, crystallizer=crystal)

    # Non-urgent defers...
    assert gate.gate("routine", channel="#alarm").disposition is Disposition.DEFER
    # ...but urgent SENDS now despite the rate limit.
    d = gate.gate("fire", channel="#alarm", urgency="urgent")
    assert d.disposition is Disposition.SEND
    # It was still crystallized (the fake crystallizer recorded the call).
    assert crystal.calls[-1]["items"] == ["fire"]
    # And urgent still dedups: an immediate identical urgent repeat is suppressed.
    d2 = gate.gate("fire", channel="#alarm", urgency="urgent")
    assert d2.disposition is Disposition.SUPPRESS


# --------------------------------------------------------------------------- #
# Config overrides
# --------------------------------------------------------------------------- #


def test_config_overrides_respected(clock, crystal):
    cfg = OutputGateConfig(
        max_msgs_per_channel=10,
        rate_window=timedelta(minutes=30),
        daily_standup_hour=6,
        dedup_lookback=timedelta(minutes=5),
        state_ttl=timedelta(hours=2),
    )
    gate = HumanOutputGate(config=cfg, crystallizer=crystal)
    assert gate.config.max_msgs_per_channel == 10
    assert gate.config.daily_standup_hour == 6

    # 10 distinct top-level messages all send under the raised limit.
    for i in range(10):
        assert gate.gate(f"m{i}", channel="#k").disposition is Disposition.SEND
    assert gate.gate("m10", channel="#k").disposition is Disposition.DEFER


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        OutputGateConfig(daily_standup_hour=99)
    with pytest.raises(ValueError):
        OutputGateConfig(rate_window=timedelta(0))
    with pytest.raises(ValueError):
        # state_ttl shorter than the dedup lookback is rejected.
        OutputGateConfig(
            dedup_lookback=timedelta(hours=48), state_ttl=timedelta(hours=1)
        )


def test_empty_message_suppressed(clock, crystal):
    gate = HumanOutputGate(crystallizer=crystal)
    assert gate.gate("   ", channel="#z").disposition is Disposition.SUPPRESS


# --------------------------------------------------------------------------- #
# GC integration
# --------------------------------------------------------------------------- #


def test_gc_evicts_idle_channels_but_not_pending_standup(clock, crystal):
    cfg = OutputGateConfig(
        max_msgs_per_channel=5,
        dedup_lookback=timedelta(hours=1),
        rate_window=timedelta(hours=1),
        state_ttl=timedelta(hours=1),
    )
    gate = HumanOutputGate(config=cfg, crystallizer=crystal)

    gate.gate("hi", channel="#idle")          # will go idle
    # A channel forced to defer so it has a queued stand-up.
    deferring = HumanOutputGate(
        config=OutputGateConfig(max_msgs_per_channel=0, dedup_lookback=timedelta(0)),
        crystallizer=crystal,
    )
    deferring.gate("queued", channel="#busy")
    assert deferring.pending_digest_count("#busy") == 1

    # Advance past TTL; idle channel state has aged out.
    clock.advance(timedelta(hours=2).total_seconds())
    evicted = gate.gc_idle_channels()
    assert "#idle" in evicted

    # The channel with a queued stand-up is never evicted, even when stale.
    evicted2 = deferring.gc_idle_channels()
    assert "#busy" not in evicted2
    assert deferring.pending_digest_count("#busy") == 1


def test_gc_policy_satisfies_protocol_and_runs_via_run_gc(clock, crystal):
    from src.services.state_decay.policy import GcPolicy, StoreRegistry
    from src.services.state_decay.runner import run_gc

    cfg = OutputGateConfig(
        dedup_lookback=timedelta(hours=1),
        rate_window=timedelta(hours=1),
        state_ttl=timedelta(hours=1),
    )
    gate = HumanOutputGate(config=cfg, crystallizer=crystal)
    policy = OutputGateGcPolicy(gate)
    assert isinstance(policy, GcPolicy)  # runtime_checkable protocol

    gate.gate("hi", channel="#gc")
    clock.advance(timedelta(hours=2).total_seconds())

    reg = StoreRegistry()
    reg.register(policy)
    reports = run_gc(registry=reg)
    assert len(reports) == 1
    assert reports[0].store == "output_gate"
    assert "#gc" in reports[0].expired_ids


def test_register_output_gate_gc_uses_isolated_registry(crystal):
    from src.services.state_decay.policy import StoreRegistry

    gate = HumanOutputGate(crystallizer=crystal)
    reg = StoreRegistry()
    register_output_gate_gc(gate, registry=reg)
    assert "output_gate" in reg.names()
    # Idempotent: registering again does not raise.
    register_output_gate_gc(gate, registry=reg)
    assert reg.names().count("output_gate") == 1
