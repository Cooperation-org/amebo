"""
Contact claw — the outreach-prioritization claw.

Strategic purpose (see docs/CONTACT_CLAW.md, docs/OPPORTUNITY_CLAW.md,
docs/BOUNDARIES.md): a team always knows more people it *could* reach out to
than it has hours to reach. Those people are not a new kind of record — they are
the **outreach opportunities already sitting in the CRM** (``crm.lead`` joined to
``res.partner``). This claw is the agency layer that turns that pool into a
*preliminary ordering* — "who should I reach out to first" — that a human then
acts on:

  1. READ the outreach contacts from the CRM (name, role, tags, campaign, note,
     whether we even have an email for them).
  2. SCORE each against the org's outreach RUBRIC using a CHEAP model (haiku).
     The cheap model is correct here precisely because the rubric carries the
     judgment and a human decides who to actually contact — the model produces a
     draft ordering, not a decision.
  3. RANK and shortlist.
  4. ROUTE the ranked draft through the existing gates for a human to act on.
     The claw NEVER emails anyone, NEVER writes a score back to the CRM, and
     NEVER reorders anything on its own.

This is the exact sibling of ``opportunity_claw``: same machinery, same three
injected Protocols (a reader, a rubric, a scorer), same "no rubric → stay
silent" rule, same default-deny gates. The only differences are *what* it reads
(CRM contacts, not unassigned tasks) and *that it adds a per-contact
confidence* alongside the score.

The RUBRIC is the org's outreach values operationalized into weighted scoring
criteria, so it lives in **abra** (semantic, per-audience), NOT in amebo —
specifically abra name ``contact-outreach-rubric``, scope ``claude`` (see
``DEFAULT_RUBRIC_SCOPE`` / ``DEFAULT_RUBRIC_NAME`` and ``default_rubric_resolve``
below). amebo only references it (BOUNDARIES.md).

Boundaries (docs/BOUNDARIES.md): amebo owns no contact list, no rubric, no
outreach queue. It READS contacts through an injected ``ContactReader`` (real
adapter: ``contact_reader.OdooContactReader``), READS the rubric through an
injected ``RubricReader`` (REUSED from ``opportunity_claw`` → abra), and SCORES
through an injected ``ContactScorer`` (which REUSES ``opportunity_claw``'s
``AnthropicScorer`` — the cheap haiku model — rather than rebuilding it). All
three are Protocols so real adapters bind to the CRM / abra / Anthropic while
tests inject fakes — no real Odoo/abra/model calls in the pure path.

Additive: this provides the claw as a function the scheduler WOULD call on a
tick (and a skill the chat surface can invoke). It does NOT wire the scheduler,
edit the registry, or rewire any send path. Integration seam is documented in
docs/CONTACT_CLAW.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence

# Reuse the gate Protocols and datetime helper from pm_claw — the outbound path
# is identical to both existing claws; nothing new to model there.
from src.services.pm_claw import ApprovalGate, OutputGate, Task, _aware

# Reuse the rubric machinery and the cheap-model scorer WHOLESALE from the
# opportunity claw. The rubric is the same shape (JSON criteria/weights) and the
# scorer is the same haiku client — we do NOT rebuild either.
from src.services.opportunity_claw import (  # noqa: F401 (AbraRubricReader re-exported)
    AbraRubricReader,
    AnthropicScorer,
    Rubric,
    RubricCriterion,
    RubricReader,
    ScoredOpportunity,
)

logger = logging.getLogger(__name__)

# Where this claw's rubric lives in abra. Unlike the opportunity claw (whose
# org→rubric convention was still open), the CONTACT rubric has a decided home:
# abra name ``contact-outreach-rubric``, scope ``claude``. Its content is the
# same JSON shape the rubric reader already parses:
#   {"criteria": [{"name": "...", "weight": 2.0, "description": "..."}, ...],
#    "skill_notes": "..."}
DEFAULT_RUBRIC_SCOPE = "claude"
DEFAULT_RUBRIC_NAME = "contact-outreach-rubric"


def default_rubric_resolve(_org_id: int) -> tuple:
    """The decided org→rubric mapping for the contact claw: every org reads the
    single ``contact-outreach-rubric`` (scope ``claude``). Passed to the REUSED
    ``AbraRubricReader`` at wiring time so the convention is explicit and
    injected, never guessed inside the reader."""
    return (DEFAULT_RUBRIC_SCOPE, DEFAULT_RUBRIC_NAME)


# ===========================================================================
# Config — every knob here, defaults documented, no magic numbers inline.
# ===========================================================================


@dataclass(frozen=True)
class ContactClawConfig:
    """
    Tunables for one ranking pass. Defaults are conservative. Override at
    construction; never hardcode a number in the logic.
    """

    # Cost ceiling: at most this many contacts are sent to the scorer in one
    # pass. Keeps the cheap-model bill flat. Surplus is reported (never dropped).
    max_candidates: int = 50

    # How many top-ranked contacts to put in front of the human. The rest stay
    # scored in the report but out of the headline shortlist.
    shortlist_size: int = 10

    # When True, contacts we have no email for are dropped before scoring
    # (can't reach them). Default False: keep them, let the rubric weigh
    # reachability, and surface the count — dropping is the caller's choice.
    require_email: bool = False

    def __post_init__(self) -> None:
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be >= 1")
        if self.shortlist_size < 1:
            raise ValueError("shortlist_size must be >= 1")


# ===========================================================================
# The contact projection + injection seams — the claw depends on Protocols,
# never on a concrete tool. ContactReader/ContactScorer are new; RubricReader
# is reused from opportunity_claw.
# ===========================================================================


@dataclass(frozen=True)
class Contact:
    """
    One outreach contact as the claw needs to see it — the minimal projection of
    a CRM ``crm.lead`` joined to its ``res.partner``. The adapter
    (``contact_reader.OdooContactReader``) normalizes the CRM's native shape into
    this; the claw stays CRM-agnostic.
    """

    key: str                       # stable id, e.g. "lead-<id>"
    name: str
    role: Optional[str] = None     # job function / position
    tags: tuple = ()               # CRM tags (outreach framing)
    campaign: Optional[str] = None  # UTM campaign name
    note: str = ""                 # partner comment, HTML-stripped
    has_email: bool = False        # do we have any way to reach them?

    def descriptor(self) -> str:
        """A one-line, model-facing summary the scorer reads. Packs the context
        the rubric cares about into the ``title`` slot the reused scorer expects
        (so ``AnthropicScorer`` can score contacts without being rebuilt)."""
        bits = [self.name or "(unnamed)"]
        if self.role:
            bits.append(f"role: {self.role}")
        if self.tags:
            bits.append("tags: " + ", ".join(t for t in self.tags if t))
        if self.campaign:
            bits.append(f"campaign: {self.campaign}")
        bits.append("email: yes" if self.has_email else "email: no")
        if self.note:
            bits.append("note: " + self.note[:200])
        return " | ".join(bits)


class ContactReader(Protocol):
    """
    Reads the org's outreach contacts from the system of record (the CRM via the
    real ``OdooContactReader`` adapter). The claw NEVER imports Odoo; the adapter
    passes the projection in. Tests inject a fake. Empty is a valid answer.
    """

    def list_contacts(self, *, org_id: int) -> Sequence[Contact]:
        ...


@dataclass
class ScoredContact:
    """One contact after the cheap model scored it against the rubric.

    ``confidence`` is Optional on purpose: the REUSED ``AnthropicScorer`` emits a
    score + rationale but not a calibrated confidence, so the real adapter
    reports ``None`` (unknown) rather than fabricating a number — honest, not a
    guess. A fake scorer (tests) or a future scorer that has the model emit
    calibrated confidence can populate it. See ``ReusedAnthropicContactScorer``.
    """

    contact_key: str
    name: str
    score: float                 # preliminary, 0..100
    confidence: Optional[float] = None  # 0..1 when known; None = uncalibrated
    why: str = ""                # one-clause rationale
    rank: int = 0                # 1-based, assigned by rank_contacts()


class ContactScorer(Protocol):
    """
    Scores contacts against the rubric and returns one ScoredContact per
    contact. A Protocol so tests inject a deterministic fake — no real model call
    in the pure path. The real adapter (``ReusedAnthropicContactScorer``) reuses
    ``opportunity_claw.AnthropicScorer`` rather than rebuilding the haiku client.
    """

    def score_contacts(
        self, candidates: Sequence[Contact], rubric: Rubric
    ) -> Sequence[ScoredContact]:
        ...


# ===========================================================================
# Structured report — what the claw assessed (returned to the caller).
# ===========================================================================


@dataclass
class RankingReport:
    """
    The structured result of one contact-ranking pass. The caller gets the full
    assessment regardless of what the gates decided to do with the message.

    ``sent_directly`` is ALWAYS False — the claw never sends and never writes
    scores back to the CRM. ``note`` carries a plain reason when the pass
    produced no ranking (no contacts / no rubric), so silence is explainable.
    """

    org_id: int
    channel: str
    generated_at: datetime
    rubric_name: Optional[str] = None
    ranked: List[ScoredContact] = field(default_factory=list)
    candidate_count: int = 0          # outreach contacts found
    scored_count: int = 0             # how many were sent to the scorer
    overflow: int = 0                 # candidates beyond max_candidates (not scored)
    no_email_count: int = 0           # candidates with no email (a signal, surfaced)
    draft_text: Optional[str] = None
    message_queued: bool = False
    sent_directly: bool = False       # invariant: the claw never sends
    gate_decision: Any = None
    approval_result: Any = None
    note: Optional[str] = None

    @property
    def is_quiet(self) -> bool:
        """True when there is nothing to put in front of a human."""
        return not self.ranked


# ===========================================================================
# Pure logic — trivially unit-testable, no I/O, no gates.
# ===========================================================================


def select_candidates(
    contacts: Sequence[Contact], config: ContactClawConfig
) -> List[Contact]:
    """
    The candidates = contacts we can actually act on. A contact with no name is
    nothing to reach out to, so it is dropped. When ``require_email`` is set,
    contacts we have no email for are dropped too (otherwise kept, so the rubric
    can weigh reachability and the report can surface the count). Pure filter.
    """
    out: List[Contact] = []
    for c in contacts:
        if not (c.name or "").strip():
            continue  # nothing to act on
        if config.require_email and not c.has_email:
            continue
        out.append(c)
    return out


def rank_contacts(scored: Sequence[ScoredContact]) -> List[ScoredContact]:
    """
    Sort by score descending (stable, so equal scores keep input order) and
    stamp a 1-based rank. Pure; the preliminary ordering, nothing more.
    """
    ordered = sorted(scored, key=lambda s: s.score, reverse=True)
    for i, s in enumerate(ordered, start=1):
        s.rank = i
    return ordered


def _render_line(s: ScoredContact) -> str:
    why = f" — {s.why}" if s.why else ""
    conf = f" (conf {s.confidence:.0%})" if s.confidence is not None else ""
    return f"{s.rank}. [{s.score:.0f}{conf}] {s.name}{why}"


# ===========================================================================
# The claw entry point
# ===========================================================================


def run_contact_claw(
    *,
    org_id: int,
    channel: str,
    contact_reader: ContactReader,
    rubric_reader: RubricReader,
    scorer: ContactScorer,
    output_gate: OutputGate,
    approval_gate: Optional[ApprovalGate] = None,
    config: Optional[ContactClawConfig] = None,
    acting_identity: Optional[str] = None,
    instance_id: Optional[int] = None,
    deferred_send: Optional[Callable[[Dict[str, Any]], str]] = None,
    now: Optional[datetime] = None,
) -> RankingReport:
    """
    Run one contact-ranking pass for an org and queue ONE ranked draft ("who to
    reach out to") for a human. The claw performs NO direct side effect — it
    returns the ranking and routes the message through the gates. It NEVER emails
    anyone and NEVER writes a score back to the CRM.

    Flow (identical discipline to run_opportunity_claw):
      1. READ the outreach contacts via ContactReader.
      2. LOAD the rubric via RubricReader. No rubric → stay silent (we never
         invent criteria; a ranking without a rubric is a hidden judgment).
      3. SCORE the candidates with the cheap model (ContactScorer), RANK,
         shortlist.
      4. ROUTE the SEND through the draft-approval (ACTION) gate — outbound, so
         held for human approval (default-deny).
      5. DEFER the body into the human-output (MESSAGE) gate's digest.

    Empty contacts or no rubric → queues nothing, returns a report whose ``note``
    explains the silence.
    """
    cfg = config or ContactClawConfig()
    when = _aware(now) or datetime.now(timezone.utc)
    acting = acting_identity or f"amebo:org-{org_id}"

    report = RankingReport(org_id=org_id, channel=channel, generated_at=when)

    # (1) READ — the outreach contacts from the CRM.
    candidates = select_candidates(
        list(contact_reader.list_contacts(org_id=org_id)), cfg
    )
    report.candidate_count = len(candidates)
    report.no_email_count = sum(1 for c in candidates if not c.has_email)
    if not candidates:
        report.note = "no outreach contacts to rank"
        logger.debug("[contact-claw] org=%s: %s", org_id, report.note)
        return report

    # (2) LOAD the rubric — without it we do NOT rank (no hidden judgment).
    rubric = rubric_reader.get_rubric(org_id=org_id)
    if rubric is None or rubric.is_empty:
        report.note = (
            "no outreach rubric set for this org — cannot produce a preliminary "
            "ordering. Set 'contact-outreach-rubric' (the org's outreach values "
            "as weighted criteria) in abra first."
        )
        logger.info("[contact-claw] org=%s: %s", org_id, report.note)
        return report
    report.rubric_name = rubric.name

    # Cost ceiling: score at most max_candidates; report the overflow, never
    # silently drop it.
    to_score = candidates[: cfg.max_candidates]
    report.overflow = len(candidates) - len(to_score)
    report.scored_count = len(to_score)

    # (3) SCORE with the cheap model, then RANK (pure) and shortlist.
    scored = list(scorer.score_contacts(to_score, rubric))
    ranked = rank_contacts(scored)
    report.ranked = ranked[: cfg.shortlist_size]

    if report.is_quiet:
        report.note = "scorer returned nothing to rank"
        logger.info("[contact-claw] org=%s: %s", org_id, report.note)
        return report

    # (4)+(5) COMPOSE the ranked draft. Explicitly a PROPOSAL — a human decides
    # who to actually contact.
    lines = [_render_line(s) for s in report.ranked]
    overflow_note = (
        f"\n(+{report.overflow} more contacts not scored this pass — raise "
        f"max_candidates to include them)"
        if report.overflow
        else ""
    )
    email_note = (
        f"\n({report.no_email_count} of {report.candidate_count} have no email "
        f"on file — find one before reaching out)"
        if report.no_email_count
        else ""
    )
    draft_text = (
        f"Contact outreach ranking ({when:%Y-%m-%d}) against rubric "
        f"'{rubric.name}'. Preliminary order — who to reach out to first, for a "
        f"human to decide and act on, not a decision.\n"
        + "\n".join(lines)
        + overflow_note
        + email_note
    )
    report.draft_text = draft_text

    # ACTION gate — the SEND is outbound; hold for human approval (default-deny).
    # The claw does NOT execute: the executor is the deferred-send hook, run only
    # after a human approves.
    if approval_gate is not None:
        def _executor(_action: Dict[str, Any]) -> str:
            if deferred_send is not None:
                return deferred_send(_action)
            # No real sender wired yet — surface that, never send silently.
            # TODO(send): bind to the gated Slack post executor on approval.
            logger.info(
                "[contact-claw] approved ranking for org=%s has no sender wired",
                org_id,
            )
            return "[contact-claw] approved; no sender wired"

        report.approval_result = approval_gate.gate_or_execute(
            org_id=org_id,
            action_type="slack_post",          # outbound → GATED (default-deny)
            acting_identity=acting,
            executor=_executor,
            target=channel,
            payload={"text": draft_text, "notify_channel": channel},
            preview=f"Contact ranking: top {len(report.ranked)} of "
                    f"{report.candidate_count} to reach out to",
            instance_id=instance_id,
        )

    # MESSAGE gate — DEFER the body into the channel's digest. urgency 'normal'
    # so the gate batches it; the claw never forces a top-level send.
    report.gate_decision = output_gate.gate(draft_text, channel=channel, urgency="normal")
    report.message_queued = True
    report.sent_directly = False  # invariant, asserted explicitly

    logger.info(
        "[contact-claw] org=%s channel=%s: queued ranking of top %d/%d",
        org_id, channel, len(report.ranked), report.candidate_count,
    )
    return report


# ===========================================================================
# Concrete scorer adapter — REUSES the opportunity claw's AnthropicScorer (the
# cheap haiku model) instead of rebuilding it. Constructed only by the (future)
# scheduler wiring, exactly like the rest of the claw machinery.
# ===========================================================================


class ReusedAnthropicContactScorer:
    """
    A ``ContactScorer`` that REUSES ``opportunity_claw.AnthropicScorer`` — the
    same haiku client, prompt, JSON parse, and graceful fallback — rather than
    rebuilding any of it. It only adapts the shapes at the boundary:

      Contact         → the ``Task`` projection the reused scorer scores
                        (id = contact.key, title = contact.descriptor()).
      ScoredOpportunity → ScoredContact (score + rationale carried through).

    Confidence: the reused scorer does not emit a calibrated per-item
    confidence, so this adapter reports ``None`` for a genuine model score (the
    honest "unknown"), and ``0.0`` when it can tell the underlying scorer will
    fall back to a deterministic placeholder order (no API key / no client) —
    that ordering is not a real judgment and says so. This is provenance, not a
    fabricated probability. A future scorer that has the model emit confidence
    can populate real values without touching the claw.
    """

    def __init__(self, scorer: Optional[AnthropicScorer] = None):
        self._scorer = scorer or AnthropicScorer()

    def score_contacts(
        self, candidates: Sequence[Contact], rubric: Rubric
    ) -> Sequence[ScoredContact]:
        by_key = {c.key: c for c in candidates}
        # Adapt Contact → the Task shape the reused scorer expects.
        tasks = [Task(id=c.key, title=c.descriptor()) for c in candidates]
        scored_opps: Sequence[ScoredOpportunity] = self._scorer.score(tasks, rubric)

        # If the reused scorer has no live client it produces a deterministic
        # placeholder order — flag that as zero confidence rather than implying
        # a real judgment.
        fallback = getattr(self._scorer, "client", None) is None
        conf = 0.0 if fallback else None

        out: List[ScoredContact] = []
        for opp in scored_opps:
            contact = by_key.get(opp.task_id)
            name = contact.name if contact else opp.title
            out.append(ScoredContact(
                contact_key=opp.task_id,
                name=name,
                score=opp.score,
                confidence=conf,
                why=opp.rationale,
            ))
        return out
