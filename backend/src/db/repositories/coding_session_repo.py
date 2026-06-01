"""
Data access for coding-agent sessions.

One coding session per intention thread (threads.id). Maps a thread to a
Claude Agent SDK session, the model chosen for it, and an isolated git worktree.
Additive: this repo only touches the `coding_sessions` table from migration 013.
"""

import logging
from typing import Dict, Optional

from psycopg2 import extras

from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class CodingSessionRepo:

    def __init__(self):
        DatabaseConnection.initialize_pool()

    def get_or_create_session(
        self,
        thread_id: int,
        model: str,
        instance_id: Optional[int] = None,
        repo_url: Optional[str] = None,
    ) -> Dict:
        """
        Get the coding session for a thread, or create one.

        The model is set only on creation (chosen at thread start, kept stable
        for prompt-cache continuity). Use set_model() to deliberately escalate.
        """
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM coding_sessions WHERE thread_id = %s",
                    (thread_id,),
                )
                row = cur.fetchone()
                if row:
                    return dict(row)

                cur.execute(
                    """
                    INSERT INTO coding_sessions (thread_id, instance_id, model, repo_url)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                    """,
                    (thread_id, instance_id, model, repo_url),
                )
                row = cur.fetchone()
                conn.commit()
                logger.info("Created coding session %s for thread %s (model=%s)",
                            row["id"], thread_id, model)
                return dict(row)
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def get_session(self, session_id: str) -> Optional[Dict]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM coding_sessions WHERE id = %s", (session_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def get_by_thread(self, thread_id: int) -> Optional[Dict]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM coding_sessions WHERE thread_id = %s", (thread_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def set_status(self, session_id: str, status: str) -> None:
        self._update(session_id, status=status)

    def attach_sdk_session(self, session_id: str, sdk_session_id: str) -> None:
        """Record the Claude Agent SDK session id once a worker has one."""
        self._update(session_id, sdk_session_id=sdk_session_id)

    def set_worktree(self, session_id: str, worktree_path: str) -> None:
        self._update(session_id, worktree_path=worktree_path)

    def set_model(self, session_id: str, model: str) -> None:
        """Deliberately change the model (escalation). Costs one cache rewrite."""
        self._update(session_id, model=model)

    # -- internal -----------------------------------------------------------

    _ALLOWED = {"status", "sdk_session_id", "worktree_path", "model", "repo_url"}

    def _update(self, session_id: str, **fields) -> None:
        bad = set(fields) - self._ALLOWED
        if bad:
            raise ValueError(f"Not updatable: {sorted(bad)}")
        if not fields:
            return
        cols = ", ".join(f"{k} = %s" for k in fields)
        params = list(fields.values()) + [session_id]
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE coding_sessions SET {cols}, updated_at = NOW() WHERE id = %s",
                    params,
                )
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)
