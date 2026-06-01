"""
Data access for the coding-agent work queue (`coding_jobs`, migration 013).

This repo is where per-session serialization and ordering live, in Postgres:

- enqueue(): assigns a per-session monotonic `seq` under a session advisory
  lock, so ordering is correct and there are no seq collisions.
- claim_next(): atomically claims the oldest queued job for a session that has
  no job already running, guarded by a non-blocking advisory lock keyed on the
  session id. This guarantees at most one job per session is in flight, even
  with many concurrent workers, and lets workers skip busy sessions
  (FOR UPDATE SKIP LOCKED) instead of blocking.
"""

import logging
from typing import Dict, List, Optional

from psycopg2 import extras
from psycopg2.extras import Json

from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class CodingJobRepo:

    def __init__(self):
        DatabaseConnection.initialize_pool()

    def enqueue(self, session_id: str, prompt: str, payload: Optional[Dict] = None) -> Dict:
        """
        Append a job to a session's queue. The seq is assigned under a blocking
        advisory lock on the session so concurrent enqueues stay ordered and
        never collide on UNIQUE (session_id, seq).
        """
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Serialize seq assignment for this session only. The xact lock
                # releases on commit/rollback below.
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (session_id,))
                cur.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM coding_jobs WHERE session_id = %s",
                    (session_id,),
                )
                next_seq = cur.fetchone()["next_seq"]
                cur.execute(
                    """
                    INSERT INTO coding_jobs (session_id, seq, prompt, payload)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                    """,
                    (session_id, next_seq, prompt, Json(payload or {})),
                )
                row = cur.fetchone()
                conn.commit()
                logger.info("Enqueued coding job %s (session=%s seq=%s)",
                            row["id"], session_id, next_seq)
                return dict(row)
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def claim_next(self) -> Optional[Dict]:
        """
        Atomically claim the next runnable job and mark it 'running'.

        Returns the claimed job dict, or None if nothing is runnable right now
        (queue empty, or every queued session already has a job in flight).
        """
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    WITH next AS (
                        SELECT j.id
                        FROM coding_jobs j
                        WHERE j.status = 'queued'
                          AND NOT EXISTS (
                              SELECT 1 FROM coding_jobs r
                              WHERE r.session_id = j.session_id AND r.status = 'running'
                          )
                          AND pg_try_advisory_xact_lock(hashtext(j.session_id::text))
                        ORDER BY j.session_id, j.seq
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE coding_jobs
                    SET status = 'running', started_at = NOW(), attempts = attempts + 1
                    FROM next
                    WHERE coding_jobs.id = next.id
                    RETURNING coding_jobs.*
                    """
                )
                row = cur.fetchone()
                conn.commit()
                if row:
                    logger.info("Claimed coding job %s (session=%s seq=%s)",
                                row["id"], row["session_id"], row["seq"])
                return dict(row) if row else None
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def complete(self, job_id: str, result: str) -> None:
        self._finish(job_id, status="done", result=result)

    def fail(self, job_id: str, error: str) -> None:
        self._finish(job_id, status="error", error=error)

    def get_job(self, job_id: str) -> Optional[Dict]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM coding_jobs WHERE id = %s", (job_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def list_for_session(self, session_id: str) -> List[Dict]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM coding_jobs WHERE session_id = %s ORDER BY seq",
                    (session_id,),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    # -- internal -----------------------------------------------------------

    def _finish(self, job_id: str, status: str, result: Optional[str] = None,
                error: Optional[str] = None) -> None:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE coding_jobs
                    SET status = %s, result = %s, error = %s, finished_at = NOW()
                    WHERE id = %s
                    """,
                    (status, result, error, job_id),
                )
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)
