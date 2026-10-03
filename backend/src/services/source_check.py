"""
Numbered sources, checked in code.

Each tool result is tagged [S1], [S2], ... before the model sees it, and the
model cites facts with those tags. Before an answer reaches a person, code
checks it:
- every [S#] it cites exists,
- every website it names was returned by a tool, opened earlier in the thread,
  or written by the person,
- it does not claim to have checked or read something when no tool ran.
A failing answer is sent back to the model to fix (it may use tools); if it
still fails, the failing sentences are removed. Nothing unchecked is shown.
"""

import re
from typing import Iterable, List, Optional, Tuple

# Appended to the system prompt by every loop that uses Sources.
CITE_NOTE = (
    "\n\nSOURCES. Each tool result starts with a tag like [S3]. Put the tag "
    "after any fact that came from that result. Never say you checked, "
    "verified, read or confirmed something unless a tool result in this "
    "conversation shows it. Never name a website unless a tool returned it or "
    "the person wrote it."
)

MAX_FIXES = 2

# Web domains only: "MAIN.md", "app.py", "Node.js" are files or names, not sites.
_FILE_EXTS = {
    "md", "py", "js", "ts", "tsx", "jsx", "json", "txt", "html", "htm", "css",
    "sh", "yml", "yaml", "toml", "csv", "pdf", "png", "jpg", "jpeg", "gif", "svg",
    "sql", "env", "log", "cfg", "ini", "lock", "go", "rs", "rb", "java", "xml",
    "doc", "docx", "xlsx", "pptx", "zip", "gz", "tar", "mp4", "mp3", "service",
}
_DOMAIN = re.compile(
    r"(?<![\w@./-])(?:https?://)?((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+([a-z]{2,24}))(?![\w-])",
    re.IGNORECASE,
)
_TAG = re.compile(r"\[S(\d+)\]")
# A tool result that is an error or a blocked page is not a source.
_FAILED = re.compile(r"^(?:Error|Refused|Unknown tool)\b|^URL: \S+\nStatus: [45]\d\d\b")
_CHECK_WORDS = re.compile(
    r"\b(verified|I checked|checked against|confirmed (?:on|in|by|with|against)|"
    r"according to|I read|I fetched|I looked at|I looked up|I searched)\b",
    re.IGNORECASE,
)


def domains(text: str) -> List[str]:
    seen: List[str] = []
    for m in _DOMAIN.finditer(text or ""):
        if m.group(2).lower() in _FILE_EXTS:
            continue
        d = m.group(1).lower()
        if d.startswith("www."):
            d = d[4:]
        if d not in seen:
            seen.append(d)
    return seen


def source_label(name: str, inp) -> str:
    """Short name for a source: the URL for a fetched page, else tool + argument."""
    inp = inp or {}
    if inp.get("url"):
        return str(inp["url"])[:80]
    arg = next((str(v) for v in inp.values() if isinstance(v, (str, int))), "")
    return f"{name} {arg}".strip()[:80]


def next_tag_number(messages: Iterable[dict]) -> int:
    """First free S-number given tags already in the replayed history."""
    nums = [int(n) for m in messages for n in _TAG.findall(str(m.get("content", "")))]
    return max(nums, default=0) + 1


class Sources:
    """The tool results of one answer, numbered."""

    def __init__(self, start: int = 1, known: str = ""):
        # known: text whose websites count as opened — earlier opened sites in
        # the thread and the person's own message.
        self._next = start
        self._known = known.lower()
        self.items: List[Tuple[int, str, str]] = []   # (n, label, content)

    def add(self, label: str, content: str) -> str:
        """Record a tool result; return it tagged for the model."""
        if _FAILED.match(str(content).lstrip()):
            return str(content)
        n = self._next
        self._next += 1
        self.items.append((n, label, str(content)))
        return f"[S{n}] {content}"

    def opened(self) -> List[str]:
        """Websites in this answer's tool results, to remember for the thread."""
        out: List[str] = []
        for _, _, c in self.items:
            out += [d for d in domains(c) if d not in out]
        return out

    def problems(self, answer: str) -> List[str]:
        have = {n for n, _, _ in self.items}
        returned = (" ".join(c for _, _, c in self.items) + " " + self._known).lower()
        out = [f"[S{n}] does not exist" for n in sorted({int(x) for x in _TAG.findall(answer)})
               if int(n) not in have]
        out += [f"{d} was not opened" for d in domains(answer) if d not in returned]
        if not self.items:
            out += [f'says "{w}" but no tool ran'
                    for w in dict.fromkeys(m.group(0) for m in _CHECK_WORDS.finditer(answer))]
        return out

    def fix_request(self, problems: List[str]) -> str:
        return ("Your answer was not shown to the person: " + "; ".join(problems)
                + ". Open what you need with tools, or leave those claims out. "
                "Write the whole answer again.")

    def strip(self, answer: str) -> str:
        """Last resort: drop the sentences that still fail."""
        keep = []
        for s in re.split(r"(?<=[.!?])\s+|\n", answer):
            if s.strip() and not self.problems(s):
                keep.append(s)
        return " ".join(keep).strip()

    def footer(self, answer: str) -> str:
        """One line naming the sources the answer cites."""
        cited = [int(n) for n in dict.fromkeys(_TAG.findall(answer))]
        labels = {n: label for n, label, _ in self.items}
        named = [f"[S{n}] {labels[n]}" for n in cited if n in labels]
        return f"{answer}\n\n{' · '.join(named)}" if named else answer


def finish(answer: str, sources: Sources, retry) -> str:
    """Check `answer`; while it fails, `retry(fix_request)` returns a new one
    (the caller runs its model loop again, tools allowed). Returns the answer
    to show: passing, or with failing sentences removed, plus its sources."""
    for _ in range(MAX_FIXES):
        bad = sources.problems(answer)
        if not bad:
            break
        answer = retry(sources.fix_request(bad)) or ""
    if sources.problems(answer):
        answer = sources.strip(answer) or "I could not check an answer to that."
    return sources.footer(answer)
