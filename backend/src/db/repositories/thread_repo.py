"""
Data access for conversation threads and turns.
Source-agnostic: works for Slack, email, web, API.
"""

import logging
from typing import List, Dict, Optional
from psycopg2 import extras
from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class ThreadRepo:

    def __init__(self):
        DatabaseConnection.initialize_pool()

    def get_or_create_thread(
        self,
        source_type: str,
        source_ref: str,
        workspace_id: Optional[str] = None,
        instance_id: Optional[int] = None
    ) -> Dict:
        """Get existing thread or create new one. Returns thread dict."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Try to find existing
                cur.execute("""
                    SELECT * FROM threads
                    WHERE source_type = %s AND source_ref = %s
                    AND (workspace_id = %s OR (workspace_id IS NULL AND %s IS NULL))
                """, (source_type, source_ref, workspace_id, workspace_id))
                thread = cur.fetchone()

                if thread:
                    # Update last_active
                    cur.execute(
                        "UPDATE threads SET last_active_at = NOW() WHERE id = %s",
                        (thread['id'],)
                    )
                    conn.commit()
                    return dict(thread)

                # Create new
                cur.execute("""
                    INSERT INTO threads (instance_id, source_type, source_ref, workspace_id)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                """, (instance_id, source_type, source_ref, workspace_id))
                thread = cur.fetchone()
                conn.commit()
                return dict(thread)
        finally:
            DatabaseConnection.return_connection(conn)

    def add_turn(
        self,
        thread_id: int,
        role: str,
        content: str,
        metadata: Optional[Dict] = None,
        token_estimate: Optional[int] = None
    ) -> int:
        """Add a turn to a thread. Returns turn ID."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO thread_turns (thread_id, role, content, metadata, token_estimate)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (thread_id, role, content,
                      extras.Json(metadata or {}), token_estimate))
                turn_id = cur.fetchone()[0]
                cur.execute(
                    "UPDATE threads SET last_active_at = NOW() WHERE id = %s",
                    (thread_id,)
                )
                conn.commit()
                return turn_id
        finally:
            DatabaseConnection.return_connection(conn)

    def get_turns(self, thread_id: int, after_turn_id: Optional[int] = None) -> List[Dict]:
        """Get turns for a thread, optionally only those after a given turn ID."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                if after_turn_id:
                    cur.execute("""
                        SELECT * FROM thread_turns
                        WHERE thread_id = %s AND id > %s
                        ORDER BY created_at
                    """, (thread_id, after_turn_id))
                else:
                    cur.execute("""
                        SELECT * FROM thread_turns
                        WHERE thread_id = %s
                        ORDER BY created_at
                    """, (thread_id,))
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    def get_thread(self, thread_id: int) -> Optional[Dict]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM threads WHERE id = %s", (thread_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def update_summary(self, thread_id: int, summary: str, through_turn_id: int):
        """Store compacted summary, marking which turns it covers."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE threads
                    SET summary = %s, summary_through_turn_id = %s
                    WHERE id = %s
                """, (summary, through_turn_id, thread_id))
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)

    def garbage_collect(self, stale_hours: int = 24) -> int:
        """
        Delete threads (and their turns) that haven't been active
        within stale_hours. Returns count of deleted threads.
        """
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM threads
                    WHERE last_active_at < NOW() - INTERVAL '%s hours'
                    RETURNING id
                """, (stale_hours,))
                deleted = cur.rowcount
                conn.commit()
                if deleted:
                    logger.info(f"GC: deleted {deleted} stale threads (>{stale_hours}h)")
                return deleted
        finally:
            DatabaseConnection.return_connection(conn)

    def clear_thread(self, thread_id: int):
        """Clear all turns and summary for a thread (the 'refresh' button)."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM thread_turns WHERE thread_id = %s", (thread_id,))
                cur.execute("""
                    UPDATE threads SET summary = NULL, summary_through_turn_id = NULL
                    WHERE id = %s
                """, (thread_id,))
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)
