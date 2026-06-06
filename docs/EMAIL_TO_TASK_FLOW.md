# Email-to-Task Flow

The flagship near-term claw use case, in Golda's own words:

> "We got an email, I copied it to the CRM. Make the task and tell people in
> Slack."

A human forwards an email into the CRM. The claw reads the latest forwarded
email from a given sender, crystallizes it into a Taiga task, and notifies the
right Slack channel. **Neither the task-create nor the Slack post is sent blind**
— both are held as approval DRAFTS routed through the draft-approval gate, and
the Slack notification additionally passes the human-output gate so it stays
concise. A human approves before anything reaches Taiga or Slack.

## Where it lives

| Piece | File |
|---|---|
| Flow / claw | `backend/src/services/email_to_task_flow.py` |
| Tests (fakes only, no DB) | `backend/tests/test_email_to_task_flow.py` |

Additive and new-files-only. Nothing in `registry.py`, `auth.py`,
`slack_oauth.py`, `main.py`, or the existing gate services was touched.

## The flow

```python
process_latest_forwarded_email(
    *,
    sender,            # whose forwarded email to read
    slack_channel,     # INPUT/config — never hardcoded
    org_id,            # org whose CRM/Taiga/Slack/approval-queue this acts in
    readers,           # CrmEmailReader  (read-only seam)
    task_creator,      # TaskCreator     (executor, run only AFTER approval)
    notifier,          # Notifier        (executor, run only AFTER approval)
    gate,              # ApprovalGate    (DraftApprovalService in prod)
    output_gate=None,  # OutputGate      (HumanOutputGate in prod)
    acting_identity,   # who the draft is stamped as, e.g. "amebo:<team>"
    instance_id=None,
    goal_id=None,
) -> FlowResult
```

Steps:

1. **Read** the latest forwarded email from `sender` via the injected
   `CrmEmailReader` (read-only → not gated). No email → clean no-op.
2. **Crystallize** the email into a `DraftedTask` (title + description + source
   link back to the CRM record). Deterministic; offline-safe.
3. **Draft the task**: route a `mcp_taiga` create through
   `gate.create_pending_action` → a `pending_action` awaiting approval. The task
   is NOT created directly.
4. **Notify Slack**: run the message through the human-output gate first
   (dedup / rate-limit / crystallize), then draft a `slack_post` through the
   approval gate. If the output gate withholds the message (duplicate /
   over-noise / deferred to the daily stand-up), no Slack draft is queued; the
   task draft still stands.

`FlowResult` returns the email read, the `DraftedTask`, and the ids of the
pending_actions created. **The flow performs NO direct side effect** — every
outbound action is a gated draft.

## How outbound is gated (both actions)

Both `mcp_taiga` (task-create) and `slack_post` are in
`gated_actions.GATED_ACTIONS` (and default-deny would gate them anyway). The
flow calls `gate.create_pending_action(...)` directly rather than
`gate_or_execute(...)`, because for this flow both actions must ALWAYS become a
draft and must NEVER execute inline — there is no "free" path here. A human
approves each pending_action, after which the gate runs the injected executor
(`task_creator.create_task` / `notifier.notify`) via the service's
`execute_approved`. The executors are bound at the call site so this module
imports no channel, CRM, or Taiga client.

## How it composes with the two gates

```
email ──read(CRM, read-only)──▶ crystallize ──▶ DraftedTask
                                                 │
                          ┌──────────────────────┴───────────────────────┐
                          ▼                                               ▼
                 draft-approval gate                          human-output gate
                 (action gate: mcp_taiga)                     (message gate)
                          │                                               │
                          ▼                                               ▼
                 pending_action (task)                    SEND/DEFER/SUPPRESS
                                                                          │ SEND
                                                                          ▼
                                                          draft-approval gate
                                                          (action gate: slack_post)
                                                                          │
                                                                          ▼
                                                          pending_action (slack)
```

The two gates are siblings (see `docs/DRAFT_APPROVAL_GATE.md` and
`docs/OUTPUT_GATE.md`): the action gate decides whether an outbound thing
happens at all; the message gate decides whether/how to say it. The Slack
notification passes through BOTH — output gate first (so the text a human
approves is already concise), then the approval gate (so it is held as a draft).

## Injection seams (Protocols) and where real adapters attach

The flow depends only on Protocols; concrete clients attach at the call site.
Each carries a `TODO(...)` in the source marking where the real adapter goes.

| Seam | Production implementation | TODO marker | Gated? |
|---|---|---|---|
| `CrmEmailReader.latest_forwarded_from` | Odoo read of the forwarded `mail.message`, scoped read-only | `TODO(crm-adapter)` | No (read-only) |
| `TaskCreator.create_task` | the `mcp_taiga` tool create | `TODO(taiga-adapter)` | Yes — run only after approval |
| `Notifier.notify` | the existing Slack send path | `TODO(slack-adapter)` | Yes — run only after approval |
| `ApprovalGate.create_pending_action` | `DraftApprovalService` | — (already exists) | — |
| `OutputGate.gate` | `HumanOutputGate` | — (already exists) | — |

`DraftApprovalService.create_pending_action` and `HumanOutputGate.gate` already
match the `ApprovalGate` / `OutputGate` Protocols, so production wiring is just
passing the real instances. The CRM/Taiga/Slack adapters are the only NEW
adapters to build, and they wrap tools that already exist in the registry — no
new tool authority.

## Wiring it (no edits to locked files)

The flow is a library function; a goal/scheduler caller composes it. Sketch
(lives wherever a goal is dispatched, NOT in this module):

```python
from src.services.draft_approval_service import DraftApprovalService
from src.services.human_output_gate import HumanOutputGate, register_output_gate_gc
from src.services.email_to_task_flow import process_latest_forwarded_email

gate = DraftApprovalService(notifier=my_slack_notifier)   # approval requests go here
output_gate = HumanOutputGate()
register_output_gate_gc(output_gate)

result = process_latest_forwarded_email(
    sender=goal_config["sender"],
    slack_channel=goal["notify_channel"],     # config, never hardcoded
    org_id=goal["org_id"],
    readers=MyCrmReader(...),                  # TODO(crm-adapter)
    task_creator=MyTaigaCreator(...),          # TODO(taiga-adapter)
    notifier=MySlackNotifier(...),             # TODO(slack-adapter)
    gate=gate,
    output_gate=output_gate,
    acting_identity=f"amebo:{org_slug}",       # stamp the actor (BOUNDARIES.md)
    instance_id=instance["id"],
    goal_id=goal["id"],
)
# result.pending_action_ids → the drafts a human now approves.
```

## Tests

`backend/tests/test_email_to_task_flow.py` — pure Python, no DB, no real
CRM/Taiga/Slack. A fake CRM reader supplies the email; a recording gate captures
the drafts; recording executors prove they are NEVER called by the flow; the
real (offline-safe) `HumanOutputGate` exercises the output-gate path.

Run:

```bash
cd backend
python -m pytest tests/test_email_to_task_flow.py -v
```

Covers: email → `DraftedTask` + two gated pending_actions, no side effects;
channel comes from config; empty/no-email is a clean no-op; the Slack
notification passes through the output gate (and is withheld when the gate
suppresses a duplicate).
