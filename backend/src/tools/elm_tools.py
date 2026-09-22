"""
Elm tools — amebo reading campaign state from elm over its HTTP API.

Elm (elm.linkedtrust.us) is a separate app over the CRM, not part of amebo. It
owns campaigns; amebo owns goals. A goal references a campaign by its elm URL
and nothing more, so amebo works unchanged where there is no elm and no CRM.

Auth: X-API-Key from ELM_API_KEY. Base URL from ELM_BASE_URL.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import requests

DEFAULT_BASE_URL = "https://elm.linkedtrust.us"
TIMEOUT = 30


ELM_CAMPAIGNS_SCHEMA = {
    "type": "object",
    "properties": {
        "days": {
            "type": "integer",
            "description": "Activity window in days (default 30, max 365).",
        },
        "limit": {
            "type": "integer",
            "description": "How many campaigns to return, most recently touched first (default 15).",
        },
        "min_messages": {
            "type": "integer",
            "description": "Only campaigns with at least this many human messages in the window.",
        },
    },
    "required": [],
}


def _base_url() -> str:
    return (os.environ.get("ELM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def elm_campaigns(tool_input: Dict[str, Any], context: Dict[str, Any]) -> str:
    key = (os.environ.get("ELM_API_KEY") or "").strip()
    if not key:
        return (
            "Error: elm_campaigns needs ELM_API_KEY in the backend env. "
            "It is not configured on this deployment."
        )

    days = int(tool_input.get("days") or 30)
    limit = int(tool_input.get("limit") or 15)
    min_messages = int(tool_input.get("min_messages") or 0)

    try:
        resp = requests.get(
            f"{_base_url()}/api/campaigns",
            params={"days": days},
            headers={"X-API-Key": key},
            timeout=TIMEOUT,
        )
    except requests.exceptions.Timeout:
        return f"Error: elm did not answer within {TIMEOUT}s."
    except requests.exceptions.RequestException as exc:
        return f"Error: could not reach elm — {exc}"

    if resp.status_code == 401:
        return "Error: elm rejected the API key (401)."
    if resp.status_code != 200:
        return f"Error: elm returned HTTP {resp.status_code}: {resp.text[:300]}"

    try:
        rows: List[Dict[str, Any]] = (resp.json() or {}).get("campaigns") or []
    except ValueError:
        return "Error: elm returned a non-JSON response."

    if min_messages:
        rows = [r for r in rows if (r.get("messages_human") or 0) >= min_messages]
    rows = rows[:limit]
    if not rows:
        return f"No campaigns with activity in the last {days} days."

    base = _base_url()
    lines = [f"Campaigns by last touch (last {days} days):", ""]
    for r in rows:
        people = ", ".join(
            f"{p['name']} ({p['messages']})" for p in (r.get("active_people") or [])[:3]
        ) or "nobody"
        lines.append(
            f"- {r['name']} — last touch {r.get('last_touch') or 'never'}; "
            f"{r.get('messages_human', 0)} human / {r.get('messages_agent', 0)} agent "
            f"messages; {r.get('opportunities', 0)} opportunities; active: {people}"
        )
        lines.append(f"  {base}{r['url']}")
    return "\n".join(lines)
