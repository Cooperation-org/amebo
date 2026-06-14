"""
Opportunity claw — the prioritization claw.

Strategic purpose (see docs/OPPORTUNITY_CLAW.md, docs/ORGS_GOALS_CLAW.md,
docs/BOUNDARIES.md): an org always has more things it *could* do than it can
fund. Those candidates are not a new kind of record — they are simply the
**unassigned, open tasks** already sitting in the task tracker (Golda's call:
"opportunities might just be unassigned tasks"). This claw is the agency layer
that turns that backlog into a *preliminary ordering* a steering committee or
funders can act on:

  1. READ the unassigned/open tasks (the opportunities) from the tracker.
  2. SCORE each against the org's RUBRIC using a CHEAP model (haiku). The cheap
     model is correct here precisely because the rubric carries the judgment and
     a human finalizes — the model produces a draft ordering, not a decision.
  3. RANK and shortlist.
  4. ROUTE the ranked draft through the existing gates for a human to FINALIZE
     the order and assign budget. The claw never sends, never funds, never
     reorders the tracker on its own.

The RUBRIC is the org's values/vision *operationalized* into weighted scoring
criteria — so it lives in abra (semantic, per-audience), NOT in amebo. This is
how the top of the spine (values/vision) gets teeth at the bottom
(what we actually fund). amebo only references it (BOUNDARIES.md).

It is ADDITIVE and composes with the two existing gates instead of reinventing
them — identical discipline to ``pm_claw``:

  - human-output gate (MESSAGE gate, ``human_output_gate.HumanOutputGate``):
    the ranked draft is deferred/crystallized into the channel's digest as ONE
    message, never one-per-opportunity.
  - draft-approval gate (ACTION gate, ``draft_approval_service``): posting the
    ranking is an outbound action, so the SEND is held for human approval
    (default-deny). The claw performs NO direct side effect.

Boundaries (docs/BOUNDARIES.md): amebo owns no task list, no rubric, no budget.
It READS tasks through an injected ``TaskReader`` (reused from ``pm_claw``),
READS the rubric through an injected ``RubricReader`` (abra), and SCORES through
an injected ``Scorer`` (a cheap model). All three are Protocols so the real
adapters bind to the tool layer / abra / Anthropic while tests inject fakes —
no real Taiga/abra/model calls in the pure path.

Additive: this provides the claw as a function the scheduler WOULD call on a
tick (and a skill the chat surface can invoke). It does NOT wire the scheduler,
edit the registry, or rewire any send path. Integration seam is documented in
docs/OPPORTUNITY_CLAW.md.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence

# Reuse the tracker projection and seams already defined by the PM claw — the
# "opportunity" is just an unassigned/open Task, so there is nothing new to model.
from src.services.pm_claw import (
    ApprovalGate,
    OutputGate,
    Task,
    TaskReader,
    _aware,
    _is_done,
)

logger = logging.getLogger(__name__)

# The cheap model for preliminary scoring. Matches src/coding/models.py HAIKU.
# A claw is allowed to name a concrete model (claws are specific); the CORE
# never hardcodes this — only this claw and its config do.
DEFAULT_SCORER_MODEL = "claude-haiku-4-5-20251001"


# ===========================================================================
# Config — every knob here, defaults documented, no magic numbers inline.
# ===========================================================================


@dataclass(frozen=True)
class OpportunityClawConfig:
    """
    Tunables for one ranking pass. Defaults are conservative. Override at
    construction; never hardcode a number in the logic.
    """

    # Task statuses that mean "finished" — never an opportunity. Matches
    # pm_claw's done set; compared case-insensitively.
    done_statuses: frozenset = frozenset({"done", "closed", "completed", "resolved"})

    # Cost ceiling: at most this many candidates are sent to the scorer in one
    # pass. Keeps the cheap-model bill flat across many orgs. If the backlog is
    # larger, the surplus is reported (never silently dropped).
    max_candidates: int = 50

    # How many top-ranked opportunities to put in front of the committee. The
    # rest stay scored in the report but out of the headline shortlist.
    shortlist_size: int = 10

    # The cheap model used for the preliminary ordering.
    scorer_model: str = DEFAULT_SCORER_MODEL

    def __post_init__(self) -> None:
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be >= 1")
        if self.shortlist_size < 1:
            raise ValueError("shortlist_size must be >= 1")


# ===========================================================================
# The rubric — the org's values/vision operationalized. Lives in abra; amebo
# only references a read-only projection of it here.
# ===========================================================================


@dataclass(frozen=True)
class RubricCriterion:
    """One weighted scoring criterion, in the org's own words."""

    name: str
    weight: float = 1.0
    description: str = ""


