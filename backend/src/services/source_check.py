"""
Mark links in an answer that no tool returned.

The model names websites it never opened ("verified against Boast's published
figures"). A prompt rule does not stop that, so the harness checks: every URL or
web domain in the answer must appear in some tool result from the same answer.
Anything else is listed under the answer so the person sees it was not opened.
"""

import re
from typing import Iterable, List

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


def _domains(text: str) -> List[str]:
    seen = []
    for m in _DOMAIN.finditer(text or ""):
        d = m.group(1).lower()
        if m.group(2).lower() in _FILE_EXTS:
            continue
        if d.startswith("www."):
            d = d[4:]
        if d not in seen:
            seen.append(d)
    return seen


def unopened_domains(answer: str, tool_outputs: Iterable[str]) -> List[str]:
    """Domains named in `answer` that appear in none of `tool_outputs`."""
    returned = " ".join(str(t) for t in tool_outputs).lower()
    return [d for d in _domains(answer) if d not in returned]


def mark_unopened(answer: str, tool_outputs: Iterable[str]) -> str:
    """`answer`, plus a last line naming the sites amebo did not open."""
    missing = unopened_domains(answer, list(tool_outputs))
    if not missing:
        return answer
    return f"{answer}\n\nNot opened for this answer: {', '.join(missing)}"
