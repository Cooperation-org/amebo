"""
Tests for the contact (outreach-prioritization) claw.

Mirrors test_opportunity_claw's discipline: the pure logic (candidate selection,
ranking) is tested directly, and the entry point is tested with injected fakes so
no real Odoo / abra / model calls happen. The key invariants:

  - candidates = outreach contacts with a name (email optional by default)
  - no rubric  -> the claw stays silent and ranks nothing (no invented order)
  - the claw NEVER sends and NEVER writes back to the CRM; outbound goes through
    the gates
  - the ContactScorer is an injection seam (a fake here); the real adapter REUSES
    opportunity_claw.AnthropicScorer (proven to degrade below)
  - the OdooContactReader join/normalization is tested with a fake search_read
    (no XML-RPC)
"""

from datetime import datetime, timezone

import pytest

from src.services.contact_claw import (
    Contact,
    ContactClawConfig,
    ReusedAnthropicContactScorer,
    ScoredContact,
    default_rubric_resolve,
    rank_contacts,
    run_contact_claw,
    select_candidates,
)
from src.services.contact_reader import OdooContactReader, _strip_html
from src.services.opportunity_claw import Rubric, RubricCriterion


NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)


# --- fakes ------------------------------------------------------------------


class FakeContactReader:
    def __init__(self, contacts):
        self._contacts = contacts

    def list_contacts(self, *, org_id):
        return self._contacts


class FakeRubricReader:
    def __init__(self, rubric):
        self._rubric = rubric

    def get_rubric(self, *, org_id):
        return self._rubric


class FakeContactScorer:
    """Scores by a dict {contact_key: (score, confidence)}; default (0, None)."""

    def __init__(self, scores):
        self._scores = scores
        self.called_with = None

    def score_contacts(self, candidates, rubric):
        self.called_with = list(candidates)
        out = []
        for c in candidates:
            score, conf = self._scores.get(c.key, (0.0, None))
            out.append(ScoredContact(
                contact_key=c.key, name=c.name,
                score=score, confidence=conf, why="fake",
            ))
        return out


class RecordingOutputGate:
    def __init__(self):
        self.calls = []

    def gate(self, message, *, channel, thread_ts=None, urgency="normal", goal_id=None):
        self.calls.append({"message": message, "channel": channel, "urgency": urgency})
        return {"action": "deferred"}


class RecordingApprovalGate:
    def __init__(self):
        self.calls = []

    def gate_or_execute(self, org_id, action_type, acting_identity, executor,
                        target=None, payload=None, preview=None,
                        instance_id=None, goal_id=None):
        # default-deny: never call the executor (would be the send)
        self.calls.append({"action_type": action_type, "target": target,
                           "preview": preview, "payload": payload})
        return {"status": "pending_approval"}


def _rubric():
    return Rubric(
        org_id=1, name="contact-outreach-rubric",
        criteria=(RubricCriterion("fit", 2.0, "matches our outreach goals"),),
    )


def _contact(key, name, has_email=True, role=None, tags=(), campaign=None, note=""):
    return Contact(key=key, name=name, has_email=has_email, role=role,
                   tags=tags, campaign=campaign, note=note)


# --- pure: candidate selection ---------------------------------------------


def test_select_candidates_drops_nameless():
    cfg = ContactClawConfig()
    out = select_candidates([
        _contact("lead-1", "Alice"),
        _contact("lead-2", "   "),          # nameless -> dropped
        _contact("lead-3", "Bob"),
    ], cfg)
    assert [c.key for c in out] == ["lead-1", "lead-3"]


def test_require_email_drops_emailless():
    cfg = ContactClawConfig(require_email=True)
    out = select_candidates([
        _contact("lead-1", "Alice", has_email=True),
        _contact("lead-2", "Bob", has_email=False),   # dropped when required
    ], cfg)
    assert [c.key for c in out] == ["lead-1"]