@dataclass(frozen=True)
class Rubric:
    """
    The projection of an org's rubric the claw needs: a name (for provenance)
    and the weighted criteria. The adapter is responsible for loading this from
    abra; the claw stays storage-agnostic.
    """

    org_id: int
    name: str
    criteria: tuple
    # "abra" when loaded from a real rubric; adapters may set other provenance.
    source: str = "abra"

    @property
    def is_empty(self) -> bool:
        return not self.criteria


# ===========================================================================
# Injection seams — the claw depends on Protocols, never on a concrete tool.
# TaskReader is reused from pm_claw. RubricReader + Scorer are new.
# ===========================================================================


class RubricReader(Protocol):
    """
    Loads an org's rubric from abra. Returns None when the org has no rubric —
    in which case the claw STAYS SILENT and ranks nothing (we never invent
    criteria; ordering without a rubric would be a hidden judgment).

    The convention for WHERE an org's rubric lives in abra (which scope / name)
    is an integration decision, not something this module invents — the real
    adapter is constructed with that mapping. See ``AbraRubricReader``.
    """

    def get_rubric(self, *, org_id: int) -> Optional[Rubric]:
        ...


@dataclass
class ScoredOpportunity:
    """One opportunity after the cheap model scored it against the rubric."""

    task_id: str
    title: str
    score: float                 # preliminary, 0..100
    rationale: str = ""
    rank: int = 0                # 1-based, assigned by rank()


class Scorer(Protocol):
    """
    Scores candidates against the rubric and returns one ScoredOpportunity per
    candidate. Implemented by a CHEAP model (haiku). A Protocol so tests inject
    a deterministic fake — no real model call in the pure path.

    Batch (all candidates in one call) so the model can produce a coherent
    relative ordering and so the cost is one call per pass, not N.
    """

    def score(
        self, candidates: Sequence[Task], rubric: Rubric
    ) -> Sequence[ScoredOpportunity]:
        ...


# ===========================================================================
# Structured report — what the claw assessed (returned to the caller).
# ===========================================================================


@dataclass
class RankingReport:
    """
    The structured result of one ranking pass. The caller gets the full
    assessment regardless of what the gates decided to do with the message.

    ``sent_directly`` is ALWAYS False — the claw never sends. ``note`` carries a
    plain reason when the pass produced no ranking (no candidates / no rubric),
    so silence is explainable rather than mysterious.
    """

    org_id: int
    channel: str
    generated_at: datetime
    rubric_name: Optional[str] = None
    ranked: List[ScoredOpportunity] = field(default_factory=list)
    candidate_count: int = 0          # how many opportunities were found
    scored_count: int = 0             # how many were sent to the scorer
    overflow: int = 0                 # candidates beyond max_candidates (not scored)
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
    tasks: Sequence[Task], config: OpportunityClawConfig
) -> List[Task]:
    """
    The opportunities = OPEN (not in a done status) AND UNASSIGNED (no
    assignee). Golda's definition. Pure filter over the tracker projection.
    """
    out: List[Task] = []
    for t in tasks:
        if _is_done(t.status, config):
            continue
        if (t.assignee or "").strip():
            continue  # already owned by someone — not an open opportunity
        out.append(t)
    return out


