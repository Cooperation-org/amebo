"""
hot_tags tool — surface an org's priority items so the model knows what
matters now without scanning the whole knowledge base.

Backed by abra's hot_tags table, scoped via the calling org's id.
"""

from __future__ import annotations

from typing import Any, Dict

from src.db.repositories.binding_repo import BindingRepo


def list_hot_tags(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    org_id = context.get("org_id")
    if not org_id:
        return "Error: no org context available."

    scope = tool_input.get("scope") or None

    repo = BindingRepo(org_id=org_id)
    try:
        tags = repo.get_hot_tags(scope=scope) or []
    except Exception as exc:
        return f"Error: could not read hot tags — {exc}"

    if not tags:
        scope_note = f" (scope={scope})" if scope else ""
        return f"No hot tags for this org{scope_note}."

    lines = ["Hot tags (priority items):"]
    for t in tags[:50]:
        scope_label = t.get("scope") or "—"
        priority = t.get("priority", 0)
        added = t.get("added_at")
        added_iso = added.isoformat() if hasattr(added, "isoformat") else str(added)
        lines.append(f"  - {t['name']}  [scope={scope_label}, priority={priority}, added={added_iso}]")
    return "\n".join(lines)


LIST_HOT_TAGS_SCHEMA = {
    "type": "object",
    "properties": {
        "scope": {
            "type": "string",
            "description": (
                "Optional scope filter (e.g. 'linkedtrust', 'project'). "
                "Omit to return all scopes."
            ),
        },
    },
    "required": [],
}
