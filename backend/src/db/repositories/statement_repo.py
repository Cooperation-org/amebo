"""
Statement repo — the org's named pointers to what it is aiming at.

One table (migration 031). A statement is a relation name plus either the words
themselves or a pointer to where they live. Resolving a pointer to text is not
this repo's job; that is services/statements.py, so the store stays a store.

Every write records who made it. A row amebo proposed is written with
accepted_at NULL and stays inert until a person accepts it.
"""

from typing import Any, Dict, List, Optional

from psycopg2 import extras

from src.db.connection import DatabaseConnection

# Columns a caller may change. Anything else (org_id, written_by, timestamps)
# is set by the server, so a client cannot reassign a row to another org or
# forge authorship by passing extra fields.
EDITABLE = ("name", "body", "pointer", "source", "informs_priority", "holder")


class StatementRepo:
    """All methods commit eagerly; reads return plain dicts (RealDictCursor)."""

    def __init__(self):
        DatabaseConnection.initialize_pool()

    def add(
        self,
        org_id: int,
        name: str,
        *,
        body: Optional[str] = None,
        pointer: Optional[str] = None,
        source: str = "",
        informs_priority: bool = False,
        holder: str = "org",
        written_by: str = "",
        accepted: bool = True,
    ) -> Dict[str, Any]:
        """Add a statement. `accepted=False` is how a claw proposes one: the row
        exists and is visible, and nothing reads it until a human accepts."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO org_statements (
                        org_id, holder, name, body, pointer, source,
                        informs_priority, written_by, accepted_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                            CASE WHEN %s THEN now() ELSE NULL END)
                    RETURNING *
                    """,
                    (org_id, holder, name, body, pointer, source,
                     informs_priority, written_by, accepted),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row)
        finally:
            DatabaseConnection.return_connection(conn)

    def list_for_org(self, org_id: int, holder: Optional[str] = None) -> List[Dict[str, Any]]:
        """Everything the org holds, proposed rows included — the page shows
        them so a proposal can be accepted or thrown away where it sits."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM org_statements
                    WHERE org_id = %s AND (%s::text IS NULL OR holder = %s)
                    ORDER BY accepted_at IS NULL DESC, name, created_at
                    """,
                    (org_id, holder, holder),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    def live_for_org(self, org_id: int, holder: str = "org") -> List[Dict[str, Any]]:
        """Accepted rows that are switched on — what actually steers the org.
        Nothing switched on returns empty, which is a normal state."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM org_statements
                    WHERE org_id = %s AND holder = %s
                      AND accepted_at IS NOT NULL AND informs_priority
                    ORDER BY name, created_at
                    """,
                    (org_id, holder),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    def get(self, statement_id: int, org_id: int) -> Optional[Dict[str, Any]]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM org_statements WHERE id = %s AND org_id = %s",
                    (statement_id, org_id),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def update(
        self,
        statement_id: int,
        org_id: int,
        fields: Dict[str, Any],
        *,
        written_by: str = "",
        accept: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Change the fields a person may change. Editing carries authorship, so
        a proposal a human corrected becomes that human's words. `accept=True`
        stamps accepted_at, which is the gesture that makes a row live."""
        sets = [f"{col} = %s" for col in EDITABLE if col in fields]
        params: List[Any] = [fields[col] for col in EDITABLE if col in fields]
        if written_by:
            sets.append("written_by = %s")
            params.append(written_by)
        if accept:
            sets.append("accepted_at = COALESCE(accepted_at, now())")
        if not sets:
            return self.get(statement_id, org_id)
        sets.append("updated_at = now()")
        params += [statement_id, org_id]

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    f"UPDATE org_statements SET {', '.join(sets)} "
                    "WHERE id = %s AND org_id = %s RETURNING *",
                    params,
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def delete(self, statement_id: int, org_id: int) -> bool:
        """Throwing one away is ordinary work, not an incident: a mission
        somebody outgrew should leave, not linger switched off."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM org_statements WHERE id = %s AND org_id = %s",
                    (statement_id, org_id),
                )
                deleted = cur.rowcount > 0
                conn.commit()
                return deleted
        finally:
            DatabaseConnection.return_connection(conn)
