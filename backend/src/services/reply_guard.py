"""Reply guard: a Slack answer states the purpose, not the process.

Rule (prompts/amebo-for-claude.md and the instance identity_prompt): a reply is
concise, purposeful, and ends with ONE link to the thing made. Prompts alone did
not hold, so both answer paths (the backend in slack_commands, amebo-max in
max_answerer) check the reply here before posting and ask the model for one
rewrite when it fails. If the rewrite still fails, it is posted anyway and
logged: a long answer is better than silence.
"""
from __future__ import annotations

import re
from typing import Optional

# Characters of visible text; a Slack link <url|label> counts as its label.
MAX_CHARS = 400

# Headings and openers that narrate the work instead of giving the result.
PROCESS_MARKERS = re.compile(
    r"what i did|here'?s what i did|steps i took|what i (?:read|checked|looked at)"
    r"|^\s*[*_]*(?:i (?:read|checked|searched|looked at|reviewed))\b",
    re.IGNORECASE | re.MULTILINE,
)

# Sentences about amebo itself ("I removed", "I've noted", "My mistake"): two or
# more is an account of the work, not the result.
_SELF = re.compile(r"(?:^|[.!?:]\s+|\n\s*)(?:I|I've|I'm|I'd|I'll|My)\b")
_APOLOGY = re.compile(r"my mistake|i should have|sorry|apolog", re.IGNORECASE)

_SLACK_LINK = re.compile(r"<([^|>]+)\|([^>]*)>")
_BARE_LINK = re.compile(r"<(https?://[^>]+)>")

REWRITE_INSTRUCTION = (
    "Your reply was not posted: {why}. Rewrite it for Slack. Focus on the "
    "PURPOSE, NOT THE PROCESS: the answer or what you made, in at most "
    f"{MAX_CHARS} characters, no account of what you read, checked or did, "
    "ending with ONE link to the thing made (a ticket, card, doc or other "
    "item, wherever the work lives). Reply with the rewritten message only."
)


def visible_length(text: str) -> int:
    text = _SLACK_LINK.sub(lambda m: m.group(2), text)
    text = _BARE_LINK.sub("link", text)
    return len(text.strip())


def problem(text: str) -> Optional[str]:
    """Why this reply breaks the rule, or None when it is fine."""
    if not text:
        return None
    n = visible_length(text)
    if n > MAX_CHARS:
        return f"it is {n} characters, the limit is {MAX_CHARS}"
    if _APOLOGY.search(text):
        return "it apologizes; state the result only"
    n_self = len(_SELF.findall(text))
    if n_self >= 2:
        return f"it narrates what amebo did ({n_self} sentences start with I or My)"
    m = PROCESS_MARKERS.search(text)
    if m:
        return f"it narrates process (\"{m.group(0).strip()}\")"
    return None


def rewrite_prompt(text: str, why: str) -> str:
    """Instruction plus the rejected reply, for a model with no thread context."""
    return REWRITE_INSTRUCTION.format(why=why) + "\n\nThe reply:\n\n" + text
