"""
Whiteboard repo — append-only entries plus the processed stamp.

The whiteboard is an input surface (a chatter log), not a record: entries are
written once, read by humans (recent) and by amebo's filing pass (unprocessed),
and stamped processed_at/filed when their facts have been put where they belong.
"""

from typing import Any, Dict, List, Optional

from psycopg2 import extras

from src.db.connection import DatabaseConnection


class WhiteboardRepo:
    """All methods commit eagerly; reads return plain dicts (RealDictCursor)."""

    def __init__(self):
        DatabaseConnection.initialize_pool()

    def add(
        self,
        org_id: int,
        text: str,
        user_id: Optional[int] = None,
        author: str = "",
    ) -> Dict[str, Any]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO whiteboard_entries (org_id, user_id, author, text)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                    """,
                    (org_id, user_id, author, text),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row)
        finally:
            DatabaseConnection.return_connection(conn)

    def list_for_org(
        self, org_id: int, limit: int = 50, unprocessed_only: bool = False
    ) -> List[Dict[str, Any]]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT * FROM whiteboard_entries
                    WHERE org_id = %s {"AND processed_at IS NULL" if unprocessed_only else ""}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (org_id, limit),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    def mark_processed(
        self, entry_id: int, org_id: int, filed: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[Dict[str, Any]]:
        """Stamp an entry as filed. Org-guarded; only unprocessed rows update."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE whiteboard_entries
                    SET processed_at = now(), filed = %s
                    WHERE id = %s AND org_id = %s AND processed_at IS NULL
                    RETURNING *
                    """,
                    (extras.Json(filed) if filed is not None else None, entry_id, org_id),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)
