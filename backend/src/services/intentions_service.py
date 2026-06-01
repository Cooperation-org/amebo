"""
Intentions service — propose and commit placements in abra.

Drives the <amebo-create-goal> embed component. Takes free-text from the
user, asks Anthropic to propose where it belongs in abra (name, content
summary, labels, optional cron for clawable goals), returns a structured
proposal. A second call commits the proposal: writes the abra side via
AbraWriter, optionally creates an amebo goal and stamps the `RUN_BY`
binding linking the two.

Architecture:
  - abra is the map. amebo holds no copy of it.
  - amebo writes to abra via AbraWriter (imported from the abra repo
    on the shared dev VM at /opt/shared/repos/abra/impl/pgvector).
  - A "clawable goal" is a name in abra labeled `goal` AND bound to
    `amebo:claw/<goal-uuid>` via the RUN_BY relationship. amebo's
    goals table has a matching row whose config.abra_ref points back.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

# AbraWriter lives in the abra repo; this VM has both repos at well-known
# paths. Add it to sys.path lazily so a missing repo doesn't crash import.
_ABRA_IMPL = "/opt/shared/repos/abra/impl/pgvector"
if _ABRA_IMPL not in sys.path:
    sys.path.insert(0, _ABRA_IMPL)

logger = logging.getLogger(__name__)


# ── proposal shape ────────────────────────────────────────────────────────

@dataclass
class Proposal:
    """What amebo proposes for the free text input."""
    scope: str
    name: str                        # the pet name, slug-style
    name_is_new: bool                # True if the name doesn't exist in scope yet
    content_summary: str             # text to store as the content blob (her words by default)
    labels: List[str]                # e.g. ["goal", "hot"]
    make_clawable: bool              # if True, amebo will create a goal record on commit
    cron: Optional[str]              # cron expression when clawable + scheduled, else None
    title: str                       # short title for the goal (only used if clawable)
    description: str                 # longer description for the goal record
    reasoning: str                   # short note explaining the placement

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": self.scope,
            "name": self.name,
            "name_is_new": self.name_is_new,
            "content_summary": self.content_summary,
            "labels": self.labels,
            "make_clawable": self.make_clawable,
            "cron": self.cron,
            "title": self.title,
            "description": self.description,
            "reasoning": self.reasoning,
        }


# ── prompts ───────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You help Golda place a free-text thought into her abra map.

abra holds her brain extension: names (pet-name handles) bound to content
blobs, labels (hot, goal), and URIs. A "clawable goal" is a name marked
with label `goal` AND bound by `RUN_BY` to an `amebo:claw/<uuid>` URI;
amebo's claw loop will then act on it on a schedule.

Your job: read her input, look at her existing names (provided below
as context), and propose how to place this thought. Be conservative —
prefer extending an existing name when she's clearly continuing prior
work; create a new name when she's starting something new.

Output STRICT JSON with these keys (no extra text, no markdown fence):
  name              kebab-case slug; existing if extending, new if fresh
  name_is_new       boolean
  content_summary   her words, lightly cleaned (no fabrication)
  labels            small list, e.g. ["goal"], ["goal","hot"], or []
  make_clawable     true ONLY if she clearly wants amebo to actively work on it
  cron              cron expression if recurring (e.g. "0 9 * * 1" for weekly Mon 9am), else null
  title             short title (10 words max) if clawable, else ""
  description       short description (1-2 sentences) if clawable, else ""
  reasoning         one sentence on the placement choice

Defaults:
  - scope is `golda` unless told otherwise
  - if she doesn't mention scheduling, cron is null and the goal (if any) is manual
  - if you're unsure between two names, prefer extending an existing one
  - keep `content_summary` close to her words; do not over-summarize
"""


def _build_user_message(text: str, scope: str, existing_names: List[str],
                         name_hint: Optional[str]) -> str:
    lines = [f"Scope: {scope}"]
    if name_hint:
        lines.append(f"Extending existing name: {name_hint}")
        lines.append("(name_is_new must be false; use this exact name.)")
    if existing_names:
        lines.append("")
        lines.append("Existing names in scope (sample):")
        for n in existing_names[:60]:
            lines.append(f"  - {n}")
    lines.append("")
    lines.append("Her free-text input:")
    lines.append(text.strip())
    lines.append("")
    lines.append("Return the JSON now.")
    return "\n".join(lines)


# ── service ───────────────────────────────────────────────────────────────

