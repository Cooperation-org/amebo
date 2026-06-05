"""
Data access for poller state (migration 014): idempotency + dead-letter.
"""

import logging
from typing import Dict, List, Optional

from psycopg2 import extras

from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class MailPollerRepo:

    def __init__(self):
        DatabaseConnection.initialize_pool()

    # -- idempotency --------------------------------------------------------

    def is_seen(self, message_id: str) -> bool:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM mail_seen WHERE message_id = %s", (message_id,))
                return cur.fetchone() is not None
        finally:
            DatabaseConnection.return_connection(conn)

    def mark_seen(self, message_id: str) -> None:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO mail_seen (message_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    (message_id,),
                )
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def purge_seen(self, ttl_days: int) -> int:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM mail_seen WHERE seen_at < NOW() - (%s || ' days')::interval",
                    (ttl_days,),
                )
                n = cur.rowcount
                conn.commit()
                return n
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    # -- dead-letter --------------------------------------------------------

    def dead_letter(self, reason: str, message_id: Optional[str] = None,
                    from_addr: Optional[str] = None, to_addrs: Optional[str] = None,
                    subject: Optional[str] = None, tag: Optional[str] = None,
                    detail: Optional[str] = None) -> None:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mail_dead_letter
                        (reason, message_id, from_addr, to_addrs, subject, tag, detail)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (reason, message_id, from_addr, to_addrs, subject, tag, detail),
                )
                conn.commit()
            logger.info("dead-letter: reason=%s from=%s subject=%r", reason, from_addr, subject)
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def list_dead_letter(self, limit: int = 50) -> List[Dict]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM mail_dead_letter ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)
