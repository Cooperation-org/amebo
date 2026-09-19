"""Prompt layers shared by every path that talks to a model.

Rules (``prompts/rules.md``) and the two catalogs, shapes (``prompts/shapes``)
and skills (``prompts/skills``). One builder for live chat and for claws, so the
two triggers never fork (docs/BOUNDARIES.md, "one engine, two triggers").

A shape is the form of an output; a skill is how to do a kind of work. Each is
a self-contained markdown file with frontmatter, readable outside amebo. An
org's overlay (``<context repo>/shapes``, ``<context repo>/skills``) shadows the
packaged file of the same name.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from src.services.skill_files import core_dir, org_dir, read_skills

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

# Read-only tools that fetch prompt layers. Offered on every path regardless of
# an instance's or goal's allowed_tools: they are knowledge, not actions.
PROMPT_LAYER_TOOLS = frozenset({"load_skill", "list_skills", "load_shape", "list_shapes"})

_HEADERS = {
    "shapes": (
        "**Shapes.** Every output to a person takes a shape. Call "
        "`load_shape(name)` for the one that fits before writing the answer:"
    ),
    "skills": (
        "**Available skills.** When one fits the request, call "
        "`load_skill(name)` to load its full instructions before answering. "
        "You may load more than one and combine them with other tools:"
    ),
}


def rules_text() -> str:
    """The always-on rules, from the file. Empty string if it is missing."""
    try:
        return (PROMPTS_DIR / "rules.md").read_text().strip()
    except OSError:
        logger.warning("prompts/rules.md missing")
        return ""


def catalog(kind: str, org_id: Optional[int] = None) -> str:
    """Short catalog (name: description) of one kind, org overlay first."""
    items = read_skills([org_dir(kind, org_id), core_dir(kind)])
    if not items:
        return ""
    lines = [_HEADERS[kind]]
    for s in items:
        if s.get("name"):
            lines.append(f"- {s['name']}: {s.get('description', '')}")
    return "\n".join(lines)


def layers(org_id: Optional[int] = None) -> str:
    """Rules, then the shapes catalog, then the skills catalog."""
    parts = [rules_text(), catalog("shapes", org_id), catalog("skills", org_id)]
    return "\n\n".join(p for p in parts if p)
