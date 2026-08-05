"""Work-list marks — one person's pin or burial of a subject.

A mark is a fact about a person and a subject, never about the task, so nothing
here reaches Taiga or the CRM. Reads come back as {subject -> state} because
that is the only shape the list needs: it has the items already and asks, once,
which of them this person has marked.
"""

from typing import Any, Dict, List, Optional

from psycopg2 import extras

from src.db.connection import DatabaseConnection

STATES = ("pinned", "buried")


class WorkListMarkRepo:
    """All methods commit eagerly; reads return plain dicts (RealDictCursor)."""

    def __init__(self):
        DatabaseConnection.initialize_pool()

    def set(self, *, org_id: int, person: str, subject: str,
            state: str) -> Dict[str, Any]:
        """Pin or bury. Setting one replaces the other: a subject cannot be both
        always-shown and pushed down, and the last thing the person clicked is
        what they meant."""
        if state not in STATES:
            raise ValueError(f"unknown mark state: {state!r}")
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO work_list_marks (org_id, person, subject, state)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (org_id, person, subject)
                    DO UPDATE SET state = EXCLUDED.state, created_at = now()
                    RETURNING *
                    """,
                    (org_id, (person or "").strip().lower(), subject, state),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row)
        finally:
            DatabaseConnection.return_connection(conn)

    def clear(self, *, org_id: int, person: str, subject: str) -> bool:
        """Unpin or unbury. Returns whether there was anything to clear, so the
        route can 404 rather than pretend."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM work_list_marks "
                    "WHERE org_id = %s AND person = %s AND subject = %s",
                    (org_id, (person or "").strip().lower(), subject),
                )
                removed = cur.rowcount
                conn.commit()
                return bool(removed)
        finally:
            DatabaseConnection.return_connection(conn)

    def for_person(self, *, org_id: int,
                   person: Optional[str]) -> Dict[str, str]:
        """{subject -> state} for one person. No person (a service key, or
        nobody signed in) means no marks: a pin belongs to a human, and applying
        someone else's would rearrange a stranger's list."""
        if not person:
            return {}
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT subject, state FROM work_list_marks "
                    "WHERE org_id = %s AND person = %s "
                    "ORDER BY created_at ASC",
                    (org_id, (person or "").strip().lower()),
                )
                return {r["subject"]: r["state"] for r in cur.fetchall()}
        finally:
            DatabaseConnection.return_connection(conn)

    def pinned_order(self, *, org_id: int, person: Optional[str]) -> List[str]:
        """Subjects this person pinned, oldest pin first — the order they chose,
        which is the only order a pinned block should be in."""
        marks = self.for_person(org_id=org_id, person=person)
        return [s for s, state in marks.items() if state == "pinned"]
