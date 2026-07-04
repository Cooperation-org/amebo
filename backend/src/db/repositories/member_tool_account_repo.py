"""
Attribution map (I7): a team member's account inside a shared tool — their Taiga
username, Odoo user, Slack handle for @-mentions. This is amebo's operational
data (member_tool_accounts, mig 019), NOT abra (decided 2026-07-04). Amebo reads
it to mention a person, assign a task, or log CRM activity.

Recognition (who is speaking → person) is separate and lives in
person_identities (see PersonIdentityRepo). This is the other direction: given a
person, how do we address them inside the org's tools.
"""

import logging
from typing import Dict, List, Optional
from psycopg2 import extras
from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class MemberToolAccountRepo:

    def __init__(self):
        DatabaseConnection.initialize_pool()

    def external_id(self, org_id: int, user_id: int, tool_key: str) -> Optional[str]:
        """The person's external id in a tool (e.g. their Slack Uxxxx, Taiga user
        id). None if unmapped. Skips 'failed' provisioning rows."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT external_id FROM member_tool_accounts
                    WHERE org_id = %s AND user_id = %s AND tool_key = %s
                      AND external_id IS NOT NULL AND state <> 'failed'
                    ORDER BY (state = 'linked') DESC, id
                    LIMIT 1
                    """,
                    (org_id, user_id, tool_key),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def slack_mention(self, org_id: int, user_id: int) -> Optional[str]:
        """Convenience: the person's Slack id for an @-mention."""
        return self.external_id(org_id, user_id, "slack")

    def by_username(self, org_id: int, tool_key: str, external_username: str) -> Optional[str]:
        """Resolve a tool handle (username) to its external id within an org."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT external_id FROM member_tool_accounts
                    WHERE org_id = %s AND tool_key = %s
                      AND external_username ILIKE %s AND external_id IS NOT NULL
                    LIMIT 1
                    """,
                    (org_id, tool_key, external_username),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def accounts_for(self, org_id: int, user_id: int) -> List[Dict]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT tool_key, external_id, external_username, granted_role, state "
                    "FROM member_tool_accounts WHERE org_id = %s AND user_id = %s "
                    "ORDER BY tool_key",
                    (org_id, user_id),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    def link(self, org_id: int, user_id: int, tool_key: str, external_id: str,
             external_username: Optional[str] = None, state: str = "linked") -> Dict:
        """Idempotently record a member's account in a tool (provisioning/admin).
        Keyed on the external account per mig 019's uq_mta_extern."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO member_tool_accounts
                        (org_id, user_id, tool_key, external_id, external_username, state)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (org_id, tool_key, external_id)
                        WHERE external_id IS NOT NULL DO UPDATE
                        SET user_id = EXCLUDED.user_id,
                            external_username = COALESCE(EXCLUDED.external_username,
                                                         member_tool_accounts.external_username),
                            state = EXCLUDED.state
                    RETURNING org_id, user_id, tool_key, external_id, external_username, state
                    """,
                    (org_id, user_id, tool_key, external_id, external_username, state),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row)
        finally:
            DatabaseConnection.return_connection(conn)
