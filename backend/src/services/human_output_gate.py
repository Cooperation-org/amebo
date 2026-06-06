"""
Human-output gate — the message gate for the claw.

Strategic purpose (see docs/OUTPUT_GATE.md and docs/CRYSTALLIZE.md): Amebo can
be "so noisy" in Slack. This is the guard that sits BEFORE Amebo emits a
human-facing message and enforces that the claw behaves like a useful colleague,
not a firehose. It is the SIBLING of the draft-approval gate
(``draft_approval_service.py``):

  - draft-approval gate (ACTION gate): "should this outbound ACTION happen at
    all? (a human approves first)"
  - human-output gate (MESSAGE gate, this): "is this human-facing MESSAGE
    concise, non-repetitive, and within rate limits? should it be a thread
    reply, or batched into the daily stand-up, instead of sent right now?"

Both are pre-send guards on the SAME notifier path; they compose (the action
gate decides whether a thing happens, this decides how/whether to say it).

What it enforces, applied in this order to every message:

    1. dedup            — drop a message that repeats what was just said.
    2. thread-preference— prefer a thread reply over a new top-level channel
                          message. If a thread is open (``thread_ts`` given) we
                          stay in it; if not and we're posting top-level, we
                          force the message into the channel's running thread
                          when one exists. Resolved before the rate limit
                          because the rate limit governs only top-level posts.
    3. rate-limit       — if the channel has heard from us too many times in the
                          window, do not add another TOP-LEVEL message; defer it
                          to the daily stand-up (urgent and thread replies
                          bypass; see below).
    4. crystallize      — distill to the smallest output that still carries the
                          meaning, in the receiver's bandwidth (reuses the
                          crystallize seam — see ``Crystallizer`` below).
    5. decision         — SEND (now, possibly crystallized / forced to a thread),
                          DEFER (queued to the per-channel daily digest), or
                          SUPPRESS (duplicate / over-noise with nothing worth
                          sending now).

Boundaries (docs/BOUNDARIES.md): crystallize is a core engine function; this
gate enforces it. All gate state (recent-message fingerprints, per-channel send
counters, the deferred-digest queue) is TRANSIENT operational state Amebo owns
and is given a TTL — it decays and is registered with the per-store GC. Nothing
durable lives here.

Additive: this provides the gate as a function the notifier WOULD call before
sending. It does NOT rewire the live send path. The single integration point is
documented in docs/OUTPUT_GATE.md.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Callable, Dict, List, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)


# ===========================================================================
# Config — every knob is here, defaults documented, no magic numbers inline.
# ===========================================================================


@dataclass(frozen=True)
class OutputGateConfig:
    """
    All tunables for the gate. Defaults are conservative ("a quiet, useful
    colleague"). Override at construction time; never hardcode a number in the
    logic. See docs/OUTPUT_GATE.md for the rationale behind each default.
    """

    # Rate limit: at most this many top-level (non-thread, non-urgent) messages
    # per channel within ``rate_window``. The (N+1)th non-urgent message in the
    # window is deferred to the daily stand-up rather than sent.
    max_msgs_per_channel: int = 5
    rate_window: timedelta = timedelta(hours=1)

    # Daily stand-up: the hour of day (local server time, 0-23) at which the
    # per-channel digest is intended to flush. The gate does not run a clock
    # itself (no daemon); a scheduler tick calls ``flush_daily_digest`` when the
    # hour matches. ``is_standup_hour`` exposes the check.
    daily_standup_hour: int = 9

    # Dedup: a message whose fingerprint matches one sent to the same channel
    # within this lookback is SUPPRESSED as a repeat.
    dedup_lookback: timedelta = timedelta(hours=24)

    # TTL after which transient gate state for an idle channel is GC'd. Must be
    # at least as long as the longest lookback so we never forget state we still
    # consult. Defaults to the dedup lookback.
    state_ttl: timedelta = timedelta(hours=24)

    def __post_init__(self) -> None:
        if self.max_msgs_per_channel < 0:
            raise ValueError("max_msgs_per_channel must be >= 0")
        if self.rate_window <= timedelta(0):
            raise ValueError("rate_window must be positive")
        if not (0 <= self.daily_standup_hour <= 23):
            raise ValueError("daily_standup_hour must be in 0..23")
        if self.dedup_lookback < timedelta(0):
            raise ValueError("dedup_lookback must be >= 0")
        if self.state_ttl < max(self.rate_window, self.dedup_lookback):
            raise ValueError(
                "state_ttl must be >= the longest lookback "
                "(rate_window / dedup_lookback) so consulted state isn't GC'd"
            )


# ===========================================================================
# Crystallize seam — reuse the core crystallize engine; tests fake it.
# ===========================================================================


class Crystallizer(Protocol):
    """
    The conciseness step. Per docs/CRYSTALLIZE.md crystallizing is a core engine
    function (not a channel feature): distill an input pile to the smallest
    output that carries the meaning, at the receiver's bandwidth.

    The gate depends on this seam, never on a concrete implementation. The real
    wiring injects the engine's crystallize call; unit tests inject a fake. When
    the crystallize-engine code lands (it is a documented commitment, not yet a
    built function — see CRYSTALLIZE.md "Status"), wrap it here.
    """

    def crystallize(
        self,
        items: List[str],
        *,
        in_thread: bool,
        receiver: Optional[str] = None,
    ) -> str:
        """Distill ``items`` into one message. ``in_thread`` signals an open
        working relationship (more length allowed); top-level wants 1-2 lines."""
        ...


class _PassthroughCrystallizer:
    """
    Default crystallizer used until the real engine is injected. It does NOT
    invent a summarization model (that would reinvent crystallize); it only
    JOINS the pile deterministically and trims to the receiver's bandwidth per
    CRYSTALLIZE.md (1-2 lines cold, more inside an open thread). This keeps the
    gate honest and offline-safe; production injects the real engine.
    """

    # Bandwidth ceilings from CRYSTALLIZE.md, made explicit (not magic): a cold
    # top-level ping gets two lines; an open thread may expand.
    COLD_MAX_LINES = 2
    THREAD_MAX_LINES = 12

    def crystallize(
        self,
        items: List[str],
        *,
        in_thread: bool,
        receiver: Optional[str] = None,
    ) -> str:
        lines: List[str] = []
        for it in items:
            for ln in (it or "").splitlines():
                ln = ln.strip()
                if ln:
                    lines.append(ln)
        if not lines:
            return ""
        cap = self.THREAD_MAX_LINES if in_thread else self.COLD_MAX_LINES
        if len(lines) <= cap:
            return "\n".join(lines)
        head = lines[: cap - 1]
        more = len(lines) - len(head)
        head.append(f"(+{more} more — ask for detail)")
        return "\n".join(head)


# ===========================================================================
# Decision result
# ===========================================================================


class Disposition(str, Enum):
    SEND = "send"          # deliver now (text is crystallized; may be threaded)
    DEFER = "defer"        # queued to the per-channel daily stand-up digest
    SUPPRESS = "suppress"  # dropped (duplicate, or over-rate with nothing new)


@dataclass
class GateDecision:
    """
    Outcome of running one message through the gate. The notifier acts on
    ``disposition``:

      - SEND     → call the real notifier with ``text`` and ``thread_ts``.
      - DEFER    → do nothing now; the message is in the digest queue and will
                   leave at the daily stand-up flush.
      - SUPPRESS → do nothing; the message was a repeat or over-noise.
    """

    disposition: Disposition
    channel: str
    text: Optional[str] = None              # crystallized text, when SEND
    thread_ts: Optional[str] = None         # thread to reply in, when SEND
    reason: str = ""                        # human-readable why
    urgency: str = "normal"

    @property
    def should_send(self) -> bool:
        return self.disposition is Disposition.SEND


# ===========================================================================
# Transient state stores (in-memory, TTL'd, GC-registered)
# ===========================================================================


def _now() -> float:
    """Monotonic-ish wall seconds. A module seam so tests can freeze time."""
    return time.time()


@dataclass
class _ChannelState:
    """Per-channel transient state. Everything here decays."""

    # (fingerprint -> last-seen epoch seconds) for dedup.
    recent_fingerprints: Dict[str, float] = field(default_factory=dict)
    # epoch seconds of each top-level non-urgent send, for rate limiting.
    send_times: List[float] = field(default_factory=list)
    # the running thread_ts we keep replying into, if known.
    active_thread_ts: Optional[str] = None
    # deferred items awaiting the daily stand-up: (text, goal_id, epoch).
    digest: List[Tuple[str, Optional[str], float]] = field(default_factory=list)
    # last time anything touched this channel (for whole-channel GC).
    last_touch: float = field(default_factory=_now)


# ===========================================================================
# The gate
# ===========================================================================

# A sender takes (channel, text, thread_ts) and returns True on success. The
# gate NEVER imports a channel; the notifier passes its real send fn at flush
# time. Mirrors goal_dispatcher.Notifier with the optional thread arg added.
DigestSender = Callable[[str, str, Optional[str]], bool]


class HumanOutputGate:
    """
    Cheap to instantiate. Holds the config, the crystallize seam, and the
    transient per-channel state. Thread-safe (a lock guards the state maps) so
    it can sit on a shared notifier path.

    The gate makes a DECISION; it does not send. The caller (notifier) acts on
    the decision. For deferred messages, the daily stand-up is flushed by
    ``flush_daily_digest(channel, sender=...)``, which the scheduler calls when
    ``is_standup_hour()`` is true.
    """

    def __init__(
        self,
        config: Optional[OutputGateConfig] = None,
        crystallizer: Optional[Crystallizer] = None,
    ):
        self._cfg = config or OutputGateConfig()
        self._crystallizer: Crystallizer = crystallizer or _PassthroughCrystallizer()
        self._channels: Dict[str, _ChannelState] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------- config

    @property
    def config(self) -> OutputGateConfig:
        return self._cfg

    def is_standup_hour(self, hour: int) -> bool:
        """True when ``hour`` (0-23, local) is the configured stand-up hour. The
        scheduler passes the current hour so the gate owns no clock/daemon."""
        return hour == self._cfg.daily_standup_hour

    # ------------------------------------------------------------- the gate

    def gate(
        self,
        message: str,
        *,
        channel: str,
        thread_ts: Optional[str] = None,
        urgency: str = "normal",
        goal_id: Optional[str] = None,
    ) -> GateDecision:
        """
        Run one human-facing message through the gate.

        Order: dedup → rate-limit/over-noise → thread-preference → crystallize →
        decision. ``urgency='urgent'`` bypasses the rate-limit/batching step
        (it always SENDs now) but STILL goes through dedup and crystallize — an
        urgent message must not be a repeat and must still be concise.
        """
        text = (message or "").strip()
        if not text:
            return GateDecision(
                Disposition.SUPPRESS, channel, reason="empty message",
                urgency=urgency,
            )

        with self._lock:
            st = self._touch(channel)
            now = _now()
            self._expire_state(st, now)

            # (1) dedup — a repeat of something said recently is suppressed.
            fp = self._fingerprint(text)
            seen_at = st.recent_fingerprints.get(fp)
            if seen_at is not None and (now - seen_at) <= self._cfg.dedup_lookback.total_seconds():
                logger.debug("[output-gate] dedup suppress on %s", channel)
                return GateDecision(
                    Disposition.SUPPRESS, channel,
                    reason="duplicate within dedup lookback", urgency=urgency,
                )

            urgent = (urgency or "normal").lower() == "urgent"

            # (2) thread-preference (resolved before rate-limiting, because the
            # rate limit only governs TOP-LEVEL posts — thread replies are
            # preferred and cheap). If no thread was given but the channel has a
            # running thread, force the message into it rather than posting a new
            # top-level message. If a thread_ts is supplied, stay in it and adopt
            # it as the channel's running thread.
            chosen_thread = thread_ts or st.active_thread_ts
            if thread_ts:
                st.active_thread_ts = thread_ts
            in_thread = chosen_thread is not None

            # (3) rate-limit / over-noise. Applies only to non-urgent, TOP-LEVEL
            # messages: urgent bypasses, and a thread reply never counts toward
            # (or is blocked by) the per-channel top-level budget.
            if not urgent and not in_thread and self._over_rate(st, now):
                # Defer to the daily stand-up instead of adding to the noise.
                st.digest.append((text, goal_id, now))
                # Record the fingerprint so a later identical attempt dedups,
                # and so the digest itself won't double-count it.
                st.recent_fingerprints[fp] = now
                logger.debug("[output-gate] rate-limit defer on %s", channel)
                return GateDecision(
                    Disposition.DEFER, channel,
                    reason="over rate limit; queued to daily stand-up",
                    urgency=urgency,
                )

            # (4) crystallize — single message, receiver bandwidth aware.
            crystallized = self._crystallizer.crystallize(
                [text], in_thread=in_thread, receiver=channel,
            ).strip()
            if not crystallized:
                return GateDecision(
                    Disposition.SUPPRESS, channel,
                    reason="crystallized to nothing", urgency=urgency,
                )

            # (5) decision = SEND. Record the send for dedup + rate accounting.
            st.recent_fingerprints[fp] = now
            # Only a top-level (not-in-thread) send counts toward the rate
            # limit; thread replies are cheap and threads are preferred.
            if not in_thread:
                st.send_times.append(now)
            return GateDecision(
                Disposition.SEND, channel, text=crystallized,
                thread_ts=chosen_thread,
                reason="urgent send" if urgent else "send",
                urgency=urgency,
            )

    # ------------------------------------------------------- daily stand-up

    def flush_daily_digest(
        self,
        channel: str,
        sender: Optional[DigestSender] = None,
    ) -> Optional[GateDecision]:
        """
        Collapse ALL queued items for ``channel`` into ONE crystallized stand-up
        message covering every goal, and clear the queue. Returns the SEND
        decision for that single message (or None if the queue was empty).

        If ``sender`` is provided it is invoked with the stand-up text (sent in
        the channel's running thread when one exists, so the daily report stays
        a thread reply per the thread-preference rule). If no sender is given,
        the caller delivers using the returned decision.

        This is the "report once daily as one overall stand-up covering all the
        things, even with multiple goals" requirement: many goals collapse into
        one concise message, not one per goal.
        """
        with self._lock:
            st = self._channels.get(channel)
            if not st or not st.digest:
                return None

            items = [t for (t, _g, _ts) in st.digest]
            goal_ids = sorted({g for (_t, g, _ts) in st.digest if g})
            in_thread = st.active_thread_ts is not None

            standup = self._crystallizer.crystallize(
                items, in_thread=in_thread, receiver=channel,
            ).strip()

            # Clear the queue regardless — it has been crystallized out.
            st.digest.clear()
            st.last_touch = _now()

            if not standup:
                return None

            decision = GateDecision(
                Disposition.SEND, channel, text=standup,
                thread_ts=st.active_thread_ts,
                reason=(
                    "daily stand-up covering "
                    + (f"{len(goal_ids)} goals" if goal_ids else "all queued items")
                ),
                urgency="normal",
            )

        # Deliver outside the lock if a sender was provided.
        if sender is not None:
            try:
                sender(channel, decision.text or "", decision.thread_ts)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[output-gate] stand-up sender raised for %s: %s", channel, exc
                )
        return decision

    def pending_digest_count(self, channel: str) -> int:
        """How many items are queued for the channel's next stand-up. For
        tests / introspection."""
        with self._lock:
            st = self._channels.get(channel)
            return len(st.digest) if st else 0

    # ------------------------------------------------------- GC integration

    def gc_idle_channels(self, ttl: Optional[timedelta] = None) -> List[str]:
        """
        Drop transient state for channels untouched for longer than ``ttl``
        (default ``config.state_ttl``). A channel with queued digest items is
        NEVER dropped (its stand-up still has to go out). Returns the channel
        keys evicted. Idempotent; safe to call from a scheduler tick / the GC
        runner.
        """
        cutoff_ttl = (ttl or self._cfg.state_ttl).total_seconds()
        now = _now()
        evicted: List[str] = []
        with self._lock:
            for chan, st in list(self._channels.items()):
                if st.digest:
                    continue  # never drop a channel with an undelivered stand-up
                self._expire_state(st, now)
                if (now - st.last_touch) > cutoff_ttl and not st.recent_fingerprints \
                        and not st.send_times:
                    del self._channels[chan]
                    evicted.append(chan)
        if evicted:
            logger.info("[output-gate] GC evicted %d idle channels", len(evicted))
        return evicted

    # ------------------------------------------------------------- internal

    def _touch(self, channel: str) -> _ChannelState:
        st = self._channels.get(channel)
        if st is None:
            st = _ChannelState()
            self._channels[channel] = st
        st.last_touch = _now()
        return st

    def _over_rate(self, st: _ChannelState, now: float) -> bool:
        window = self._cfg.rate_window.total_seconds()
        recent = [t for t in st.send_times if (now - t) <= window]
        st.send_times = recent
        return len(recent) >= self._cfg.max_msgs_per_channel

    def _expire_state(self, st: _ChannelState, now: float) -> None:
        """Drop fingerprints past dedup lookback and send-times past the rate
        window. Keeps per-channel state bounded between GC passes."""
        dedup = self._cfg.dedup_lookback.total_seconds()
        st.recent_fingerprints = {
            fp: t for fp, t in st.recent_fingerprints.items()
            if (now - t) <= dedup
        }
        window = self._cfg.rate_window.total_seconds()
        st.send_times = [t for t in st.send_times if (now - t) <= window]

    @staticmethod
    def _fingerprint(text: str) -> str:
        """Stable dedup fingerprint: case- and whitespace-insensitive hash of
        the message body. Two messages that say the same thing collide."""
        import hashlib

        normalized = " ".join(text.lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ===========================================================================
# GC policy adapter — register the gate's transient state with state_decay.
# ===========================================================================


class OutputGateGcPolicy:
    """
    Adapts ``HumanOutputGate`` to the ``state_decay.GcPolicy`` protocol so the
    gate's transient counters/digest-queue decay through the SAME per-store GC
    runner as threads / goal_events / abra working memory (BOUNDARIES.md: each
    store runs its own GC; transient state needs a TTL).

    The "items" are idle channel keys. ``expire`` evicts them via the gate's own
    ``gc_idle_channels``; channels with an undelivered stand-up are protected by
    the gate and never enumerated.
    """

    def __init__(self, gate: HumanOutputGate, ttl: Optional[timedelta] = None):
        self._gate = gate
        self._ttl = ttl or gate.config.state_ttl

    @property
    def name(self) -> str:
        return "output_gate"

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def is_durable(self, item: object) -> bool:
        # Transient by definition; nothing here is durable.
        return False

    def enumerate_expirable(self) -> List[str]:
        now = _now()
        cutoff = self._ttl.total_seconds()
        out: List[str] = []
        with self._gate._lock:  # noqa: SLF001 — adapter is part of the module
            for chan, st in self._gate._channels.items():  # noqa: SLF001
                if st.digest:
                    continue
                if (now - st.last_touch) > cutoff:
                    out.append(chan)
        return out

    def expire(self, items: List[str]):
        from src.services.state_decay.policy import GcReport

        evicted = self._gate.gc_idle_channels(self._ttl)
        keep = set(items)
        evicted = [c for c in evicted if c in keep] or evicted
        return GcReport(
            store=self.name,
            considered=len(items),
            expired=len(evicted),
            expired_ids=evicted,
        )


def register_output_gate_gc(gate: HumanOutputGate, registry=None) -> None:
    """
    Register ``gate`` with the state-decay store registry (default: the
    process-wide ``default_registry``) so ``run_gc`` decays its idle-channel
    state alongside the other stores. Idempotent: re-registers cleanly.

    This is opt-in wiring the notifier owner calls once when constructing the
    shared gate; the gate itself imports nothing from state_decay at module load,
    keeping it additive and side-effect-free on import.
    """
    from src.services.state_decay.policy import default_registry

    reg = registry or default_registry
    reg.unregister("output_gate")
    reg.register(OutputGateGcPolicy(gate))
