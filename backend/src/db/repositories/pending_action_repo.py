"""
Data access for the draft-approval gate (pending_actions).

One table, org-scoped:

  pending_actions — outbound/destructive claw actions awaiting human approval.

The repo never decides whether an action SHOULD be gated (that is
services.gated_actions) nor performs the action (that is the caller/executor).
Here we only persist and transition state. Org isolation is enforced by every
state-change method requiring the caller's org_id; an action belonging to a
different org is invisible and untouchable.

Status transitions enforced by CHECK constraint in the DB schema (see
migrations/015_pending_actions.sql). We also validate in Python so callers get
clear errors before round-tripping to Postgres.

Follows the GoalRepo conventions: commits eagerly, returns plain dicts via
RealDictCursor, initializes the shared pool on construction.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from psycopg2 import extras

from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


VALID_STATUSES = {"pending", "approved", "rejected", "executed", "failed"}


class PendingActionRepo:
    """All methods commit eagerly. Reads use RealDictCursor."""

    def __init__(self):
        DatabaseConnection.initialize_pool()

    # ------------------------------------------------------------- Create

    def create(
        self,
        org_id: int,
        action_type: str,
        acting_identity: str,
        target: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        preview: Optional[str] = None,
        instance_id: Optional[int] = None,
        goal_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a new 'pending' action. Returns the new row."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO pending_actions (
                        org_id, instance_id, goal_id, action_type, target,
                        payload, preview, acting_identity
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        org_id,
                        instance_id,
                        goal_id,
                        action_type,
                        target,
                        extras.Json(payload if payload is not None else {}),
                        preview,
                        acting_identity,
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row)
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    # ------------------------------------------------------------- Reads

    def get(self, action_id: str) -> Optional[Dict[str, Any]]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM pending_actions WHERE id = %s", (action_id,)
                )
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def list_for_org(
        self,
        org_id: int,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List actions for an org, newest request first, optionally by status."""
        if status is not None and status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status!r}")

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                if status:
                    cur.execute(
                        """
                        SELECT * FROM pending_actions
                        WHERE org_id = %s AND status = %s
                        ORDER BY requested_at DESC
                        LIMIT %s
                        """,
                        (org_id, status, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM pending_actions
                        WHERE org_id = %s
                        ORDER BY requested_at DESC
                        LIMIT %s
                        """,
                        (org_id, limit),
                    )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    # ------------------------------------------------------------- Transitions

    def set_decision(
        self,
        action_id: str,
        org_id: int,
        to_status: str,
        approver: str,
        decision_reason: Optional[str] = None,
        from_status: str = "pending",
    ) -> Optional[Dict[str, Any]]:
        """
        Move a pending action to approved/rejected. Org-scoped and
        status-guarded in a single UPDATE: only a row that belongs to org_id
        AND is currently `from_status` is affected. Returns the updated row,
        or None when nothing matched (wrong org, unknown id, or not pending).
        """
        if to_status not in ("approved", "rejected"):
            raise ValueError(f"set_decision only handles approved/rejected, got {to_status!r}")

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE pending_actions
                    SET status = %s,
                        approver = %s,
                        decision_reason = %s,
                        decided_at = NOW()
                    WHERE id = %s AND org_id = %s AND status = %s
                    RETURNING *
                    """,
                    (to_status, approver, decision_reason, action_id, org_id, from_status),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row) if row else None
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def mark_executed(
        self, action_id: str, org_id: int, from_status: str = "approved"
    ) -> Optional[Dict[str, Any]]:
        """Mark an approved action as executed. Org- and status-guarded."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE pending_actions
                    SET status = 'executed', executed_at = NOW(), error = NULL
                    WHERE id = %s AND org_id = %s AND status = %s
                    RETURNING *
                    """,
                    (action_id, org_id, from_status),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row) if row else None
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def mark_failed(
        self,
        action_id: str,
        org_id: int,
        error: str,
        from_status: str = "approved",
    ) -> Optional[Dict[str, Any]]:
        """Mark an approved action as failed, recording the error. Guarded."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE pending_actions
                    SET status = 'failed', executed_at = NOW(), error = %s
                    WHERE id = %s AND org_id = %s AND status = %s
                    RETURNING *
                    """,
                    (error, action_id, org_id, from_status),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row) if row else None
        except Exception:
            conn.rollback()
            raise
        finally:
            DatabaseConnection.return_connection(conn)