class IntentionsService:
    """Propose + commit intentions placements."""

    def __init__(self, anthropic_client: Optional[Anthropic] = None):
        if anthropic_client is not None:
            self.client = anthropic_client
        else:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            self.client = Anthropic(api_key=api_key) if api_key else None

    # ---- propose ---------------------------------------------------------

    def propose(self, text: str, scope: str = "golda",
                name: Optional[str] = None,
                feedback: Optional[str] = None) -> Proposal:
        """Produce a placement proposal for free text. `feedback` is
        prior free-text correction from the user; we feed it back so the
        next proposal incorporates it."""
        text = (text or "").strip()
        if not text:
            raise ValueError("text must not be empty")

        existing = self._existing_names(scope)
        user_message = _build_user_message(text, scope, existing, name)
        if feedback:
            user_message += f"\n\nUser feedback on the previous proposal:\n{feedback.strip()}"

        if self.client is None:
            # mock proposal so the route still works without ANTHROPIC_API_KEY
            return self._mock_proposal(text, scope, name)

        try:
            resp = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            raw = resp.content[0].text if resp.content else ""
        except Exception as e:
            logger.warning("Anthropic call failed, falling back to mock: %s", e)
            return self._mock_proposal(text, scope, name)

        return self._parse_proposal(raw, text, scope, name)

    def _existing_names(self, scope: str) -> List[str]:
        """Top names by binding count in scope. Best-effort; empty on failure."""
        try:
            from src.db.abra_connection import AbraConnection
        except Exception:
            return []
        if not AbraConnection.is_available():
            return []
        conn = AbraConnection.get_connection()
        if conn is None:
            return []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT name FROM bindings
                       WHERE scope = %s
                       GROUP BY name
                       ORDER BY COUNT(*) DESC
                       LIMIT 60""",
                    (scope,)
                )
                return [row[0] for row in cur.fetchall()]
        except Exception as e:
            logger.warning("Could not load existing names: %s", e)
            return []
        finally:
            AbraConnection.return_connection(conn)

    def _parse_proposal(self, raw: str, text: str, scope: str,
                         name_hint: Optional[str]) -> Proposal:
        """Parse the model's JSON response into a Proposal. Tolerant of
        accidental markdown fences."""
        raw = raw.strip()
        # strip ```json fences if present
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        payload_str = m.group(0) if m else raw
        try:
            data = json.loads(payload_str)
        except json.JSONDecodeError as e:
            logger.warning("Could not parse proposal JSON, using mock. raw=%s err=%s", raw[:300], e)
            return self._mock_proposal(text, scope, name_hint)

        return Proposal(
            scope=scope,
            name=str(data.get("name") or name_hint or "untitled").strip() or "untitled",
            name_is_new=bool(data.get("name_is_new", name_hint is None)),
            content_summary=str(data.get("content_summary") or text).strip(),
            labels=[str(x).strip() for x in (data.get("labels") or []) if str(x).strip()],
            make_clawable=bool(data.get("make_clawable", False)),
            cron=(str(data.get("cron")).strip() if data.get("cron") else None),
            title=str(data.get("title") or "").strip(),
            description=str(data.get("description") or "").strip(),
            reasoning=str(data.get("reasoning") or "").strip(),
        )

    def _mock_proposal(self, text: str, scope: str,
                        name_hint: Optional[str]) -> Proposal:
        """No-LLM fallback. Slug from first words; everything else minimal."""
        if name_hint:
            name = name_hint
            is_new = False
        else:
            words = re.findall(r"[a-z0-9]+", text.lower())
            name = "-".join(words[:3]) if words else "untitled"
            is_new = True
        return Proposal(
            scope=scope, name=name, name_is_new=is_new,
            content_summary=text, labels=[],
            make_clawable=False, cron=None,
            title="", description="",
            reasoning="(mock: no Anthropic key; using a slug from your words.)",
        )

    # ---- commit ----------------------------------------------------------

    def commit(self, proposal: Proposal, *,
                user_writer_uri: str,
                org_id: int,
                created_by_user_id: Optional[int] = None) -> Dict[str, Any]:
        """Apply the proposal: write abra side via AbraWriter; if clawable,
        create the amebo goal and stamp the RUN_BY binding.

        Returns: { scope, name, content_id, goal_id (or None), bindings_written }
        """
        from write_binding import AbraWriter  # imported via sys.path above

        dsn = os.getenv("ABRA_DATABASE_URL")
        if not dsn:
            raise RuntimeError("ABRA_DATABASE_URL is not set; cannot write to abra")

        writer = AbraWriter(writer_uri=user_writer_uri, dsn=dsn)
        bindings_written = 0
        goal_id: Optional[str] = None

        try:
            # 1. store content blob with her summary
            content_id = writer.store_content(
                source_file=f"intentions:{proposal.name}",
                content=proposal.content_summary,
                note_date=None,
                catcode=None,
            )

            # 2. ABOUT binding from name → content
            writer.write_binding(
                proposal.scope, proposal.name,
                rel="ABOUT", target_type="content",
                target_ref=str(content_id),
                qualifier="intent",
                permanence="CURRENT",
            )
            bindings_written += 1

            # 3. labels
            for label in proposal.labels:
                writer.set_label(proposal.scope, proposal.name, label)

            # 4. clawable goal — create amebo goal AND stamp RUN_BY binding
            if proposal.make_clawable:
                trigger_config: Dict[str, Any] = {"type": "manual"}
                if proposal.cron:
                    trigger_config = {"type": "cron", "expression": proposal.cron}

                # local import to avoid circular wiring at module load
                from src.services.goal_engine import GoalEngine
                engine = GoalEngine()
                goal = engine.create_goal(
                    org_id=org_id,
                    title=proposal.title or proposal.name,
                    description=proposal.description or proposal.content_summary,
                    target_criteria=None,
                    trigger_config=trigger_config,
                    notify_channel=None,
                    created_by_user_id=created_by_user_id,
                    config={
                        "abra_ref": {
                            "scope": proposal.scope,
                            "name": proposal.name,
                        }
                    },
                )
                goal_id = goal["id"]

                # RUN_BY binding pointing back into the goal — this is the
                # marker that makes the abra-side name a "clawable goal."
                writer.write_binding(
                    proposal.scope, proposal.name,
                    rel="RUN_BY", target_type="uri",
                    target_ref=f"amebo:claw/{goal_id}",
                    permanence="CURRENT",
                )
                bindings_written += 1

            return {
                "scope": proposal.scope,
                "name": proposal.name,
                "content_id": content_id,
                "goal_id": goal_id,
                "bindings_written": bindings_written,
                "labels_set": list(proposal.labels),
            }
        finally:
            writer.close()
