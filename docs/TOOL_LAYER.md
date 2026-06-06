# Amebo Tool Layer — Eyes and Hands

Amebo's tool layer is split into two kinds of capability, by intent:

- **Eyes (read tools)** — side-effect-free lookups. Ungated. Run immediately.
- **Hands (gated actuators)** — outbound/destructive actions. Every one routes
  through the existing draft-approval gate; nothing is sent without human
  approval.

This is additive: new adapter modules plus appended registrations in
`backend/src/tools/registry.py`. No existing tool, gate, or route was rewritten.

## The tools

| Tool | Kind | Module | Gated? | CLI it shells to |
|---|---|---|---|---|
| `odoo_search` | eyes | `cli_read_tools.py` | no (FREE) | `odoo-cli search contacts\|leads "<q>"` |
| `crm_read_latest_email` | eyes | `cli_read_tools.py` | no (FREE) | `odoo-cli show contact <sender>` † |
| `abra_search` | eyes | `cli_read_tools.py` | no (FREE) | `abra search\|about "<q>"` |
| `taiga_list` | eyes | `cli_read_tools.py` | no (FREE) | `mcp-taiga list [project]` |
| `taiga_create_task` | hands | `gated_actuators.py` | **yes** | `mcp-taiga create <subject> …` † (only after approval) |
| `slack_post_gated` | hands | `gated_actuators.py` | **yes** | reuses `slack_tools.slack_post_impl` (only after approval) |

† TODO markers in the code where a real CLI subcommand/flag is not yet
confirmed. All such cases fail safe — a read returns empty/erroring output, and
a write subprocess only ever runs after human approval, never speculatively.

## How read vs. gated compose with `allowed_tools`

Two independent gates apply to every tool, in order:

1. **`allowed_tools` (coarse, per-instance).** `registry.get_tools_for_instance`
   only emits a tool's schema to the model if the tool name is in the
   instance's `config.allowed_tools` (or the default set). A tool not allowed
   for an instance is never described to the model and never executed —
   `cli_read_tools` and `gated_actuators` are subject to exactly the same
   filtering as every other registered tool. (`goal_guardrails.permit_tool`
   enforces the same allow-list at claw execution time.)

2. **The draft-approval gate (fine, per-action).** Independently of which
   tools exist for an instance, the *outbound* ones cannot fire without
   approval. The actuator calls
   `DraftApprovalService.gate_or_execute(action_type=<tool name>, …)`. Because
   the action type equals the gated tool name, `gated_actions.requires_approval`
   returns True (it is default-deny and the names are listed in
   `GATED_ACTIONS`), so the gate records a `pending_action`, notifies a human,
   and returns **without** running the side effect. The actuator reports the
   pending action back to the model as `[held for approval]`.

Read tools skip step 2 entirely — they are listed in `FREE_ACTIONS`, perform no
side effect, and the dispatcher/QA loop runs them inline.

## Reusing the existing gate (not a new one)

The actuators do not implement any approval logic of their own. They:

- build the real side effect as an `executor` closure (Slack post / Taiga
  create), and
- hand it to `DraftApprovalService.gate_or_execute`.

For a gated action the gate **never calls the executor**; it creates the draft.
The closure is still passed so that the *same* gate would execute it if the
action were ever reclassified FREE — the actuator never branches around the
gate. The deferred side effect runs later only via
`DraftApprovalService.execute_approved(action_id, org_id, executor)`, which the
API/dispatcher invokes on human approval. Execution stays pluggable; this module
imports no channel/route, only the gate service.

`org_id` for the gate comes from the tool `context` (the same `org_id` the read
tools and goal-introspection tools receive). Without an org context the actuator
refuses rather than acting under an ambiguous identity. The acting identity is
stamped `urn:amebo:user:<principal>` for a delegated turn or `amebo:<org_id>`
for a background claw, following the credential-helper conventions.

## Subprocess discipline

All CLI calls use `cli_read_tools.run_cli`: list args, `shell=False`, an
explicit timeout, stdout captured, stderr surfaced on non-zero exit, missing
executable handled. No string is pre-joined and re-split, so there is no
word-splitting on input and no shell-injection surface.

## Tests

`backend/tests/test_tool_layer.py` (subprocess and the gate fully mocked — no
real CLI, Slack, Taiga, or DB):

- read tools invoke the right CLI with the right argv;
- gated actuators route through the gate, creating a `pending_action` and
  **not** performing the side effect;
- a tool not in `allowed_tools` is never exposed by
  `get_tools_for_instance` and never executed.

Run: `cd backend && python -m pytest tests/test_tool_layer.py -q`
