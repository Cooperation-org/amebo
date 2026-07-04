"""
Data access for the Goal/Claw subsystem.

Two tables, both per-org:

  goals        — declared intentions for the claw to pursue
  goal_events  — append-only audit trail of every action on a goal

The repo never decides *what* to do with a goal; that lives in
services.goal_engine and services.goal_dispatcher. Here we only persist.

Status transitions enforced by CHECK constraint in the DB schema (see
migrations/009_goals_and_events.sql) — we still validate in Python so
callers get clear errors before round-tripping to Postgres.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from psycopg2 import extras

from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


VALID_STATUSES = {"pending", "active", "completed", "failed", "paused", "waiting_user"}
VALID_ACTOR_TYPES = {"user", "claw", "system"}


class GoalRepo:
    """
    All methods commit eagerly. Reads use a RealDictCursor so callers get
    plain dicts rather than tuples — easier to log and to pass through to
    JSON responses unchanged.
    """

    def __init__(self):
        DatabaseConnection.initialize_pool()

    # ------------------------------------------------------------------ Goals

    def create(
        self,
        org_id: int,
        title: str,
        description: Optional[str] = None,
        target_criteria: Optional[Dict[str, Any]] = None,
        trigger_config: Optional[Dict[str, Any]] = None,
        notify_channel: Optional[str] = None,
        created_by_user_id: Optional[int] = None,
        assigned_to_user_id: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new goal in 'pending' status. Returns the new row."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO goals (
                        org_id, title, description, target_criteria,
                        trigger_config, notify_channel,
                        created_by_user_id, assigned_to_user_id,
                        config
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        org_id,
                        title,
                        description,
                        extras.Json(target_criteria) if target_criteria is not None else None,
                        extras.Json(trigger_config) if trigger_config is not None else None,
                        notify_channel,
                        created_by_user_id,
                        assigned_to_user_id,
                        extras.Json(config) if config is not None else extras.Json({}),
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row)
        finally:
            DatabaseConnection.return_connection(conn)

    def get(self, goal_id: str) -> Optional[Dict[str, Any]]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM goals WHERE id = %s", (goal_id,))
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
        """List goals for an org, newest first, optionally filtered by status."""
        if status is not None and status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status!r}")

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                if status:
                    cur.execute(
                        """
                        SELECT * FROM goals
                        WHERE org_id = %s AND status = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (org_id, status, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM goals
                        WHERE org_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (org_id, limit),
                    )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    def list_pending(self, org_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Pending goals across all orgs (used by the scheduler when no
        org filter is needed) or for a single org.
        """
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                if org_id is None:
                    cur.execute(
                        "SELECT * FROM goals WHERE status = 'pending' "
                        "ORDER BY created_at ASC"
                    )
                else:
                    cur.execute(
                        "SELECT * FROM goals WHERE status = 'pending' AND org_id = %s "
                        "ORDER BY created_at ASC",
                        (org_id,),
                    )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    def set_status(
        self,
        goal_id: str,
        status: str,
        completed: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Transition a goal to a new status. When `completed` is True the
        completed_at timestamp is set; otherwise it stays NULL.
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status!r}")

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                if completed:
                    cur.execute(
                        """
                        UPDATE goals
                        SET status = %s, updated_at = NOW(), completed_at = NOW()
                        WHERE id = %s
                        RETURNING *
                        """,
                        (status, goal_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE goals
                        SET status = %s, updated_at = NOW()
                        WHERE id = %s
                        RETURNING *
                        """,
                        (status, goal_id),
                    )
                row = cur.fetchone()
                conn.commit()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    # --------------------------------------------------------------- Deletion

    def delete(self, goal_id: str, org_id: int) -> bool:
        """Hard-delete a goal. Returns True if a row was deleted, False if
        the goal id was unknown or belonged to a different org. The
        goal_events FK is `ON DELETE CASCADE`, so the audit trail goes with
        the goal."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM goals WHERE id = %s AND org_id = %s",
                    (goal_id, org_id),
                )
                deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        finally:
            DatabaseConnection.return_connection(conn)

    # ---------------------------------------------------------------- Events

    def append_event(
        self,
        goal_id: str,
        actor_type: str,
        action: str,
        actor_user_id: Optional[int] = None,
        result_summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        parent_event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Append an event to a goal's audit trail. Step index is auto-assigned
        as the next integer for this goal (under a single transaction so
        concurrent appends do not collide on the same index).

        parent_event_id links this event to the one that caused it (WP19
        attribution chain), e.g. a tool_call to its dispatch. NULL = top-level.
        """
        if actor_type not in VALID_ACTOR_TYPES:
            raise ValueError(f"Invalid actor_type: {actor_type!r}")

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Lock the goal row so step_index allocation is consistent.
                cur.execute("SELECT id FROM goals WHERE id = %s FOR UPDATE", (goal_id,))
                if cur.fetchone() is None:
                    raise LookupError(f"Goal not found: {goal_id}")

                cur.execute(
                    "SELECT COALESCE(MAX(step_index), -1) + 1 AS next_idx "
                    "FROM goal_events WHERE goal_id = %s",
                    (goal_id,),
                )
                next_idx = cur.fetchone()["next_idx"]

                cur.execute(
                    """
                    INSERT INTO goal_events (
                        goal_id, step_index, actor_user_id, actor_type,
                        action, result_summary, metadata, parent_event_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        goal_id,
                        next_idx,
                        actor_user_id,
                        actor_type,
                        action,
                        result_summary,
                        extras.Json(metadata) if metadata is not None else None,
                        parent_event_id,
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

    def list_events(self, goal_id: str, limit: int = 500) -> List[Dict[str, Any]]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM goal_events
                    WHERE goal_id = %s
                    ORDER BY step_index ASC
                    LIMIT %s
                    """,
                    (goal_id, limit),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)
