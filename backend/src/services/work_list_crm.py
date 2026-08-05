"""Odoo-backed source for the work list.

The vendor leaf, kept apart from ``work_list`` for the same reason
``work_list_taiga`` is: ranking stays pure and testable against a fake store,
and every Odoo detail (XML-RPC, model names, the /web# form URL) lives here.

What comes out of the CRM and onto a person's list, and what deliberately does
not:

  **In: scheduled follow-ups** (``mail.activity``) — someone chose a date and
  put a name on it. That is the same kind of fact as a story with a due date,
  so it ranks on the same clock and sits in the same list rather than in a CRM
  section of its own.

  **Out: undated leads.** There are over a thousand of them. A list that needs
  a person is not a backlog, and dumping the pipeline into it is exactly what
  the grooming pass had to undo. A lead reaches the list when someone schedules
  something on it, which is the moment it starts waiting on a human.

Only reads. Writes a human presses go through the registered executors.
"""

from __future__ import annotations

import logging
import os
import re
from html import unescape as _unescape
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ODOO_PUBLIC_URL = os.getenv("ODOO_PUBLIC_URL", "https://crm.linkedtrust.us").rstrip("/")


def form_url(model: str, record_id: Any) -> str:
    """Where a person goes to see an Odoo record. One place builds this so the
    form route cannot drift between callers."""
    return f"{ODOO_PUBLIC_URL}/web#id={record_id}&model={model}&view_type=form"


_BREAK_RE = re.compile(r"<\s*(br|/p|/div|/li)\b[^>]*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")

# Amebo's own stamp on chatter it wrote (see mail_poller/poller.py). It is a
# label the app generated, not something a person said, so it never becomes the
# headline on a card.
_PROVENANCE_RE = re.compile(r"^\s*via [\w.-]+ ·[^\n]*\n?", re.I)

# A forwarded mail carries its own header block. The person's words start after
# it, and the name on the From: line is who actually said them — not whoever
# forwarded it into the CRM.
_FWD_MARKER_RE = re.compile(
    r"-{2,}\s*Forwarded message\s*-{2,}|Begin forwarded message:?|"
    r"-{2,}\s*Original Message\s*-{2,}", re.I)
_HEADER_LINE_RE = re.compile(r"^\s*(From|Date|Sent|Subject|To|Cc|Bcc):", re.I)
_FROM_NAME_RE = re.compile(r"^\s*From:\s*([^<\n]+?)\s*(?:<|$)", re.I | re.MULTILINE)

# How far past the last header key to keep looking for the blank line that
# closes the block. A wrapped Cc: list runs to a few lines; beyond that the
# blank line is not a header separator and the message starts straight away.
_HEADER_WRAP_LINES = 8


def _clean(html: str) -> str:
    """HTML chatter as readable text, with its line structure kept.

    Breaks become newlines rather than spaces: a forwarded mail's header block
    is only separable from the message when its lines are still lines.
    """
    text = _BREAK_RE.sub("\n", html or "")
    text = _TAG_RE.sub(" ", text)
    text = _unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    # A tag either side of a break leaves the space that stood in for it sitting
    # against the newline, which then shows up as an indent on every line.
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def human_words(text: str) -> tuple:
    """(who actually said it or None, what they said).

    Strips what amebo stamped on the record and what the mail client wrote,
    leaving the part a person typed. Golda's rule for every surface: their
    words, never app-generated labels.
    """
    body = _PROVENANCE_RE.sub("", text or "", count=1).strip()
    who = None

    marker = _FWD_MARKER_RE.search(body)
    if marker:
        after = body[marker.end():]
        name = _FROM_NAME_RE.search(after)
        if name:
            who = name.group(1).strip() or None
        # Where the header block ends. Not simply "after the last From:/To:
        # line" — a long Cc: wraps onto lines of its own that carry no key, and
        # those read as the start of the message when they are not. A mail body
        # begins after the blank line that closes the headers, so that is what
        # is looked for.
        lines = after.splitlines()
        last_header = -1
        for i, line in enumerate(lines):
            if _HEADER_LINE_RE.match(line):
                last_header = i
        if last_header >= 0:
            start = last_header + 1
            for i in range(start, min(len(lines), start + _HEADER_WRAP_LINES)):
                if not lines[i].strip():
                    start = i + 1
                    break
            body = "\n".join(lines[start:]).strip() or body
    return who, body


