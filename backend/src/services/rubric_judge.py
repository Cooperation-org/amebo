"""The judged half of the rubric: a model re-ranks the hard-scored candidates
using the org's ``judgement`` prose.

Hard signals put every item in a band. This step lets the org's own words move
an item inside that band ("a warm intro cooling beats a cold lead", "anything
about the Level Up workshop is first this month"). Invariants the code keeps,
whatever the model says:

- Only judged-band items are touched. A dated row (rank >= CLOCK_FLOOR) is
  never moved; the clock wins.
- A nudge is bounded (``MAX_NUDGE``) and the result stays under
  ``JUDGED_CEILING``.
- Each moved row carries the model's one-line reason, labelled 'judgement'.
- One call per (org, viewer, candidate set), cached for ``TTL`` — never a call
  per page load (docs/DASHBOARD.md). No key, no model, bad JSON: the hard
  order stands, unchanged and unlabelled.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence

from src.services.rubric import Rubric
from src.services.work_list import CLOCK_FLOOR, JUDGED_CEILING, Item, Reason

logger = logging.getLogger(__name__)

MAX_NUDGE = 150.0
CANDIDATES = 25          # how many judged rows the model sees, from the top
TTL = 60 * 60            # seconds a verdict is reused
DEFAULT_MODEL = "claude-sonnet-4-6"

_SYSTEM = (
    "You rank a person's work list for one team. You are given the team's own "
    "words on what matters, the person reading, and candidate rows already "
    "scored by hard rules. Move a row only when the team's words say so. "
    "Reply with JSON only: a list of {\"subject\": ..., \"nudge\": -150..150, "
    "\"why\": \"<= 12 words, the team's terms\"}. Omit rows you would not move."
)

_cache: Dict[str, tuple] = {}
_lock = threading.Lock()


def _key(org_id: Any, viewer: Optional[str], rubric: Rubric,
         items: Sequence[Item]) -> str:
    h = hashlib.sha256()
    h.update(f"{org_id}|{viewer}|{rubric.judgement}|{rubric.focus}".encode())
    for i in items:
        h.update(f"{i.subject}|{round(i.rank)}|{i.reason.label}".encode())
    return h.hexdigest()


def _prompt(rubric: Rubric, viewer: Optional[str], items: Sequence[Item]) -> str:
    rows = []
    for i in items:
        rows.append({
            "subject": i.subject, "title": i.title, "kind": i.kind,
            "why_here": i.reason.label, "assignee": i.assignee,
            "said": (i.quote.who + ": " + i.quote.text[:200]) if i.quote else None,
        })
    return (
        f"Team focus: {rubric.focus or '(none stated)'}\n"
        f"Team judgement rules: {rubric.judgement}\n"
        f"Reader: {viewer or 'unknown'}\n\n"
        f"Candidates (hard order, top first):\n{json.dumps(rows, ensure_ascii=False)}"
    )


def _parse(raw: str) -> List[Dict[str, Any]]:
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [o for o in out if isinstance(o, dict) and o.get("subject")]


def judge(items: Sequence[Item], *, rubric: Rubric, org_id: Any,
          viewer: Optional[str], client: Any = None,
          model: str = DEFAULT_MODEL, now: Optional[float] = None) -> List[Item]:
    """Return the items re-ordered by the org's judgement. Same list back when
    there is no judgement text, no model, or the model fails."""
    items = list(items)
    if not (rubric.judgement or "").strip():
        return items
    judged = [i for i in items if i.rank < CLOCK_FLOOR][:CANDIDATES]
    if not judged:
        return items

    key = _key(org_id, viewer, rubric, judged)
    now = now or time.time()
    with _lock:
        hit = _cache.get(key)
    verdict: Optional[List[Dict[str, Any]]] = None
    if hit and now - hit[0] < TTL:
        verdict = hit[1]
    else:
        if client is None:
            try:
                from src.services.llm_client import get_llm_client
                client = get_llm_client()
            except Exception as exc:  # noqa: BLE001
                logger.warning("rubric_judge: no client: %s", exc)
                client = None
        if client is None:
            return items
        try:
            from src.services.llm_client import resolve_model
            resp = client.messages.create(
                model=resolve_model(model), max_tokens=1024, system=_SYSTEM,
                messages=[{"role": "user", "content": _prompt(rubric, viewer, judged)}])
            raw = resp.content[0].text if resp.content else ""
            verdict = _parse(raw)
        except Exception as exc:  # noqa: BLE001 - the hard order stands
            logger.warning("rubric_judge: call failed, hard order kept: %s", exc)
            return items
        with _lock:
            _cache[key] = (now, verdict)

    by_subject = {v["subject"]: v for v in (verdict or [])}
    out: List[Item] = []
    for i in items:
        v = by_subject.get(i.subject)
        if not v or i.rank >= CLOCK_FLOOR:
            out.append(i)
            continue
        try:
            nudge = max(-MAX_NUDGE, min(MAX_NUDGE, float(v.get("nudge", 0))))
        except (TypeError, ValueError):
            out.append(i)
            continue
        if not nudge:
            out.append(i)
            continue
        why = str(v.get("why") or "").strip()[:80]
        out.append(Item(
            subject=i.subject, title=i.title,
            reason=Reason(why or i.reason.label, "judgement"),
            rank=min(JUDGED_CEILING - 1.0, max(0.0, i.rank + nudge)),
            links=i.links, quote=i.quote, due=i.due, assignee=i.assignee,
            past=i.past, campaign=i.campaign))
    out.sort(key=lambda x: (-x.rank, x.title))
    return out
