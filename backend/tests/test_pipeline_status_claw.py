"""Tests for the pipeline-status claw (pipeline-hygiene digest).

Pure-core tests: the reader, gate, and dedup are injected, so nothing here
touches Odoo, Slack, or the database.
"""

from src.services.pipeline_status_claw import (
    classify,
    build_digest,
    run_pipeline_status,
)

TODAY = "2026-06-26"


def _lead(name, *, lead_id=42, activity=None, write="2026-06-26", stage="Qualified",
          owner="golda", rev=0):
    return {
        "id": lead_id,
        "name": name,
        "activity_date_deadline": activity,
        "write_date": f"{write} 09:00:00",
        "stage_id": [3, stage] if stage else False,
        "user_id": [1, owner] if owner else False,
        "expected_revenue": rev,
    }


# --- classify ---------------------------------------------------------------

def test_no_activity_is_no_next_step():
    buckets = classify([_lead("A", activity=None)], today=TODAY, stale_days=14)
    assert [l["name"] for l in buckets["no_next_step"]] == ["A"]
    assert buckets["stale"] == []


def test_old_write_with_activity_is_stale():
    buckets = classify([_lead("B", activity="2026-07-01", write="2026-06-01")],
                       today=TODAY, stale_days=14)
    assert [l["name"] for l in buckets["stale"]] == ["B"]
    assert buckets["no_next_step"] == []


def test_recent_with_activity_is_clean():
    buckets = classify([_lead("C", activity="2026-06-30", write="2026-06-25")],
                       today=TODAY, stale_days=14)
    assert buckets["no_next_step"] == [] and buckets["stale"] == []


def test_no_next_step_takes_precedence_over_stale():
    # No activity AND old write -> listed once, under no_next_step only.
    buckets = classify([_lead("D", activity=None, write="2026-01-01")],
                       today=TODAY, stale_days=14)
    assert [l["name"] for l in buckets["no_next_step"]] == ["D"]
    assert buckets["stale"] == []


# --- digest -----------------------------------------------------------------

def test_clean_pipeline_yields_no_digest():
    assert build_digest({"no_next_step": [], "stale": []},
                        today=TODAY, stale_days=14) is None


def test_digest_counts_both_buckets():
    buckets = {"no_next_step": [_lead("A", activity=None)],
               "stale": [_lead("B", activity="x", write="2026-01-01")]}
    msg = build_digest(buckets, today=TODAY, stale_days=14)
    # Both counts in the summary; priority bucket (no-next-step) is sampled.
    assert "no next step" in msg and "gone quiet" in msg.lower()
    assert "A" in msg


def test_digest_lines_have_clickable_escaped_links():
    buckets = {"no_next_step": [_lead("A", lead_id=99, activity=None)], "stale": []}
    msg = build_digest(buckets, today=TODAY, stale_days=14)
    # Slack link syntax with ampersands escaped so the deep-link isn't truncated.
    assert "<https://crm.linkedtrust.us/web#id=99&amp;model=crm.lead&amp;view_type=form|A>" in msg
    assert "&model=" not in msg  # no raw ampersands left in the URL


def test_digest_samples_and_links_the_rest():
    many = [_lead(f"L{i}", lead_id=i, activity=None) for i in range(12)]
    msg = build_digest({"no_next_step": many, "stale": []}, today=TODAY, stale_days=14)
    assert "*12* with no next step" in msg
    assert "and 7 more in the CRM" in msg  # 12 - SAMPLE_SIZE(5)


# --- run (injected reader / gate / dedup) -----------------------------------

class _Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, channel, text, key):
        self.calls.append({"channel": channel, "text": text, "key": key})
        return "drafted"


def test_run_drafts_one_gated_digest():
    gate = _Spy()
    leads = [_lead("A", activity=None), _lead("B", activity="x", write="2026-01-01")]
    summary = run_pipeline_status(
        1, "#sales",
        reader=lambda: leads, gate=gate,
        already_drafted=lambda key: False, today=TODAY,
    )
    assert summary["drafted"] == 1
    assert len(gate.calls) == 1  # ONE digest, never one-per-deal
    assert gate.calls[0]["channel"] == "#sales"


def test_run_no_channel_is_noop():
    gate = _Spy()
    summary = run_pipeline_status(1, "", reader=lambda: [_lead("A")], gate=gate,
                                  already_drafted=lambda key: False, today=TODAY)
    assert summary["drafted"] == 0 and summary["reason"] == "no_channel"
    assert gate.calls == []


def test_run_dedups_same_day():
    gate = _Spy()
    summary = run_pipeline_status(
        1, "#sales", reader=lambda: [_lead("A", activity=None)], gate=gate,
        already_drafted=lambda key: True, today=TODAY,
    )
    assert summary["drafted"] == 0 and summary["reason"] == "already_drafted"
    assert gate.calls == []


def test_run_clean_pipeline_drafts_nothing():
    gate = _Spy()
    summary = run_pipeline_status(
        1, "#sales", reader=lambda: [_lead("C", activity="2026-06-30", write="2026-06-25")],
        gate=gate, already_drafted=lambda key: False, today=TODAY,
    )
    assert summary["drafted"] == 0 and summary["reason"] == "clean"
    assert gate.calls == []


def test_run_read_failure_is_handled():
    def boom():
        raise RuntimeError("odoo down")
    gate = _Spy()
    summary = run_pipeline_status(1, "#sales", reader=boom, gate=gate,
                                  already_drafted=lambda key: False, today=TODAY)
    assert summary["drafted"] == 0 and summary["reason"] == "read_failed"
    assert gate.calls == []
