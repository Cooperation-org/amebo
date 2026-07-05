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

    def recent_for_org(self, org_id: int, limit: int = 5) -> List[Dict]:
        """
        Recent threads for an org, newest-active first.

        Bridges threads to org via `instance_id → instances.org_id` first;
        falls back to `workspace_id → workspaces.org_id` for threads that
        predate the org→instance wiring (no instance_id stamped).

        Returns rows: {id, source_type, source_ref, title, last_active_at}.
        """
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT t.id, t.source_type, t.source_ref, t.title, t.last_active_at
                    FROM threads t
                    LEFT JOIN instances  i ON t.instance_id  = i.id
                    LEFT JOIN workspaces w ON t.workspace_id = w.workspace_id
                    WHERE i.org_id = %s OR w.org_id = %s
                    ORDER BY t.last_active_at DESC NULLS LAST
                    LIMIT %s
                    """,
                    (org_id, org_id, limit),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    def stamp_web_thread_user(self, source_ref: str, workspace_id: Optional[str], user_id: int):
        """Record the owner on a web thread (once). Lets the dashboard list a user
        their OWN conversations. Only sets it when unset — never reassigns."""
        if not user_id or not source_ref:
            return
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE threads SET user_id = %s
                    WHERE source_type = 'web' AND source_ref = %s
                      AND workspace_id IS NOT DISTINCT FROM %s
                      AND user_id IS NULL
                    """,
                    (user_id, source_ref, workspace_id),
                )
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)

    def web_threads_for_user(self, user_id: int, limit: int = 30) -> List[Dict]:
        """A user's own web conversations, newest-active first, with a snippet
        from the first user message. Read-only; scoped to the user (privacy)."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT t.id, t.source_ref, t.title, t.last_active_at,
                           (SELECT tt.content FROM thread_turns tt
                            WHERE tt.thread_id = t.id AND tt.role = 'user'
                            ORDER BY tt.id ASC LIMIT 1) AS first_user_msg
                    FROM threads t
                    WHERE t.user_id = %s AND t.source_type = 'web'
                    ORDER BY t.last_active_at DESC NULLS LAST
                    LIMIT %s
                    """,
                    (user_id, limit),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    def web_thread_turns_for_user(self, source_ref: str, user_id: int) -> Optional[List[Dict]]:
        """Turns of a user's own web thread (for resume). Returns None if the
        thread doesn't exist or isn't owned by this user (fail closed)."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id FROM threads
                    WHERE source_type = 'web' AND source_ref = %s AND user_id = %s
                    """,
                    (source_ref, user_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cur.execute(
                    """
                    SELECT role, content, created_at FROM thread_turns
                    WHERE thread_id = %s ORDER BY id ASC
                    """,
                    (row['id'],),
                )
                return [dict(r) for r in cur.fetchall()]
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
