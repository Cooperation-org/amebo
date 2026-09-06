"""Tools over the org's importance rubric (src/services/rubric.py).

``read_rubric`` is free. ``set_rubric`` changes what every person in the org
sees at the top of their list, so it is gated: the claw drafts the change with
a preview and a human approves it (docs/DRAFT_APPROVAL_GATE.md)."""
from __future__ import annotations

from typing import Any, Dict

from src.services.rubric import Rubric
from src.tools.gated_actuators import _ctx_org_id, _route_through_gate

_WEIGHTS = ("someone_waiting", "contact_interested", "money", "owned",
            "picked_up", "new", "no_detail", "quiet_fade", "quiet_max",
            "stage_step", "quiet_cap")

READ_RUBRIC_SCHEMA = {"type": "object", "properties": {}, "required": []}

SET_RUBRIC_SCHEMA = {
    "type": "object",
    "properties": {
        "focus": {"type": "string",
                  "description": "What matters to this team, in their own words. "
                                 "Shown, never scored."},
        "judgement": {"type": "string",
                      "description": "Instructions a model applies when ordering the undated rows, "
                                     "in the team's words ('a warm intro cooling beats a cold lead'). "
                                     "Hard signals still set the band; this moves rows inside it."},
        "top_n": {"type": "integer", "description": "Rows shown in the 'only what matters' view (3-7)."},
        **{w: {"type": "number", "description": f"Weight for signal '{w}'."} for w in _WEIGHTS},
        "why": {"type": "string",
                "description": "One line: what the person said that led to this change."},
    },
    "required": [],
}


def read_rubric_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    org_id = _ctx_org_id(context)
    if org_id is None:
        return "Error: no org in context."
    from src.services.rubric_store import read_rubric
    r = read_rubric(int(org_id))
    return "\n".join(r.describe()) + "\n\nraw: " + str(r.to_dict())


def execute_set_rubric(action: Dict[str, Any]) -> str:
    p = action.get("payload") or {}
    org_id = p.get("org_id")
    changes = p.get("changes") or {}
    if org_id is None or not changes:
        return "Error: cannot set rubric — payload missing org_id or changes."
    from src.services.rubric_store import write_rubric
    stored = write_rubric(int(org_id), changes)
    if stored is None:
        raise RuntimeError("set_rubric failed: no instance for org")
    return "rubric now:\n" + "\n".join(stored.describe())


def set_rubric_impl(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    changes = {k: v for k, v in (tool_input or {}).items()
               if k in Rubric().to_dict() and v is not None}
    if not changes:
        return "Error: nothing to change — give focus, top_n or a weight."
    org_id = _ctx_org_id(context)
    why = (tool_input.get("why") or "").strip()
    preview_bits = [f"{k}={v}" for k, v in changes.items() if k != "focus"]
    if "focus" in changes:
        preview_bits.insert(0, f"focus: {changes['focus'][:80]}")
    preview = "Rubric: " + ", ".join(preview_bits) + (f" — {why}" if why else "")
    return _route_through_gate(
        action_type="set_rubric", context=context, target=f"org:{org_id}",
        payload={"org_id": org_id, "changes": changes, "why": why},
        preview=preview, executor=execute_set_rubric,
    )