def test_emailless_kept_by_default():
    cfg = ContactClawConfig()
    out = select_candidates([_contact("lead-2", "Bob", has_email=False)], cfg)
    assert [c.key for c in out] == ["lead-2"]


# --- pure: ranking ----------------------------------------------------------


def test_rank_orders_desc_and_stamps_rank():
    scored = [
        ScoredContact("a", "A", 10),
        ScoredContact("b", "B", 90),
        ScoredContact("c", "C", 50),
    ]
    ranked = rank_contacts(scored)
    assert [s.contact_key for s in ranked] == ["b", "c", "a"]
    assert [s.rank for s in ranked] == [1, 2, 3]


def test_rank_is_stable_on_ties():
    scored = [ScoredContact("a", "A", 50), ScoredContact("b", "B", 50)]
    ranked = rank_contacts(scored)
    assert [s.contact_key for s in ranked] == ["a", "b"]


# --- entry point ------------------------------------------------------------


def test_no_contacts_is_quiet():
    report = run_contact_claw(
        org_id=1, channel="slack:#x",
        contact_reader=FakeContactReader([]),
        rubric_reader=FakeRubricReader(_rubric()),
        scorer=FakeContactScorer({}),
        output_gate=RecordingOutputGate(),
        now=NOW,
    )
    assert report.is_quiet
    assert not report.message_queued
    assert "no outreach contacts" in report.note


def test_no_rubric_ranks_nothing():
    out_gate = RecordingOutputGate()
    report = run_contact_claw(
        org_id=1, channel="slack:#x",
        contact_reader=FakeContactReader([_contact("lead-1", "Alice")]),
        rubric_reader=FakeRubricReader(None),   # no rubric
        scorer=FakeContactScorer({"lead-1": (99, 0.9)}),
        output_gate=out_gate,
        now=NOW,
    )
    assert report.is_quiet
    assert not report.message_queued
    assert out_gate.calls == []                 # nothing queued
    assert "no outreach rubric" in report.note


def test_empty_rubric_ranks_nothing():
    empty = Rubric(org_id=1, name="empty", criteria=())
    report = run_contact_claw(
        org_id=1, channel="slack:#x",
        contact_reader=FakeContactReader([_contact("lead-1", "Alice")]),
        rubric_reader=FakeRubricReader(empty),
        scorer=FakeContactScorer({"lead-1": (99, 0.9)}),
        output_gate=RecordingOutputGate(),
        now=NOW,
    )
    assert report.is_quiet
    assert "no outreach rubric" in report.note


def test_ranks_and_routes_through_gates_without_sending():
    out_gate = RecordingOutputGate()
    approval = RecordingApprovalGate()
    contacts = [
        _contact("lead-a", "Low"),
        _contact("lead-b", "High"),
        _contact("lead-c", "Mid"),
    ]
    report = run_contact_claw(
        org_id=1, channel="slack:#outreach",
        contact_reader=FakeContactReader(contacts),
        rubric_reader=FakeRubricReader(_rubric()),
        scorer=FakeContactScorer({
            "lead-a": (10, 0.5), "lead-b": (90, 0.8), "lead-c": (50, 0.6),
        }),
        output_gate=out_gate,
        approval_gate=approval,
        now=NOW,
    )
    # ranked best-first
    assert [s.contact_key for s in report.ranked] == ["lead-b", "lead-c", "lead-a"]
    # per-contact score/confidence/why all carried through
    top = report.ranked[0]
    assert top.score == 90 and top.confidence == 0.8 and top.why == "fake"
    # claw never sends directly; it queued one message + one gated action
    assert report.sent_directly is False
    assert report.message_queued is True
    assert len(out_gate.calls) == 1
    assert out_gate.calls[0]["urgency"] == "normal"
    assert len(approval.calls) == 1
    assert approval.calls[0]["action_type"] == "slack_post"   # outbound → gated
    assert "contact-outreach-rubric" in report.draft_text


