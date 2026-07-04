"""
Data access for org membership — a person's membership in N organizations.

Source of truth for "who belongs to which org" (migration 020). Replaces the
single platform_users.org_id column, which is retained + readable but deprecated.
"""

import logging
from typing import Dict, List
from psycopg2 import extras
from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)

VALID_SOURCES = ("manual", "linkedclaims")


class OrgMemberRepo:

    def __init__(self):
        DatabaseConnection.initialize_pool()

    def memberships(self, user_id: int) -> List[Dict]:
        """Every org this person belongs to, with their role in each.

        Returns a list of {org_id, role, source, created_at}, ordered by org_id.
        Empty list if the person is a member of no org.
        """
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT org_id, role, source, created_at
                    FROM org_members
                    WHERE user_id = %s
                    ORDER BY org_id
                    """,
                    (user_id,),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    def members_of(self, org_id: int) -> List[Dict]:
        """Every member of an org: {user_id, role, source, created_at}."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT user_id, role, source, created_at
                    FROM org_members
                    WHERE org_id = %s
                    ORDER BY user_id
                    """,
                    (org_id,),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    def add_member(
        self,
        org_id: int,
        user_id: int,
        role: str = "member",
        source: str = "manual",
    ) -> Dict:
        """Idempotently record a membership. On re-add, the role/source are
        refreshed (last write wins) so callers can use this to promote a role.
        Returns the resulting {org_id, user_id, role, source, created_at} row.
        """
        if source not in VALID_SOURCES:
            raise ValueError(
                f"invalid membership source {source!r}; expected one of {VALID_SOURCES}"
            )
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO org_members (org_id, user_id, role, source)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (org_id, user_id) DO UPDATE
                        SET role = EXCLUDED.role, source = EXCLUDED.source
                    RETURNING org_id, user_id, role, source, created_at
                    """,
                    (org_id, user_id, role or "member", source),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row)
        finally:
            DatabaseConnection.return_connection(conn)

    def is_member(self, org_id: int, user_id: int) -> bool:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM org_members WHERE org_id = %s AND user_id = %s",
                    (org_id, user_id),
                )
                return cur.fetchone() is not None
        finally:
            DatabaseConnection.return_connection(conn)
