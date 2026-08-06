# Contact Claw — preliminary outreach prioritization

The "who should I reach out to first" claw. The direct sibling of
[`OPPORTUNITY_CLAW.md`](OPPORTUNITY_CLAW.md): same machinery, same three injected
Protocols, same gates. It differs only in *what it reads* (CRM outreach contacts,
not unassigned tasks) and in adding a per-contact **confidence** beside the score.

## The problem it solves

A team always knows more people it *could* reach out to than it has hours to
reach. The CRM holds them, but nothing turned that pool into an ordering. This
claw reads the outreach contacts, scores them against a rubric with a cheap
model, and hands a *preliminary ordering* to a human to act on.

## The flow

```
CRM outreach contacts   →  score vs rubric (cheap model)  →  rank  →  gated draft
  (ContactReader)          (Scorer = reused haiku)                    (human
                            rubric from abra (RubricReader)            decides who
                                                                       to contact)
```

- **Candidates** = outreach contacts with a name. `select_candidates()`.
  Contacts with no email are kept by default (the draft says "find an email
  first" and reports the count); set `require_email` to drop them.
- **A contact** = a CRM `crm.lead` **opportunity** joined to its `res.partner`,
  projected to `{name, role/function, tags, campaign, note (partner comment,
  HTML-stripped), has_email}` — see `Contact` in `contact_claw.py`.
- **Rubric** = the org's outreach values operationalized as weighted criteria.
  Lives in **abra**, never in amebo. **No rubric → the claw stays silent and
  ranks nothing** (a ranking without explicit criteria is a hidden judgment).
- **Scorer** = a cheap model (haiku), **reused** from the opportunity claw
  (`AnthropicScorer`) — not rebuilt. Correct *because* the rubric carries the
  judgment and a human decides.
- **Decide** = the existing gates. The SEND is outbound → draft-approval gate
  (default-deny). Who to actually contact is the human's; the claw surfaces, it
  does not send and it never writes scores back to the CRM.

## Boundaries (docs/BOUNDARIES.md)

amebo owns no contact list, no rubric, no outreach queue. The claw READS
contacts (`ContactReader` → CRM), READS the rubric (`RubricReader` → abra, reused
from the opportunity claw), SCORES (`ContactScorer`, which reuses the haiku
scorer). All three are Protocols — real adapters bind to Odoo / abra / Anthropic;
tests inject fakes. The claw performs **no direct side effect**: it returns a
`RankingReport` and routes the message through the gates.

## Skill

`prompts/skills/rank-contacts.md` lets the chat surface invoke the same behavior
("rank our contacts", "who should I reach out to"). One pattern, two triggers
(scheduled claw + chat skill) — same as the opportunity claw.

## Rubric shape in abra

Decided home (unlike the opportunity claw, whose org→rubric convention was still
open): abra name **`contact-outreach-rubric`**, scope **`claude`** — see
`DEFAULT_RUBRIC_SCOPE` / `DEFAULT_RUBRIC_NAME` and `default_rubric_resolve()`.
Content is the same JSON shape the reused `AbraRubricReader` parses:

```json
{"criteria": [
   {"name": "fits our outreach goals", "weight": 2.0, "description": "..."},
   {"name": "reachable / warm",        "weight": 1.5, "description": "..."}
 ],
 "skill_notes": "free-text guidance for the reader"}
```

## Confidence

The reused `AnthropicScorer` emits a score + rationale but **not** a calibrated
per-item confidence. So `ReusedAnthropicContactScorer` reports `confidence=None`
(honest "unknown") for a genuine model score, and `confidence=0.0` when the
underlying scorer has no client and falls back to a deterministic placeholder
order (that order is not a real judgment and says so). This is provenance, not a
fabricated probability. A future scorer that has the model emit a calibrated
confidence can populate real values without touching the claw.

## The Odoo adapter

`contact_reader.OdooContactReader` is the real `ContactReader`, mirroring
`taiga_task_reader.TaigaCliTaskReader`. It reuses the mail poller's `OdooClient`
auth path (XML-RPC to `localhost:8069`, db `linkedtrust_crm`, creds from
`ODOO_API_KEY` / `ODOO_PASSWORD` — a **service / team** credential, never a
per-user god-token). The Odoo `search_read` surface is injected so tests exercise
the lead⋈partner⋈tags⋈campaign join with a fake and never touch a live CRM. A
CRM outage degrades a tick to "no contacts", never a crash.

## Status / wiring

Additive and **not wired to the scheduler** — same state as `opportunity_claw`
and `pm_claw`. To go live it needs the same seam the claws share. The exact
remaining steps (do NOT do these as part of the additive change):

1. **Adapter creds wiring.** Ensure `ODOO_API_KEY` (or `ODOO_PASSWORD`) is
   present in the backend environment for the service identity, then construct
   `OdooContactReader()` (default `search_read` reuses `OdooClient`). If several
   orgs ever share one Odoo, decide the per-org lead scoping (pass a
   `lead_domain`); today an org IS the CRM the adapter points at.
2. **Rubric resolve convention.** Already decided for this claw: construct the
   reused `AbraRubricReader(resolve=default_rubric_resolve)` so it reads
   `contact-outreach-rubric` (scope `claude`). Seed that abra note (JSON criteria
   + `skill_notes`) before the first live pass — no rubric → the claw stays
   silent by design.
3. **Scorer.** `ReusedAnthropicContactScorer()` (reuses `AnthropicScorer`, haiku,
   mock fallback when no `ANTHROPIC_API_KEY`).
4. **Scheduler branch + gated executor.** In a separate change that owns the
   scheduler, add a tick that calls `run_contact_claw(...)` per goal-enabled org,
   passing the shared `HumanOutputGate`, a `DraftApprovalService`, and the gated
   Slack-post executor as `deferred_send` (invoked only on approval). Add the
   skill/claw to the instance's `allowed_tools` if it is exposed as a tool.

## Pieces

| Piece | File |
|---|---|
| Claw + config + projection + report + reused-scorer adapter | `backend/src/services/contact_claw.py` |
| Real `ContactReader` (CRM) adapter | `backend/src/services/contact_reader.py` |
| Chat skill | `backend/prompts/skills/rank-contacts.md` |
| Tests (fakes only) | `backend/tests/test_contact_claw.py` |

No migration, no new table: the claw owns no durable state.

## Tests

`backend/tests/test_contact_claw.py` is pure Python (no Odoo/abra/model/DB). It
injects fake readers, a fake `ContactScorer`, and recording gates, and covers:
candidate selection (nameless dropped, email optional), ranking, no-rubric
silence, gated routing without sending, overflow/shortlist/no-email surfaced not
dropped, the reused scorer's map + fallback-confidence, and the Odoo adapter's
join/normalization + graceful degradation (fake `search_read`).

Run: `python -m pytest tests/test_contact_claw.py -q` from `backend/`.