def rank(scored: Sequence[ScoredOpportunity]) -> List[ScoredOpportunity]:
    """
    Sort by score descending (stable, so equal scores keep input order) and
    stamp a 1-based rank. Pure; the preliminary ordering, nothing more.
    """
    ordered = sorted(scored, key=lambda s: s.score, reverse=True)
    for i, s in enumerate(ordered, start=1):
        s.rank = i
    return ordered


def _render_line(s: ScoredOpportunity) -> str:
    rationale = f" — {s.rationale}" if s.rationale else ""
    return f"{s.rank}. [{s.score:.0f}] {s.title}{rationale}"


# ===========================================================================
# The claw entry point
# ===========================================================================


def run_opportunity_claw(
    *,
    org_id: int,
    channel: str,
    task_reader: TaskReader,
    rubric_reader: RubricReader,
    scorer: Scorer,
    output_gate: OutputGate,
    approval_gate: Optional[ApprovalGate] = None,
    config: Optional[OpportunityClawConfig] = None,
    acting_identity: Optional[str] = None,
    instance_id: Optional[int] = None,
    deferred_send: Optional[Callable[[Dict[str, Any]], str]] = None,
    now: Optional[datetime] = None,
) -> RankingReport:
    """
    Run one ranking pass for an org and queue ONE ranked draft for the steering
    committee / funders. The claw performs NO direct side effect — it returns
    the ranking and routes the message through the gates. Humans finalize the
    order and assign budget.

    Flow:
      1. READ the unassigned/open tasks (the opportunities) via TaskReader.
      2. LOAD the rubric via RubricReader. No rubric → stay silent (we never
         invent criteria).
      3. SCORE the candidates with the cheap model (Scorer), RANK, shortlist.
      4. ROUTE the SEND through the draft-approval (ACTION) gate — outbound, so
         held for human approval (default-deny).
      5. DEFER the body into the human-output (MESSAGE) gate's digest.

    Empty backlog or no rubric → queues nothing, returns a report whose ``note``
    explains the silence.
    """
    cfg = config or OpportunityClawConfig()
    when = _aware(now) or datetime.now(timezone.utc)
    acting = acting_identity or f"amebo:org-{org_id}"

    report = RankingReport(org_id=org_id, channel=channel, generated_at=when)

    # (1) READ — the opportunities are unassigned/open tracker tasks.
    candidates = select_candidates(list(task_reader.list_tasks(org_id=org_id)), cfg)
    report.candidate_count = len(candidates)
    if not candidates:
        report.note = "no unassigned/open opportunities to rank"
        logger.debug("[opportunity-claw] org=%s: %s", org_id, report.note)
        return report

    # (2) LOAD the rubric — without it we do NOT rank (no hidden judgment).
    rubric = rubric_reader.get_rubric(org_id=org_id)
    if rubric is None or rubric.is_empty:
        report.note = (
            "no rubric set for this org — cannot produce a preliminary ordering. "
            "Set a rubric (the org's values/vision as weighted criteria) in abra first."
        )
        logger.info("[opportunity-claw] org=%s: %s", org_id, report.note)
        return report
    report.rubric_name = rubric.name

    # Cost ceiling: score at most max_candidates; report the overflow, never
    # silently drop it.
    to_score = candidates[: cfg.max_candidates]
    report.overflow = len(candidates) - len(to_score)
    report.scored_count = len(to_score)

    # (3) SCORE with the cheap model, then RANK (pure) and shortlist.
    scored = list(scorer.score(to_score, rubric))
    ranked = rank(scored)
    report.ranked = ranked[: cfg.shortlist_size]

    if report.is_quiet:
        report.note = "scorer returned nothing to rank"
        logger.info("[opportunity-claw] org=%s: %s", org_id, report.note)
        return report

    # (4)+(5) COMPOSE the ranked draft. The output gate crystallizes it; this is
    # the pre-crystallize material. It is explicitly a PROPOSAL — humans finalize.
    lines = [_render_line(s) for s in report.ranked]
    overflow_note = (
        f"\n(+{report.overflow} more opportunities not scored this pass — raise "
        f"max_candidates to include them)"
        if report.overflow
        else ""
    )
    draft_text = (
        f"Opportunity ranking ({when:%Y-%m-%d}) against rubric "
        f"'{rubric.name}'. Preliminary order for the steering committee to "
        f"finalize and fund — not a decision.\n"
        + "\n".join(lines)
        + overflow_note
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
                "[opportunity-claw] approved ranking for org=%s has no sender wired",
                org_id,
            )
            return "[opportunity-claw] approved; no sender wired"

        report.approval_result = approval_gate.gate_or_execute(
            org_id=org_id,
            action_type="slack_post",          # outbound → GATED (default-deny)
            acting_identity=acting,
            executor=_executor,
            target=channel,
            payload={"text": draft_text, "notify_channel": channel},
            preview=f"Opportunity ranking: top {len(report.ranked)} of "
                    f"{report.candidate_count} for steering review",
            instance_id=instance_id,
        )

    # MESSAGE gate — DEFER the body into the channel's digest. urgency 'normal'
    # so the gate batches it; the claw never forces a top-level send.
    report.gate_decision = output_gate.gate(draft_text, channel=channel, urgency="normal")
    report.message_queued = True
    report.sent_directly = False  # invariant, asserted explicitly

    logger.info(
        "[opportunity-claw] org=%s channel=%s: queued ranking of top %d/%d",
        org_id, channel, len(report.ranked), report.candidate_count,
    )
    return report


