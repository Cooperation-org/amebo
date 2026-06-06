# Draft-Approval Gate

Human-in-the-loop approval for the claw. This is the implementation of open
question #4 in `ORGS_GOALS_CLAW.md` ("claw drafts a message, human approves
before send").

## Why

A background claw runs unsupervised. It must never take an irreversible
OUTBOUND or DESTRUCTIVE action (send a Slack message, send email, write to
CRM/Taiga, open or merge a PR) without a human approving first. Read-only and
internal/reversible actions are not gated and run immediately.

## Pieces

| Piece | File |
|---|---|
| `pending_actions` table | `backend/migrations/015_pending_actions.sql` |
| Gated-vs-free registry | `backend/src/services/gated_actions.py` |
| Persistence | `backend/src/db/repositories/pending_action_repo.py` |
| Service + gate | `backend/src/services/draft_approval_service.py` |
| REST API | `backend/src/api/routes/pending_actions.py` |
| Tests | `backend/tests/test_gated_actions.py`, `backend/tests/test_draft_approval_service.py` |

## Classification (`gated_actions.py`)

`requires_approval(action_type)` is **default-deny**: anything not explicitly
in `FREE_ACTIONS` is gated. Action types line up with tool names in
`src/tools/registry.py`. `edit_main_md` is FREE because it writes only to a
local working tree and lands uncommitted (a human reviews via `git diff`);
`slack_post`, `send_email`, `odoo_cli`, `mcp_taiga`, `open_pr`, `merge_pr` are
GATED. A new, unclassified action type is gated until someone vouches for it.

## The gate (`draft_approval_service.py`)

```python
svc = DraftApprovalService(notifier=my_slack_notifier)  # notifier optional
result = svc.gate_or_execute(
    org_id=goal["org_id"],
    action_type="slack_post",
    acting_identity="amebo:whats-cookin",   # or a person author URI
    executor=do_the_slack_post,             # called only if FREE
    target="#general",
    payload={"text": "...", "notify_channel": "slack:#approvals"},
    preview="Post a status update to #general",
    instance_id=instance["id"],
    goal_id=goal["id"],
)
# FREE  → result.executed is True, result.result holds the executor output.
# GATED → result.gated is True, a pending_actions row was created and a human
#         was notified; nothing was sent.
```

On approval, the service does NOT send anything. `approve()` transitions
`pending → approved` and returns the row; the caller/executor then performs the
side effect (e.g. via `execute_approved(action_id, org_id, executor)`, which
runs the executor and transitions to `executed`/`failed`). Execution stays
pluggable — the service never imports a channel or tool.

## Dispatcher integration point (ONE place)

The live dispatcher is **not** rewired here (additive-only). The single place
to call the gate is inside `GoalDispatcher._run_agentic_loop`
(`backend/src/services/goal_dispatcher.py`), right where a tool is about to be
executed:

```python
# in _run_agentic_loop, replacing the direct `tool.execute(tool_input, ctx)`:
from src.services.draft_approval_service import DraftApprovalService

gate = DraftApprovalService(notifier=self._notify)
gate_result = gate.gate_or_execute(
    org_id=goal["org_id"],
    action_type=name,                       # the tool name
    acting_identity=f"amebo:{org_slug}",    # autonomous claw identity
    executor=lambda _a: tool.execute(tool_input, ctx) or "",
    target=tool_input.get("channel") or tool_input.get("to"),
    payload=tool_input,
    preview=f"{name} requested by claw for goal {goal['title']}",
    instance_id=(instance or {}).get("id"),
    goal_id=goal["id"],
)
if gate_result.gated:
    # Tell the model the action is pending human approval; do NOT treat as done.
    result_text = (
        f"[held for approval] {name} requires human approval before it runs. "
        f"Pending action {gate_result.pending_action['id']} created."
    )
    is_error = False
else:
    result_text = gate_result.result or ""
    is_error = result_text.startswith("Error:")
```

Free (read-only/internal) tools execute exactly as before; only gated tools are
intercepted. This is the entire integration — no other dispatcher change.

## Router registration (deferred)

`pending_actions.py` exposes `router`. Wiring it into the app requires editing
`src/api/main.py`, which is locked while OAuth/SSO work is mid-flight. The
OAuth/SSO session owners should add these two lines alongside the existing
`goals` registration:

```python
from src.api.routes import pending_actions          # in the import list
app.include_router(
    pending_actions.router, prefix="/api/pending-actions", tags=["Pending Actions"],
)
```

Until then the router is inert (defined, not mounted). No behavior changes for
the running service.

## Migration

`015_pending_actions.sql` is a FILE only — not applied to any database here.
Apply it through the normal migration path (init_db / migration runner) when
the feature is being deployed. Rollback: `DROP TABLE IF EXISTS pending_actions;`
