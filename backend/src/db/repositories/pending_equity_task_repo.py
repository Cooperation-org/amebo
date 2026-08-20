"""
Repository for pending_equity_tasks — tracks Discord /drop-task equity
pending Taiga Done webhook, then the GovKit DropLine distribution result.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from psycopg2 import extras

from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class PendingEquityTaskRepo:
    """Create / update / find pending-equity-task rows."""

    def create(
        self,
        taiga_ref: int,
        taiga_project: str,
        org_id: int,
        govkit_org_slug: str,
        discord_user_id: str,
        discord_username: str,
        assignee: Optional[str],
        subject: str,
        equity: int = 0,
        cash: int = 0,
    ) -> int:
        """Insert a row, return its pk."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pending_equity_tasks
                        (taiga_ref, taiga_project, org_id, govkit_org_slug,
                         discord_user_id, discord_username, assignee, subject,
                         equity, cash, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'in_progress')
                    RETURNING id
                    """,
                    (taiga_ref, taiga_project, org_id, govkit_org_slug,
                     discord_user_id, discord_username, assignee, subject,
                     equity, cash),
                )
                row = cur.fetchone()
                conn.commit()
                return row[0]
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def mark_done(
        self,
        id: int,
        govkit_membership_id: Optional[int] = None,
        drop_run_id: Optional[int] = None,
        drop_line_id: Optional[int] = None,
    ) -> None:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pending_equity_tasks
                    SET status = 'done',
                        govkit_membership_id = COALESCE(%s, govkit_membership_id),
                        drop_run_id = COALESCE(%s, drop_run_id),
                        drop_line_id = COALESCE(%s, drop_line_id),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (govkit_membership_id, drop_run_id, drop_line_id, id),
                )
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def mark_failed(self, id: int, error: str) -> None:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pending_equity_tasks
                    SET status = 'failed', error = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (error, id),
                )
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def find_by_taiga_ref(self, project: str, ref: int) -> Optional[Dict[str, Any]]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, taiga_ref, taiga_project, org_id, discord_user_id,
                           discord_username, assignee, subject, equity, cash, status,
                           govkit_membership_id, drop_run_id, drop_line_id, error,
                           created_at, updated_at
                    FROM pending_equity_tasks
                    WHERE taiga_project = %s AND taiga_ref = %s
                    """,
                    (project, ref),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cols = [c[0] for c in cur.description]
                return dict(zip(cols, row))
        finally:
            DatabaseConnection.return_connection(conn)

    def find_pending(self, org_id: int) -> List[Dict[str, Any]]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, taiga_ref, taiga_project, org_id, discord_user_id,
                           discord_username, assignee, subject, equity, cash, status,
                           govkit_membership_id, drop_run_id, drop_line_id, error,
                           created_at, updated_at
                    FROM pending_equity_tasks
                    WHERE org_id = %s AND status = 'in_progress'
                    ORDER BY created_at ASC
                    """,
                    (org_id,),
                )
                cols = [c[0] for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)