# ===========================================================================
# Concrete adapters — bind the Protocols to abra and the cheap model. Kept here
# but constructed only by the (future) scheduler wiring, exactly like the rest
# of the claw machinery. Each degrades gracefully so nothing crashes a tick.
# ===========================================================================


class AbraRubricReader:
    """
    Reads a rubric from abra content.

    The org → (scope, name) mapping is NOT invented here — it is injected via
    ``resolve``, a callable the integration supplies that says, for a given
    org_id, which abra (scope, name) holds that org's rubric. This keeps the
    convention an explicit integration decision (per the repo's "never invent a
    stand-in" rule) rather than a guess baked into the claw.

    The rubric content blob is expected to be JSON of the shape::

        {"criteria": [{"name": "...", "weight": 2.0, "description": "..."}, ...]}

    Returns None (→ claw stays silent) when abra is unavailable, the mapping
    yields nothing, or the content is absent/unparseable.
    """

    def __init__(self, resolve: Callable[[int], Optional[tuple]]):
        # resolve(org_id) -> (scope, name) | None
        self._resolve = resolve

    def get_rubric(self, *, org_id: int) -> Optional[Rubric]:
        target = self._resolve(org_id)
        if not target:
            return None
        scope, name = target
        raw = self._read_content(scope, name)
        if not raw:
            return None
        criteria = self._parse_criteria(raw)
        if not criteria:
            return None
        return Rubric(org_id=org_id, name=name, criteria=tuple(criteria), source="abra")

    @staticmethod
    def _read_content(scope: str, name: str) -> Optional[str]:
        """Best-effort read of the latest content blob for (scope, name)."""
        try:
            from src.db.abra_connection import AbraConnection
        except Exception:
            return None
        if not AbraConnection.is_available():
            return None
        conn = AbraConnection.get_connection()
        if conn is None:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT c.content
                         FROM content c
                         JOIN bindings b ON b.content_id = c.id
                        WHERE b.scope = %s AND b.name = %s
                        ORDER BY c.created_at DESC
                        LIMIT 1""",
                    (scope, name),
                )
                row = cur.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.warning("[opportunity-claw] rubric read failed: %s", e)
            return None
        finally:
            AbraConnection.return_connection(conn)

    @staticmethod
    def _parse_criteria(raw: str) -> List[RubricCriterion]:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            data = json.loads(m.group(0) if m else raw)
        except (json.JSONDecodeError, AttributeError):
            return []
        out: List[RubricCriterion] = []
        for c in data.get("criteria", []):
            name = (c.get("name") or "").strip()
            if not name:
                continue
            out.append(
                RubricCriterion(
                    name=name,
                    weight=float(c.get("weight", 1.0)),
                    description=(c.get("description") or "").strip(),
                )
            )
        return out


class AnthropicScorer:
    """
    Scores opportunities against the rubric with a CHEAP model (haiku by
    default). Mirrors the client pattern in ``intentions_service`` exactly:
    construct from ANTHROPIC_API_KEY, one ``messages.create`` call, tolerant
    JSON parse, graceful fallback when the key is absent or the call fails.

    The fallback is deterministic and clearly labelled, never a silent guess: it
    preserves input order so a no-key environment still exercises the pipeline.
    """

    def __init__(
        self,
        anthropic_client: Optional[Any] = None,
        model: str = DEFAULT_SCORER_MODEL,
    ):
        self.model = model
        if anthropic_client is not None:
            self.client = anthropic_client
        else:
            try:
                from anthropic import Anthropic
            except Exception:
                self.client = None
                return
            api_key = os.getenv("ANTHROPIC_API_KEY")
            self.client = Anthropic(api_key=api_key) if api_key else None

    def score(
        self, candidates: Sequence[Task], rubric: Rubric
    ) -> Sequence[ScoredOpportunity]:
        if self.client is None:
            return self._fallback(candidates, "[no ANTHROPIC_API_KEY — order preserved]")
        prompt = self._build_prompt(candidates, rubric)
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=_SCORER_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text if resp.content else ""
        except Exception as e:
            logger.warning("[opportunity-claw] scorer call failed, fallback: %s", e)
            return self._fallback(candidates, "[scorer error — order preserved]")
        parsed = self._parse(raw, candidates)
        return parsed if parsed else self._fallback(
            candidates, "[unparseable scorer output — order preserved]"
        )

    @staticmethod
    def _build_prompt(candidates: Sequence[Task], rubric: Rubric) -> str:
        crit_lines = "\n".join(
            f"- {c.name} (weight {c.weight}): {c.description}".rstrip()
            for c in rubric.criteria
        )
        opp_lines = "\n".join(f"- id={t.id}: {t.title}" for t in candidates)
        return (
            f"Rubric '{rubric.name}' — weighted criteria:\n{crit_lines}\n\n"
            f"Opportunities to score:\n{opp_lines}\n\n"
            "Score each opportunity 0-100 for how well it serves the weighted "
            "rubric. Return ONLY a JSON array, one object per opportunity: "
            '[{"task_id": "...", "score": 0-100, "rationale": "one short clause"}].'
        )

    @staticmethod
    def _parse(raw: str, candidates: Sequence[Task]) -> List[ScoredOpportunity]:
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        try:
            data = json.loads(m.group(0) if m else raw)
        except (json.JSONDecodeError, AttributeError):
            return []
        by_id = {t.id: t for t in candidates}
        out: List[ScoredOpportunity] = []
        for row in data:
            tid = str(row.get("task_id", "")).strip()
            t = by_id.get(tid)
            if t is None:
                continue
            try:
                score = max(0.0, min(100.0, float(row.get("score", 0))))
            except (TypeError, ValueError):
                score = 0.0
            out.append(
                ScoredOpportunity(
                    task_id=t.id,
                    title=t.title,
                    score=score,
                    rationale=(row.get("rationale") or "").strip(),
                )
            )
        return out

    @staticmethod
    def _fallback(
        candidates: Sequence[Task], why: str
    ) -> List[ScoredOpportunity]:
        # Deterministic, order-preserving, clearly labelled — not a real score.
        n = len(candidates)
        return [
            ScoredOpportunity(
                task_id=t.id,
                title=t.title,
                score=float(n - i),  # preserves input order after rank()
                rationale=why,
            )
            for i, t in enumerate(candidates)
        ]


_SCORER_SYSTEM = (
    "You are a fast prioritization assistant. You produce a PRELIMINARY ordering "
    "of opportunities against an explicit rubric for a human steering committee "
    "to finalize. You do not decide; you rank. Be terse. Output JSON only."
)