def test_no_email_count_surfaced_not_dropped():
    report = run_contact_claw(
        org_id=1, channel="slack:#x",
        contact_reader=FakeContactReader([
            _contact("lead-a", "HasMail", has_email=True),
            _contact("lead-b", "NoMail", has_email=False),
        ]),
        rubric_reader=FakeRubricReader(_rubric()),
        scorer=FakeContactScorer({"lead-a": (30, None), "lead-b": (20, None)}),
        output_gate=RecordingOutputGate(),
        now=NOW,
    )
    assert report.candidate_count == 2      # emailless NOT dropped by default
    assert report.no_email_count == 1
    assert "have no email" in report.draft_text


def test_shortlist_and_overflow_are_reported_not_dropped():
    cfg = ContactClawConfig(max_candidates=2, shortlist_size=1)
    contacts = [_contact("lead-a", "A"), _contact("lead-b", "B"), _contact("lead-c", "C")]
    scorer = FakeContactScorer({"lead-a": (30, None), "lead-b": (20, None)})
    report = run_contact_claw(
        org_id=1, channel="slack:#x",
        contact_reader=FakeContactReader(contacts),
        rubric_reader=FakeRubricReader(_rubric()),
        scorer=scorer,
        output_gate=RecordingOutputGate(),
        config=cfg,
        now=NOW,
    )
    assert report.candidate_count == 3
    assert report.scored_count == 2
    assert report.overflow == 1
    assert len(scorer.called_with) == 2          # cap respected
    assert len(report.ranked) == 1               # shortlist respected
    assert "+1 more" in report.draft_text        # overflow surfaced, not hidden


def test_default_rubric_resolve_points_at_the_decided_abra_home():
    assert default_rubric_resolve(1) == ("claude", "contact-outreach-rubric")
    assert default_rubric_resolve(999) == ("claude", "contact-outreach-rubric")


# --- the reused cheap-model scorer degrades, never crashes ------------------


def test_reused_scorer_falls_back_without_client():
    from src.services.opportunity_claw import AnthropicScorer

    inner = AnthropicScorer(anthropic_client=None)
    if inner.client is not None:
        pytest.skip("ANTHROPIC_API_KEY present; fallback path not exercised")
    scorer = ReusedAnthropicContactScorer(scorer=inner)
    contacts = [_contact("lead-a", "A"), _contact("lead-b", "B")]
    scored = scorer.score_contacts(contacts, _rubric())
    # names carried back from the Contact, not the descriptor
    assert [s.name for s in scored] == ["A", "B"]
    assert [s.contact_key for s in scored] == ["lead-a", "lead-b"]
    # fallback ordering flagged as zero confidence (not a real judgment)
    assert all(s.confidence == 0.0 for s in scored)
    # fallback preserves input order after rank_contacts()
    assert [s.contact_key for s in rank_contacts(scored)] == ["lead-a", "lead-b"]


def test_reused_scorer_flags_zero_confidence_when_underlying_has_no_client():
    """Env-independent cover of the fallback branch: an underlying scorer with
    no client means a deterministic placeholder order → confidence 0.0."""
    from src.services.opportunity_claw import ScoredOpportunity

    class _NoClientScorer:
        client = None

        def score(self, tasks, rubric):
            # deterministic placeholder order, as AnthropicScorer's fallback does
            n = len(tasks)
            return [ScoredOpportunity(task_id=t.id, title=t.title,
                                      score=float(n - i), rationale="[placeholder]")
                    for i, t in enumerate(tasks)]

    scorer = ReusedAnthropicContactScorer(scorer=_NoClientScorer())
    scored = scorer.score_contacts(
        [_contact("lead-a", "A"), _contact("lead-b", "B")], _rubric())
    assert all(s.confidence == 0.0 for s in scored)
    assert scored[0].name == "A"


