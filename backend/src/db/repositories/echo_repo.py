"""
Echo repo — a person's own lines on a timeline (see migration 032).

Every method is guarded by user_id: a person only ever reads or changes
their own rows. Reads return plain dicts (RealDictCursor); writes commit.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from psycopg2 import extras

from src.db.connection import DatabaseConnection

# Columns a PATCH may touch, and nothing else.
EDITABLE = ("text", "category", "on_date", "parent_id", "position", "done_at")


class EchoRepo:
    def __init__(self):
        DatabaseConnection.initialize_pool()

    def list_for_user(self, user_id: int) -> List[Dict[str, Any]]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM echo_entries
                    WHERE user_id = %s
                    ORDER BY on_date, position, id
                    """,
                    (user_id,),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    def get(self, entry_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM echo_entries WHERE id = %s AND user_id = %s",
                    (entry_id, user_id),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def add(
        self,
        org_id: int,
        user_id: int,
        text: str,
        on_date: Optional[date] = None,
        category: Optional[str] = None,
        parent_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO echo_entries
                        (org_id, user_id, text, on_date, category, parent_id, position)
                    VALUES (%s, %s, %s, COALESCE(%s, CURRENT_DATE), %s, %s,
                            COALESCE((SELECT MAX(position) + 1 FROM echo_entries
                                      WHERE user_id = %s
                                        AND on_date = COALESCE(%s, CURRENT_DATE)
                                        AND parent_id IS NOT DISTINCT FROM %s), 0))
                    RETURNING *
                    """,
                    (org_id, user_id, text, on_date, category, parent_id,
                     user_id, on_date, parent_id),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row)
        finally:
            DatabaseConnection.return_connection(conn)

    def update(self, entry_id: int, user_id: int, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Apply the given column changes. Unknown columns are refused upstream."""
        cols = [c for c in changes if c in EDITABLE]
        if not cols:
            return self.get(entry_id, user_id)
        sets = ", ".join(f"{c} = %s" for c in cols) + ", updated_at = now()"
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    f"UPDATE echo_entries SET {sets} WHERE id = %s AND user_id = %s RETURNING *",
                    [changes[c] for c in cols] + [entry_id, user_id],
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def delete(self, entry_id: int, user_id: int) -> bool:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM echo_entries WHERE id = %s AND user_id = %s",
                    (entry_id, user_id),
                )
                deleted = cur.rowcount > 0
                conn.commit()
                return deleted
        finally:
            DatabaseConnection.return_connection(conn)
