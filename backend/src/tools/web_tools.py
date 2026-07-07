"""
Web search/research tools backed by the You.com APIs.

Two tools:
- web_search   — GET https://api.you.com/v1/agents/search (web + news results).
                 Works without an API key on You.com's documented free tier
                 (~100 searches/day); a key lifts the limit.
- web_research — POST https://api.you.com/v1/research (synthesized answer with
                 cited sources). Requires an API key.

Auth: X-API-Key header from the YDC_API_KEY environment variable.
Key management: keys.you.com / you.com/platform/api-keys.
API shapes follow youdotcom-oss/agent-skills (skills/youdotcom-api, MIT).

Both tools are read-only: they hit an external search provider and return
text to the model. No org data leaves the system beyond the query string
itself — do not put secrets or personal contact data in queries.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import requests

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.you.com/v1/agents/search"
RESEARCH_URL = "https://api.you.com/v1/research"

SEARCH_TIMEOUT = 30        # seconds
RESEARCH_TIMEOUT = 180     # research with higher effort can be slow
MAX_COUNT = 20             # results per section cap (API allows 100)
MAX_CHARS = 24_000         # cap on text returned to the model
RESEARCH_EFFORTS = {"lite", "standard", "deep", "exhaustive"}


def _api_key() -> str:
    return (os.environ.get("YDC_API_KEY") or "").strip()


def _headers() -> Dict[str, str]:
    headers = {"User-Agent": "amebo-web-tools/1.0"}
    key = _api_key()
    if key:
        headers["X-API-Key"] = key
    return headers


def _clip(text: str, limit: int = MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[truncated]"


def _format_results(section: str, items: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for i, item in enumerate(items, 1):
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        desc = (item.get("description") or "").strip()
        snippets = [s.strip() for s in (item.get("snippets") or []) if s and s.strip()]
        lines.append(f"[{section} {i}] {title}\n{url}")
        if desc:
            lines.append(desc)
        # A couple of snippets add recall without flooding the context.
        for snip in snippets[:2]:
            if snip != desc:
                lines.append(f"> {snip}")
        lines.append("")
    return lines


def web_search(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    query = (tool_input.get("query") or "").strip()
    if not query:
        return "Error: query is required."

    count = int(tool_input.get("count") or 10)
    count = max(1, min(count, MAX_COUNT))

    params: Dict[str, Any] = {"query": query, "count": count}
    freshness = (tool_input.get("freshness") or "").strip()
    if freshness:
        params["freshness"] = freshness

    try:
        resp = requests.get(
            SEARCH_URL, params=params, headers=_headers(), timeout=SEARCH_TIMEOUT
        )
    except requests.exceptions.Timeout:
        return f"Error: search timed out after {SEARCH_TIMEOUT}s."
    except requests.exceptions.RequestException as exc:
        return f"Error: search request failed — {exc}"

    if resp.status_code == 401:
        return (
            "Error: You.com rejected the request (401). The keyless free tier "
            "may be exhausted for today, or YDC_API_KEY is invalid."
        )
    if resp.status_code == 429:
        return "Error: You.com rate limit exceeded (429). Try again later."
    if resp.status_code != 200:
        return f"Error: You.com search returned HTTP {resp.status_code}: {resp.text[:300]}"

    try:
        body = resp.json()
    except ValueError:
        return "Error: You.com search returned non-JSON response."

    results = body.get("results") or {}
    web_hits = results.get("web") or []
    news_hits = results.get("news") or []
    if not web_hits and not news_hits:
        return f"No results for: {query}"

    lines: List[str] = [f"You.com search results for: {query}", ""]
    lines += _format_results("web", web_hits)
    if news_hits:
        lines += _format_results("news", news_hits)
    return _clip("\n".join(lines).strip())


def web_research(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    question = (tool_input.get("question") or "").strip()
    if not question:
        return "Error: question is required."
    if not _api_key():
        return (
            "Error: web_research requires YDC_API_KEY, which is not configured "
            "on this deployment. Use web_search (works keyless) or ask an admin "
            "to add the key (you.com/platform/api-keys) to the backend env."
        )

    effort = (tool_input.get("effort") or "standard").strip().lower()
    if effort not in RESEARCH_EFFORTS:
        return f"Error: effort must be one of {sorted(RESEARCH_EFFORTS)}."

    try:
        resp = requests.post(
            RESEARCH_URL,
            json={"input": question, "research_effort": effort},
            headers=_headers(),
            timeout=RESEARCH_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        return f"Error: research timed out after {RESEARCH_TIMEOUT}s (effort={effort})."
    except requests.exceptions.RequestException as exc:
        return f"Error: research request failed — {exc}"

    if resp.status_code == 401:
        return "Error: You.com rejected YDC_API_KEY (401)."
    if resp.status_code == 429:
        return "Error: You.com rate limit exceeded (429). Try again later."
    if resp.status_code != 200:
        return f"Error: You.com research returned HTTP {resp.status_code}: {resp.text[:300]}"

    try:
        body = resp.json()
    except ValueError:
        return "Error: You.com research returned non-JSON response."

    output = body.get("output") or {}
    content = (output.get("content") or "").strip()
    if not content:
        return "Error: You.com research returned an empty answer."

    lines = [content, "", "Sources:"]
    for i, src in enumerate(output.get("sources") or [], 1):
        title = (src.get("title") or "").strip()
        url = (src.get("url") or "").strip()
        lines.append(f"[{i}] {title} — {url}")
    return _clip("\n".join(lines).strip())


WEB_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search terms, as you would type into a search engine.",
        },
        "count": {
            "type": "integer",
            "description": "Results per section (web/news), 1-20. Default 10.",
            "default": 10,
        },
        "freshness": {
            "type": "string",
            "description": (
                "Optional recency filter: 'day', 'week', 'month', 'year', or a "
                "date range. Omit for no filter."
            ),
        },
    },
    "required": ["query"],
}

WEB_RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "The research question to answer with cited sources.",
        },
        "effort": {
            "type": "string",
            "enum": ["lite", "standard", "deep", "exhaustive"],
            "description": (
                "Research depth. 'standard' (default) for most questions; 'deep'/"
                "'exhaustive' are slower and cost more — use only when asked for "
                "thorough research."
            ),
            "default": "standard",
        },
    },
    "required": ["question"],
}