class OdooActivityStore:
    """Scheduled CRM follow-ups, and the last thing a person said on the record
    each one hangs off."""

    def __init__(self, connect=None):
        self._connect = connect or self._default_connect

    @staticmethod
    def _default_connect():
        from src.tools.cli_read_tools import _odoo
        return _odoo()

    def _kw(self, model: str, method: str, args, kwargs=None):
        m, db, uid, pwd = self._connect()
        return m.execute_kw(db, uid, pwd, model, method, args, kwargs or {})

    def open_activities(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Every scheduled follow-up, newest deadline last. Odoo only keeps an
        activity until it is marked done, so "open" needs no filter — a done
        follow-up is deleted, not flagged."""
        return self._kw("mail.activity", "search_read", [[]], {
            "fields": ["res_model", "res_id", "res_name", "summary", "note",
                       "date_deadline", "user_id", "activity_type_id"],
            "order": "date_deadline asc",
            "limit": limit,
        })

    def last_messages(self, res_model: str,
                      res_ids: List[int]) -> Dict[int, Dict[str, str]]:
        """{res_id -> the most recent human message on that record}.

        One query for the whole page rather than one per row: the list reads
        this for every activity it is about to show, and a call per row is what
        makes a list feel slow.
        """
        if not res_ids:
            return {}
        try:
            rows = self._kw("mail.message", "search_read", [[
                ("model", "=", res_model),
                ("res_id", "in", list(res_ids)),
                ("message_type", "in", ["comment", "email"]),
            ]], {"fields": ["res_id", "body", "author_id", "date"],
                 "order": "date desc", "limit": 400})
        except Exception as exc:  # noqa: BLE001 - a quote is a nicety, not the row
            logger.debug("work_list_crm: no messages for %s: %s", res_model, exc)
            return {}
        out: Dict[int, Dict[str, str]] = {}
        for row in rows:                      # newest first, so first wins
            rid = row.get("res_id")
            if rid in out:
                continue
            said_by, text = human_words(_clean(row.get("body")))
            if not text:
                continue
            author = row.get("author_id")
            out[rid] = {
                # Whoever the mail says wrote it, before whoever pasted it in.
                "who": said_by or (author[1] if isinstance(author, (list, tuple))
                                   and len(author) > 1 else "someone"),
                "text": text,
                "url": form_url(res_model, rid),
            }
        return out

    def activity(self, activity_id: int) -> Optional[Dict[str, Any]]:
        """One scheduled follow-up, or None when it is gone. Odoo deletes an
        activity when it is marked done, so a row opened from a stale list is a
        normal 404, not an error."""
        try:
            rows = self._kw("mail.activity", "read", [[int(activity_id)]], {
                "fields": ["res_model", "res_id", "res_name", "summary", "note",
                           "date_deadline", "user_id", "activity_type_id"]})
        except Exception as exc:  # noqa: BLE001
            logger.info("work_list_crm: activity %r unreadable: %s", activity_id, exc)
            return None
        return rows[0] if rows else None

    def messages(self, res_model: str, res_id: int,
                 limit: int = 20) -> List[Dict[str, str]]:
        """What people actually said on one record, newest first."""
        try:
            rows = self._kw("mail.message", "search_read", [[
                ("model", "=", res_model), ("res_id", "=", res_id),
                ("message_type", "in", ["comment", "email"]),
            ]], {"fields": ["body", "author_id", "date"],
                 "order": "date desc", "limit": limit})
        except Exception as exc:  # noqa: BLE001 - the record still opens without them
            logger.debug("work_list_crm: no messages for %s/%s: %s",
                         res_model, res_id, exc)
            return []
        out: List[Dict[str, str]] = []
        for row in rows:
            said_by, text = human_words(_clean(row.get("body")))
            if not text:
                continue
            author = row.get("author_id")
            out.append({
                "who": said_by or (author[1] if isinstance(author, (list, tuple))
                                   and len(author) > 1 else "someone"),
                "text": text,
                "when": row.get("date") or "",
            })
        return out

    def uids_for_logins(self, logins: List[str]) -> List[int]:
        """The Odoo user ids behind a set of logins, in one query.

        The list filters on ids, never display names: this CRM has two distinct
        accounts both reading "Golda Velez", so matching by name would hand one
        person the other's follow-ups.
        """
        if not logins:
            return []
        try:
            rows = self._kw("res.users", "search_read",
                            [[("login", "in", list(logins))]], {"fields": ["id"]})
        except Exception as exc:  # noqa: BLE001
            logger.warning("work_list_crm: cannot resolve logins %r: %s", logins, exc)
            return []
        found = [r["id"] for r in rows if r.get("id")]
        if len(found) < len(logins):
            logger.info("work_list_crm: %d of %d mapped CRM logins exist",
                        len(found), len(logins))
        return found
