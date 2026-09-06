"""The importance rubric — what makes an item rise on a person's list.

Per org, configurable, in code. Golda (2026-09-06): "It's not a dated deadline.
Usually the things don't have dated deadlines. If there is a person waiting on
it, that would be most important. If somebody would be interested in the thing,
for money or for a warm contact, that's what makes it important. But for each
person it would be different because they have a different surface of contacts
and a different surface of skills. LinkedTrust: is it going to generate money.
workers.vc: partnerships and attention. Raise the Voices: human rights cases,
no money involved. There needs to be a skill for updating the rubric. It should
not be a fixed rubric."

So the weights live in ``instances.config.rubric`` and the code only knows the
signals. The clock (a real due date) still outranks every judged signal; that
rule is not in the rubric because a person cannot be assumed to have meant to
hide from a date.

Signals, in the team's words, each a weight added to an undated item's score:

- ``someone_waiting``    somebody other than the reader said the last word
- ``contact_interested`` the last word on a CRM record was the contact's own
- ``money``              the record carries expected revenue
- ``owned``              somebody owns it, so it can move
- ``picked_up``          somebody dragged it off the board's first column
- ``new``                made within ``new_days`` and not yet looked at
- ``no_detail``          nothing written down to act on (subtracted)
- ``quiet_fade``         points lost per day since anything happened, to
                         ``quiet_max``
- ``draft``              a draft amebo is holding for approval (its own ask,
                         so it starts below a person's)
- ``stage_step``         each CRM stage further along is more real
- ``quiet_cap``          quiet days on an opportunity stop counting past this

``focus`` is prose: what matters to this team, shown to the reader and to the
claw, never scored. ``judgement`` is prose too, but it IS applied: when set, a
model reads the hard-scored candidates with these instructions and may move
each one up or down within the judged band, saying why on the row
(src/services/rubric_judge.py). Golda (2026-09-06): "the rubric should allow
some LLM judgement, it's kind of like a prompt, it can have some hard signal
also." The clock still wins; judgement never reaches a dated row. ``top_n`` is
how many rows a person is shown when they ask for only what matters.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any, Dict, List, Optional

# The defaults are the weights the list ran on before the rubric existed
# (work_list.py, 2026-08-11), so an org with no rubric ranks exactly as before.
UNDATED_FLOOR = 300.0
UNDATED_OWNED = 60.0
UNDATED_NO_DETAIL = 10.0
UNDATED_NEW_DAYS = 5
UNDATED_NEW = 250.0
UNDATED_ASKED = 120.0
UNDATED_PICKED_UP = 90.0
UNDATED_QUIET_FADE = 2.0
UNDATED_QUIET_MAX = 200.0
OPEN_CONTEXT_FLOOR = 400.0
OPEN_CONTEXT_STAGE_STEP = 60.0
OPEN_CONTEXT_QUIET_CAP = 180.0


@dataclass(frozen=True)
class Rubric:
    focus: str = ""
    judgement: str = ""
    top_n: int = 5
    # undated tasks
    someone_waiting: float = UNDATED_ASKED
    owned: float = UNDATED_OWNED
    picked_up: float = UNDATED_PICKED_UP
    new: float = UNDATED_NEW
    new_days: int = UNDATED_NEW_DAYS
    no_detail: float = UNDATED_NO_DETAIL
    quiet_fade: float = UNDATED_QUIET_FADE
    quiet_max: float = UNDATED_QUIET_MAX
    # opportunities
    stage_step: float = OPEN_CONTEXT_STAGE_STEP
    quiet_cap: float = OPEN_CONTEXT_QUIET_CAP
    contact_interested: float = 0.0
    money: float = 0.0
    # a draft amebo wants approved: its own ask, so below any person's
    draft: float = 100.0

    @classmethod
    def from_config(cls, config: Optional[Any]) -> "Rubric":
        """The org's rubric from ``instances.config``, or the defaults.

        Unknown keys are ignored and a value that will not coerce falls back to
        the default for that one field, so a typo in the config degrades one
        weight rather than the whole list."""
        raw = None
        if isinstance(config, dict):
            raw = config.get("rubric")
        if not isinstance(raw, dict):
            return cls()
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Rubric":
        kw: Dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in raw:
                continue
            v = raw[f.name]
            try:
                if f.type in ("float", float):
                    kw[f.name] = float(v)
                elif f.type in ("int", int):
                    kw[f.name] = int(v)
                else:
                    kw[f.name] = str(v or "")
            except (TypeError, ValueError):
                continue
        return cls(**kw)

    def to_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def with_changes(self, **changes: Any) -> "Rubric":
        return replace(self, **changes)

    def describe(self) -> List[str]:
        """The rubric in plain lines, highest weight first, so a person can read
        what their list is ranking on without reading code."""
        lines: List[str] = []
        if self.focus:
            lines.append(self.focus.strip())
        weights = [
            ("someone is waiting on you", self.someone_waiting),
            ("the contact wrote last", self.contact_interested),
            ("money on the record", self.money),
            ("just made, not yet looked at", self.new),
            ("somebody picked it up", self.picked_up),
            ("somebody owns it", self.owned),
        ]
        for label, w in sorted(weights, key=lambda x: -x[1]):
            if w:
                lines.append(f"+{w:g} {label}")
        lines.append(f"-{self.quiet_fade:g}/day quiet, to -{self.quiet_max:g}")
        lines.append(f"shows top {self.top_n}")
        return lines


DEFAULT = Rubric()