def test_reused_scorer_maps_model_scores_with_injected_fake_client():
    """With a live client the adapter carries score+rationale through and reports
    confidence=None (uncalibrated), never fabricating a probability."""
    from src.services.opportunity_claw import AnthropicScorer

    class _FakeResp:
        def __init__(self, text):
            self.content = [type("B", (), {"text": text})()]

    class _FakeMessages:
        def create(self, **kw):
            return _FakeResp(
                '[{"task_id": "lead-a", "score": 80, "rationale": "great fit"},'
                ' {"task_id": "lead-b", "score": 40, "rationale": "weak"}]'
            )

    class _FakeClient:
        messages = _FakeMessages()

    inner = AnthropicScorer(anthropic_client=_FakeClient())
    scorer = ReusedAnthropicContactScorer(scorer=inner)
    contacts = [_contact("lead-a", "Alice"), _contact("lead-b", "Bob")]
    scored = {s.contact_key: s for s in scorer.score_contacts(contacts, _rubric())}
    assert scored["lead-a"].score == 80
    assert scored["lead-a"].why == "great fit"
    assert scored["lead-a"].name == "Alice"          # mapped back from Contact
    assert scored["lead-a"].confidence is None       # genuine score, uncalibrated


# --- the Odoo adapter join/normalization (fake search_read, no XML-RPC) -----


def test_strip_html_reduces_comment_to_plain_text():
    assert _strip_html("<p>Hello&nbsp;<b>world</b></p>\n<p>again</p>") == "Hello world again"
    assert _strip_html(None) == ""
    assert _strip_html("") == ""


def test_odoo_contact_reader_joins_lead_partner_tags_campaign():
    calls = []

    def fake_search_read(model, domain, fields=None, limit=None, order=None):
        calls.append((model, domain))
        if model == "crm.lead":
            return [
                {"id": 7, "name": "Opp with Alice",
                 "partner_id": [11, "Alice Smith"],
                 "function": "Ops", "email_from": "",
                 "tag_ids": [2, 3], "campaign_id": [5, "Spring Push"]},
                {"id": 8, "name": "Bare lead",
                 "partner_id": False, "function": False, "email_from": "b@x.io",
                 "tag_ids": [], "campaign_id": False},
            ]
        if model == "res.partner":
            assert ("id", "in", [11]) in domain
            return [{"id": 11, "name": "Alice Smith", "function": "Head of Ops",
                     "comment": "<p>met at <b>conf</b></p>", "email": "alice@x.io"}]
        if model == "crm.tag":
            return [{"id": 2, "name": "priority"}, {"id": 3, "name": "warm"}]
        return []

    reader = OdooContactReader(search_read=fake_search_read)
    contacts = {c.key: c for c in reader.list_contacts(org_id=1)}

    a = contacts["lead-7"]
    assert a.name == "Alice Smith"
    assert a.role == "Head of Ops"          # partner.function wins over lead.function
    assert a.tags == ("priority", "warm")
    assert a.campaign == "Spring Push"
    assert a.note == "met at conf"           # HTML stripped
    assert a.has_email is True

    # a lead with no partner still projects: name falls back to the lead label,
    # has_email comes from email_from
    b = contacts["lead-8"]
    assert b.name == "Bare lead"
    assert b.campaign is None
    assert b.tags == ()
    assert b.has_email is True               # email_from present
    assert b.note == ""


def test_odoo_contact_reader_degrades_on_read_error():
    def boom(model, domain, fields=None, limit=None, order=None):
        raise RuntimeError("CRM down")

    reader = OdooContactReader(search_read=boom)
    assert list(reader.list_contacts(org_id=1)) == []   # degrades, never crashes


def test_odoo_contact_reader_only_reads_opportunities_by_default():
    seen = {}

    def fake_search_read(model, domain, fields=None, limit=None, order=None):
        seen[model] = domain
        return []

    OdooContactReader(search_read=fake_search_read).list_contacts(org_id=1)
    assert ("type", "=", "opportunity") in seen["crm.lead"]
